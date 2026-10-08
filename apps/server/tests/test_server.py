from __future__ import annotations

import asyncio

import httpx
import pytest
from simp_agent.ai import AssistantMessage, TextContent, ToolCall
from simp_agent.testing import FakeProvider

from simp_server import protocol as p
from simp_server.server import create_app, load_settings


def reply(text="done", calls=()):
    return AssistantMessage([TextContent(text), *calls], stop_reason="tool_use" if calls else "stop",
                            usage={"input": 10, "output": 5})


def bash(cid, cmd):
    return reply("", [ToolCall(cid, "bash", {"command": cmd})])


class Gated:
    """stream_fn that streams text in chunks; each chunk waits for `go` to be set (then clears it)."""

    def __init__(self, chunks):
        self.chunks, self.go, self.calls = chunks, asyncio.Event(), 0

    async def __call__(self, model, ctx, api_key=None):
        self.calls += 1
        msg = reply("".join(self.chunks))
        yield {"type": "start", "partial": msg}
        for c in self.chunks:
            await self.go.wait()
            self.go.clear()
            yield {"type": "text_delta", "delta": c}
        yield {"type": "done", "message": msg}


async def wait_for(cond, timeout=5):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timeout")


def drain(q):
    out = list()
    while not q.empty():
        out.append(q.get_nowait())
    return out


@pytest.fixture
async def env(tmp_path):
    (tmp_path / "settings.toml").write_text('[profiles.test]\napi = "fake"\nmodel = "m"\n')
    settings = load_settings(tmp_path)
    made = list()

    async def make(stream_fn):
        app = create_app(settings, stream_fn)
        mgr = app.state.mgr
        await mgr.store.open()
        token = await mgr.store.add_user(f"u{len(made)}")
        user = await mgr.store.user_by_token(token)
        row = await mgr.store.add_session(user["id"], "test")
        made.append(mgr)
        return app, mgr, user, token, await mgr.get(user, row["id"])

    yield make
    for m in made:
        await m.store.close()


async def test_reconnect_with_last_event_id_no_gaps_or_dups(env):
    _, _, _, _, run = await env(FakeProvider(reply("a"), reply("b")))
    first, q = run.subscribe(0)
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: run.state == "idle")
    seen = [e for e in first + drain(q) if "seq" in e][:3]
    run.subs.discard(q)  # the tab closes after seeing part of the log
    await run.command(p.Prompt(text="again"))
    await wait_for(lambda: run.state == "idle" and run.task.done())
    again, _ = run.subscribe(seen[-1]["seq"])
    seqs = [e["seq"] for e in seen + again if "seq" in e]
    assert seqs == [e["seq"] for e in run.log]  # every durable event exactly once, in order
    assert again[-1]["type"] == "snapshot" and again[-1]["last_seq"] == run.seq


async def test_mid_delta_reconnect_snapshot(env):
    g = Gated(["Hel", "lo ", "world"])
    _, _, _, _, run = await env(g)
    await run.command(p.Prompt(text="hi"))
    g.go.set()
    await wait_for(lambda: run.inflight.text == "Hel")
    g.go.set()
    await wait_for(lambda: run.inflight.text == "Hello ")
    first, q = run.subscribe(0)
    snap = first[-1]
    assert snap["type"] == "snapshot" and snap["in_flight"]["text"] == "Hello " and snap["run_state"] == "running"
    g.go.set()
    await wait_for(lambda: not q.empty())
    assert q.get_nowait() == {"type": "text_delta", "msg_id": snap["in_flight"]["msg_id"], "offset": 6, "delta": "world"}


async def test_approve_then_abort(env):
    _, _, _, _, run = await env(FakeProvider(bash("c1", "echo one"), bash("c2", "echo two"), reply()))
    _, q = run.subscribe(0)
    await run.command(p.Prompt(text="go"))
    await wait_for(lambda: run.pending and run.pending.call_id == "c1")
    await run.command(p.Approve(call_id="c1", decision="allow"))
    await wait_for(lambda: run.pending and run.pending.call_id == "c2")
    await run.command(p.Abort())
    await wait_for(lambda: run.state == "idle" and run.task.done())
    evs = [e for e in drain(q) if "seq" in e]
    kinds = [(e["type"], e.get("decision") or e.get("state")) for e in evs if e["type"] in ("approval_resolved", "run_state")]
    assert ("approval_resolved", "allow") in kinds and ("approval_resolved", "aborted") in kinds
    assert kinds[-1] == ("run_state", "idle")
    assert any(e["type"] == "tool_result" and "one" in e["content"] for e in evs)
    assert evs[-1]["type"] == "notice" and "aborted" in evs[-1]["text"]
    assert run.pending is None


async def test_closed_tabs_run_finishes_and_is_persisted(env):
    g = Gated(["a", "b"])
    _, mgr, user, _, run = await env(g)
    _, q = run.subscribe(0)
    await run.command(p.Prompt(text="hi"))
    g.go.set()
    run.subs.discard(q)  # every tab closed
    await wait_for(lambda: run.inflight.text == "a")
    g.go.set()
    await wait_for(lambda: run.state == "idle")
    rows = await mgr.store.entries(user["id"], run.sid)
    assert any(r["type"] == "assistant_message" and r["data"]["text"] == "ab" for r in rows)
    assert [r["data"]["role"] for r in rows if r["type"] == "msg"] == ["user", "assistant"]
    del mgr.runs[run.sid]  # like a restart: reload from SQLite
    again = await mgr.get(user, run.sid)
    assert [m.role for m in again.session.messages] == ["user", "assistant"] and again.log == run.log


async def test_two_tabs_both_receive(env):
    _, _, _, _, run = await env(FakeProvider(reply("x")))
    _, q1 = run.subscribe(0)
    _, q2 = run.subscribe(0)
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: run.state == "idle")
    a, b = drain(q1), drain(q2)
    assert a == b and any(e["type"] == "assistant_message" for e in a)


async def test_prompt_while_busy_is_follow_up_and_usage_recorded(env):
    g = Gated(["x"])
    _, mgr, user, _, run = await env(g)
    await run.command(p.Prompt(text="one"))
    await run.command(p.Prompt(text="two"))  # busy -> follow_up, not an error
    g.go.set()
    await wait_for(lambda: g.calls == 2)
    g.go.set()
    await wait_for(lambda: run.state == "idle" and run.task.done())
    assert [e["text"] for e in run.log if e["type"] == "user_message"] == ["one", "two"]
    usage = await mgr.store.usage(user["id"])
    assert len(usage) == 2 and (usage[0]["input"], usage[0]["output"], usage[0]["model"]) == (10, 5, "m")


async def test_http_auth_host_and_files(env):
    app, _, _, token, run = await env(FakeProvider())
    auth = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.get("/api/sessions", headers={"Authorization": "Bearer nope"})).status_code == 401
        assert (await c.get("/api/sessions")).status_code == 401
        assert (await c.get("/api/sessions", headers={**auth, "Host": "evil.com"})).status_code == 403
        new = await c.post("/api/sessions", headers=auth, json={})
        assert new.status_code == 200 and new.json()["run_state"] == "idle"
        assert len((await c.get("/api/sessions", headers=auth)).json()) == 2
        assert (await c.post("/api/sessions", headers=auth, json={"profile": "nope"})).status_code == 400
        base = f"/api/sessions/{run.sid}/files"
        assert (await c.put(base + "/raw?path=dir/a.bin", headers=auth, content=b"\x00\x01hi")).status_code == 200
        assert (await c.get(base + "?path=dir", headers=auth)).json() == [{"name": "a.bin", "is_dir": False, "size": 4}]
        assert (await c.get(base + "/raw?path=dir/a.bin", headers=auth)).content == b"\x00\x01hi"
        assert (await c.get(base + "/raw?path=../../simp.db", headers=auth)).status_code == 403
        assert (await c.put(base + "/raw?path=/etc/x", headers=auth, content=b"x")).status_code == 403
        assert (await c.get(base + "/raw?path=missing", headers=auth)).status_code == 404
        assert (await c.get("/api/sessions/nope/files", headers=auth)).status_code == 404


async def test_run_through_docker_sandbox_and_close_on_shutdown(tmp_path):
    import shutil
    import subprocess

    from simp_server.sandboxes.docker import IMAGE

    ok = shutil.which("docker") and not subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode
    if not ok:  # needs `simp-server build-sandbox`
        pytest.skip("docker not available")
    (tmp_path / "settings.toml").write_text('[plugins]\nsandbox = "simp_server.sandboxes.docker:DockerSandbox"\n'
                                            '[profiles.test]\napi = "fake"\nmodel = "m"\n')
    app = create_app(load_settings(tmp_path), FakeProvider(bash("c1", "echo hi > out.txt; whoami"), reply()))
    mgr = app.state.mgr
    async with app.router.lifespan_context(app):
        user = await mgr.store.user_by_token(await mgr.store.add_user("d"))
        run = await mgr.get(user, (await mgr.store.add_session(user["id"], "test"))["id"])
        await run.command(p.Prompt(text="go"))
        await wait_for(lambda: run.pending is not None, timeout=30)
        await run.command(p.Approve(call_id="c1", decision="allow"))
        await wait_for(lambda: run.state == "idle", timeout=30)
        result = next(e for e in run.log if e["type"] == "tool_result")
        assert not result["is_error"] and result["content"].strip() != "root"
        assert await run.env.read_bytes("out.txt") == b"hi\n"
        container = run.env.container
    assert subprocess.run(["docker", "inspect", container], capture_output=True).returncode != 0  # closed on shutdown
