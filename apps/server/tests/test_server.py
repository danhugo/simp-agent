from __future__ import annotations

import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import HTTPException
from simp_agent.ai import AssistantMessage, TextContent, ToolCall
from simp_agent.testing import FakeProvider

from simp_server import protocol as p
from simp_server.server import check_sandbox, create_app, load_settings


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

    async def make(stream_fn, title="t"):  # titled: no extra title LLM call unless a test asks for it
        app = create_app(settings, stream_fn)
        mgr = app.state.mgr
        await mgr.store.open()
        token = await mgr.store.add_user(f"u{len(made)}")
        user = await mgr.store.user_by_token(token)
        row = await mgr.store.add_session(user["id"], "test", title)
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
        run = await mgr.get(user, (await mgr.store.add_session(user["id"], "test", "t"))["id"])
        await run.command(p.Prompt(text="go"))
        await wait_for(lambda: run.pending is not None, timeout=30)
        await run.command(p.Approve(call_id="c1", decision="allow"))
        await wait_for(lambda: run.state == "idle", timeout=30)
        result = next(e for e in run.log if e["type"] == "tool_result")
        assert not result["is_error"] and result["content"].strip() != "root"
        assert await run.env.read_bytes("out.txt") == b"hi\n"
        container = run.env.container
    assert subprocess.run(["docker", "inspect", container], capture_output=True).returncode != 0  # closed on shutdown


async def test_profile_compat_reaches_responses_request(tmp_path):
    from simp_agent.ai import Context
    from simp_agent.ai.providers import openai_responses
    from simp_server.server import build_model
    (tmp_path / "settings.toml").write_text('[profiles.luna]\napi = "openai-responses"\nmodel = "gpt-6-luna"\n'
                                            'max_tokens = 32000\n[profiles.luna.compat]\nreasoning_effort = "low"\n')
    m = build_model(load_settings(tmp_path)["profiles"]["luna"])
    kw = openai_responses.request(m, Context("sys", []))
    assert kw["reasoning"] == {"effort": "low", "summary": "auto"} and kw["max_output_tokens"] == 32000


@asynccontextmanager
async def serve(app, mgr):
    """Real uvicorn on a free port (SSE needs real streaming). Yields (port, server); the exit shuts it down."""
    import socket

    import uvicorn
    from simp_server.server import SHUTDOWN_GRACE
    await mgr.store.close()  # the lifespan opens its own connection; a leaked one keeps pytest from exiting
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, timeout_graceful_shutdown=SHUTDOWN_GRACE,
                                        log_level="warning"))
    task = asyncio.create_task(srv.serve())
    await wait_for(lambda: srv.started)
    try:
        async with asyncio.timeout(10):
            yield port, srv
    finally:
        srv.should_exit = True
        await asyncio.wait_for(task, SHUTDOWN_GRACE + 5)


async def test_shutdown_with_open_sse_closes_sandboxes(env):
    app, mgr, _, token, run = await env(FakeProvider(reply()))
    run.ref = "ref-1"  # sandbox_ref, not the session id
    closed = list()

    async def close(ref):
        closed.append(ref)
    mgr.sandbox.close = close
    async with serve(app, mgr) as (port, srv), httpx.AsyncClient() as c:
        async with c.stream("GET", f"http://127.0.0.1:{port}/api/sessions/{run.sid}/events",
                            headers={"Authorization": f"Bearer {token}"}) as r:
            assert r.status_code == 200
            await wait_for(lambda: run.subs)  # client is connected
            srv.should_exit = True
            await wait_for(lambda: closed, 8)
    assert closed == ["ref-1"]


async def test_sse_heartbeat_and_disconnect(env, monkeypatch):
    import simp_server.server as srvmod
    monkeypatch.setattr(srvmod, "HEARTBEAT", 0.05)
    app, mgr, _, token, run = await env(FakeProvider(reply()))
    async with serve(app, mgr) as (port, _), httpx.AsyncClient() as c:
        async with c.stream("GET", f"http://127.0.0.1:{port}/api/sessions/{run.sid}/events",
                            headers={"Authorization": f"Bearer {token}"}) as r:
            async for line in r.aiter_lines():
                if line == ": ping":
                    break
        await wait_for(lambda: not run.subs)  # the closed client is gone


async def test_slow_client_dropped_never_blocks(env, monkeypatch):
    import simp_server.server as srvmod
    monkeypatch.setattr(srvmod, "QUEUE_MAX", 3)
    _, _, _, _, run = await env(FakeProvider(reply()))
    _, q = run.subscribe(0)
    for i in range(5):
        run._send({"type": "notice", "n": i})
    assert q not in run.subs and q.qsize() == 3


async def test_base_exception_never_leaves_run_busy(env):
    class Boom(BaseException):  # not an Exception: passes every `except Exception`
        pass

    async def boom(model, ctx, api_key=None):
        raise Boom()
        yield
    _, _, _, _, run = await env(boom)
    await run.command(p.Prompt(text="hi"))
    await asyncio.wait([run.task])
    assert isinstance(run.task.exception(), Boom)
    assert run.state == "error" and [e["type"] for e in run.log[-2:]] == ["run_state", "notice"]


async def test_caps_upload_and_queue(env):
    g = Gated(["a"])
    app, mgr, _, token, run = await env(g)
    mgr.settings["files_max_bytes"] = 10
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        url, h = f"/api/sessions/{run.sid}/files/raw?path=f", {"Authorization": f"Bearer {token}"}
        assert (await c.put(url, content=b"x" * 10, headers=h)).status_code == 200
        assert (await c.put(url, content=b"x" * 11, headers=h)).status_code == 413

        async def chunks():  # no content-length: the streamed check catches it
            for _ in range(3):
                yield b"x" * 5
        assert (await c.put(url, content=chunks(), headers=h)).status_code == 413
    await run.command(p.Prompt(text="hi"))
    for _ in range(20):
        await run.command(p.FollowUp(text="more"))
    with pytest.raises(HTTPException) as e:
        await run.command(p.Steer(text="one too many"))
    assert e.value.status_code == 429
    g.go.set()


def test_empty_key_ignored(tmp_path, monkeypatch):
    from simp_agent.plugins.redact_secrets import RedactSecrets
    from simp_server.server import take_keys
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=\nANTHROPIC_API_KEY=''\n")
    assert take_keys({"data_dir": str(tmp_path), "profiles": dict()}) == dict()
    r = RedactSecrets()
    r.setup(None, {"secrets": ["", "short"], "env": False})
    assert r.secrets == [] and r.mask("text") == "text"


async def test_restart_with_pending_approval(tmp_path):
    (tmp_path / "settings.toml").write_text('[profiles.test]\napi = "fake"\nmodel = "m"\n')
    settings = load_settings(tmp_path)
    app = create_app(settings, FakeProvider(bash("c1", "echo hi")))
    mgr = app.state.mgr
    await mgr.store.open()
    user = await mgr.store.user_by_token(await mgr.store.add_user("u"))
    sid = (await mgr.store.add_session(user["id"], "test", "t"))["id"]
    run = await mgr.get(user, sid)
    await run.command(p.Prompt(text="go"))
    await wait_for(lambda: run.pending is not None)
    run.durable = lambda *a, **k: asyncio.sleep(0)  # simulate the process dying: no finally-handler writes reach the db
    run.task.cancel()
    await asyncio.gather(run.task, return_exceptions=True)
    await mgr.store.close()

    app2 = create_app(settings, FakeProvider(reply("after")))
    mgr2 = app2.state.mgr
    await mgr2.store.open()
    try:
        run2 = await mgr2.get(user, sid)
        assert run2.state == "error" and run2.pending is None
        tail = [e["type"] for e in run2.log[-4:]]
        assert tail == ["approval_resolved", "tool_result", "run_state", "notice"]
        assert run2.log[-4]["decision"] == "aborted" and "interrupted" in run2.log[-1]["text"]
        await run2.command(p.Prompt(text="again"))  # usable afterwards (core repairs the dangling tool call)
        await wait_for(lambda: run2.state == "idle" and run2.task.done())
    finally:
        await mgr2.store.close()


async def test_continue_after_restart_mid_approval(tmp_path):
    (tmp_path / "settings.toml").write_text('[profiles.test]\napi = "fake"\nmodel = "m"\n')
    settings = load_settings(tmp_path)
    app = create_app(settings, FakeProvider(bash("c1", "echo hi")))
    mgr = app.state.mgr
    await mgr.store.open()
    user = await mgr.store.user_by_token(await mgr.store.add_user("u"))
    sid = (await mgr.store.add_session(user["id"], "test", "t"))["id"]
    run = await mgr.get(user, sid)
    await run.command(p.Prompt(text="go"))
    await wait_for(lambda: run.pending is not None)
    run.durable = lambda *a, **k: asyncio.sleep(0)
    run.task.cancel()
    await asyncio.gather(run.task, return_exceptions=True)
    await mgr.store.close()

    fp = FakeProvider(reply("resumed"))
    app2 = create_app(settings, fp)
    mgr2 = app2.state.mgr
    await mgr2.store.open()
    try:
        run2 = await mgr2.get(user, sid)
        await run2.command(p.Continue())
        await wait_for(lambda: not run2.busy and run2.task.done())
        assert fp.calls == 1 and run2.state == "idle"
        results = [e for e in run2.log if e["type"] == "tool_result"]
        assert results and results[-1]["call_id"] == "c1" and results[-1]["is_error"]
        assert not [e for e in run2.log if e["type"] == "notice" and "Cannot continue" in e["text"]]
        again = await mgr2.store.entries(user["id"], sid)  # the repair is durable: a later reload sees it
        assert any(e["type"] == "msg" and e["data"].get("tool_call_id") == "c1" for e in again)
    finally:
        await mgr2.store.close()


async def test_revoke_rotate(env):
    app, mgr, user, token, run = await env(FakeProvider(reply("a")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        h = {"Authorization": f"Bearer {token}"}
        assert (await c.get("/api/sessions", headers=h)).status_code == 200
        new = await mgr.store.rotate_token(user["name"])
        assert (await c.get("/api/sessions", headers=h)).status_code == 401
        assert (await c.get("/api/sessions", headers={"Authorization": f"Bearer {new}"})).status_code == 200
        await mgr.store.revoke(user["name"])
        assert (await c.get("/api/sessions", headers={"Authorization": f"Bearer {new}"})).status_code == 401


async def test_delete_running_session(env):
    gated = Gated(["a", "b"])
    app, mgr, user, token, run = await env(gated)
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: gated.calls == 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        h = {"Authorization": f"Bearer {token}"}
        r = await c.delete(f"/api/sessions/{run.sid}", headers=h)
        assert r.status_code == 200
        assert run.task.done() and run.sid not in mgr.runs
        assert (await c.delete(f"/api/sessions/{run.sid}", headers=h)).status_code == 404
        assert (await c.get(f"/api/sessions/{run.sid}/files", headers=h)).status_code == 404


async def test_allowed_hosts_configurable(tmp_path):
    (tmp_path / "settings.toml").write_text(
        'allowed_hosts = ["box.local"]\n[profiles.test]\napi = "fake"\nmodel = "m"\n')
    app = create_app(load_settings(tmp_path), FakeProvider())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://box.local") as c:
        assert (await c.post("/api/hello", json={"type": "hello", "protocol_version": 1})).status_code == 200
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.post("/api/hello", json={"type": "hello", "protocol_version": 1})).status_code == 403


def test_check_sandbox(tmp_path):
    s = load_settings(tmp_path)
    assert check_sandbox(s, 1) is None
    assert "LocalSandbox" in check_sandbox(s, 2)
    assert check_sandbox({**s, "allow_local_sandbox": True}, 2) is None
    s["plugins"]["sandbox"] = "simp_server.sandboxes.docker:DockerSandbox"
    assert check_sandbox(s, 5) is None


async def test_delete_removes_workspace_files(env):
    app, mgr, user, token, run = await env(FakeProvider(reply("a")))
    await run.env.write_bytes("a.txt", b"secret")
    root = Path(run.env.root)
    assert root.exists()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.delete(f"/api/sessions/{run.sid}", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    assert not root.exists()


async def test_revoked_user_cannot_spend(env):
    fp = FakeProvider(reply("a"))
    _, mgr, user, _, run = await env(fp)
    await mgr.store.revoke(user["name"])
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert fp.calls == 0 and run.state == "error"


async def test_open_stream_ends_when_token_rotated(env, monkeypatch):
    monkeypatch.setattr("simp_server.server.HEARTBEAT", 0.05)
    app, mgr, user, token, run = await env(FakeProvider(reply()))
    async with serve(app, mgr) as (port, _), httpx.AsyncClient() as c:
        async with c.stream("GET", f"http://127.0.0.1:{port}/api/sessions/{run.sid}/events",
                            headers={"Authorization": f"Bearer {token}"}) as r:
            await wait_for(lambda: run.subs)
            await mgr.store.rotate_token(user["name"])
            body = await asyncio.wait_for(r.aread(), 3)  # ends by itself at the next heartbeat
    assert b"snapshot" in body


async def test_count_users_ignores_revoked(env):
    _, mgr, user, _, _ = await env(FakeProvider())
    await mgr.store.add_user("other")
    await mgr.store.revoke("other")
    assert await mgr.store.count_users() == 1


# ---- Stage 3 task C: commands, plan mode, titles

def titled(text):
    return lambda ctx: reply(text) if ctx.system_prompt.startswith("Name this coding session") else reply("nope")


async def settle(run):
    await wait_for(lambda: not run.busy and run.task.done() and (run.title_task is None or run.title_task.done()))


async def test_title_set_once_event_and_usage(env):
    fp = FakeProvider(reply("a"), titled('"Fix the\nlogin bug"'), reply("b"))
    _, mgr, user, _, run = await env(fp, title="")
    q = run.subscribe(0)[1]
    await run.command(p.Prompt(text="x" * 3000))
    await settle(run)
    # reasoning models spend tokens thinking first: room for that, and the lowest effort every provider accepts
    assert fp.calls == 2 and fp.models[1].max_tokens == 200 and fp.models[1].compat["reasoning_effort"] == "low"
    assert fp.ctxs[1].messages[0].content == "x" * 2000
    ev = [e for e in drain(q) if e["type"] == "session_title"]
    assert [e["title"] for e in ev] == ["Fix the login bug"] and ev[0]["seq"] > 0
    assert (await mgr.store.get_session(user["id"], run.sid))["title"] == "Fix the login bug"
    assert run.subscribe(0)[0][-1]["title"] == "Fix the login bug"
    assert len(await mgr.store.usage(user["id"])) == 2
    await run.command(p.Prompt(text="again"))
    await settle(run)
    assert fp.calls == 3  # no second title call


async def test_title_error_keeps_empty(env):
    fp = FakeProvider(reply("a"), AssistantMessage(stop_reason="error", error="boom"))
    _, mgr, user, _, run = await env(fp, title="")
    await run.command(p.Prompt(text="hi"))
    await settle(run)
    assert fp.calls == 2 and run.state == "idle" and run.info.title == ""
    assert (await mgr.store.get_session(user["id"], run.sid))["title"] == ""
    assert not [e for e in run.log if e["type"] == "session_title"]


async def test_title_empty_reply_is_logged(env, caplog):
    fp = FakeProvider(reply("a"), titled(""))
    _, _, _, _, run = await env(fp, title="")
    await run.command(p.Prompt(text="hi"))
    await settle(run)
    assert run.info.title == "" and "empty title" in caplog.text


async def test_title_budget_refused_keeps_empty(env):
    fp = FakeProvider(reply("a"), titled("T"))
    _, mgr, user, _, run = await env(fp, title="")
    run.profile["price_in"] = 1e6  # first reply costs $10 > run limit -> title call refused
    await run.command(p.Prompt(text="hi"))
    await settle(run)
    assert fp.calls == 1 and run.info.title == ""


async def test_compact_command(env):
    g = Gated(["x"])
    _, _, _, _, run = await env(g)
    calls = list()

    async def fake_compact():
        calls.append(run.state)
        return True
    run.session.compact = fake_compact
    await run.command(p.Compact())
    await wait_for(lambda: run.task.done())
    assert calls == ["running"] and run.state == "idle"
    await run.command(p.Prompt(text="hi"))
    with pytest.raises(HTTPException) as e:
        await run.command(p.Compact())
    assert e.value.status_code == 409
    g.go.set()
    await wait_for(lambda: run.task.done() and run.state == "idle")


async def test_continue_command(env):
    fp = FakeProvider(AssistantMessage(stop_reason="error", error="overloaded", error_kind="fatal"), reply("ok"))
    _, _, _, _, run = await env(fp)
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: run.task.done())
    assert run.state == "error"
    await run.command(p.Continue())
    await wait_for(lambda: run.task.done())
    assert run.state == "idle" and fp.calls == 2
    assert [e["text"] for e in run.log if e["type"] == "assistant_message"][-1] == "ok"


async def test_continue_busy_409(env):
    g = Gated(["x"])
    _, _, _, _, run = await env(g)
    await run.command(p.Prompt(text="hi"))
    with pytest.raises(HTTPException) as e:
        await run.command(p.Continue())
    assert e.value.status_code == 409
    g.go.set()
    await wait_for(lambda: run.task.done())


async def test_plan_mode(env, tmp_path):
    fp = FakeProvider(bash("c1", "echo hi"), reply("planned"))
    _, mgr, user, _, run = await env(fp)
    assert run.subscribe(0)[0][-1]["plan_mode"] is False
    await run.command(p.SetPlanMode(enabled=True))
    assert [e["text"] for e in run.log if e["type"] == "notice"] == ["plan mode on"]
    assert run.subscribe(0)[0][-1]["plan_mode"] is True
    assert mgr.info(await mgr.store.get_session(user["id"], run.sid)).plan_mode is True
    await run.command(p.Prompt(text="do it"))
    await wait_for(lambda: run.task.done())
    tr = [e for e in run.log if e["type"] == "tool_result"]
    assert tr and tr[0]["is_error"] and "plan mode" in tr[0]["content"]
    assert "PLAN MODE" in fp.ctxs[0].system_prompt
    # survives a reload
    mgr.runs.clear()
    run2 = await mgr.get(user, run.sid)
    assert run2.subscribe(0)[0][-1]["plan_mode"] is True
    await run2.command(p.SetPlanMode(enabled=False))
    assert run2.subscribe(0)[0][-1]["plan_mode"] is False and run2.log[-1]["text"] == "plan mode off"
