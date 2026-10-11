import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from simp_agent.testing import FakeProvider

from simp_server import protocol as p
from simp_server.server import LocalSandbox, create_app, load_settings

from .test_server import Gated, reply, wait_for

PROFILE = '[profiles.test]\napi = "fake"\nmodel = "m"\n'


async def make(tmp_path, stream_fn, extra=""):
    (tmp_path / "settings.toml").write_text(extra + PROFILE)
    app = create_app(load_settings(tmp_path), stream_fn)
    mgr = app.state.mgr
    await mgr.store.open()
    user = await mgr.store.user_by_token(await mgr.store.add_user("u"))
    closed = list()
    real_close = mgr.sandbox.close

    async def close(ref):
        closed.append(ref)
        await real_close(ref)
    mgr.sandbox.close = close
    return app, mgr, user, closed


async def test_local_sandbox_uses_workspaces_and_migrates(tmp_path):
    sb = LocalSandbox({"data_dir": str(tmp_path)})
    env = await sb.open("s1")
    assert Path(env.root) == (tmp_path / "workspaces" / "s1").resolve()
    old = tmp_path / "sandboxes" / "s2"
    old.mkdir(parents=True)
    (old / "a.txt").write_text("keep")
    env = await sb.open("s2")
    assert (Path(env.root) / "a.txt").read_text() == "keep" and not old.exists()


async def test_idle_run_evicted_and_reloaded(tmp_path):
    app, mgr, user, closed = await make(tmp_path, FakeProvider(reply("a")), "idle_minutes = 0\n")
    row = await mgr.store.add_session(user["id"], "test")
    run = await mgr.get(user, row["id"])
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: not run.busy and run.task.done())
    await run.env.write_bytes("f.txt", b"x")
    q = run.subscribe(0)[1]
    await mgr.evict_idle()
    assert row["id"] in mgr.runs  # an open stream keeps it
    run.subs.discard(q)
    await mgr.evict_idle()
    assert row["id"] not in mgr.runs and closed == [row["sandbox_ref"]]
    again = await mgr.get(user, row["id"])
    assert again is not run and again.log == run.log
    assert await again.env.read_bytes("f.txt") == b"x"
    await mgr.store.close()


async def test_busy_run_not_evicted(tmp_path):
    g = Gated(["x"])
    app, mgr, user, closed = await make(tmp_path, g, "idle_minutes = 0\n")
    row = await mgr.store.add_session(user["id"], "test")
    run = await mgr.get(user, row["id"])
    await run.command(p.Prompt(text="hi"))
    await mgr.evict_idle()
    assert row["id"] in mgr.runs and closed == []
    g.go.set()
    await wait_for(lambda: not run.busy and run.task.done())
    await mgr.store.close()


async def test_lifespan_evicts_periodically(tmp_path):
    (tmp_path / "settings.toml").write_text("idle_minutes = 0\nevict_every = 0.05\n" + PROFILE)
    app = create_app(load_settings(tmp_path), FakeProvider())
    mgr = app.state.mgr
    async with app.router.lifespan_context(app):
        user = await mgr.store.user_by_token(await mgr.store.add_user("u"))
        row = await mgr.store.add_session(user["id"], "test")
        await mgr.get(user, row["id"])
        await wait_for(lambda: not mgr.runs)


async def test_cap_evicts_lru_or_503(tmp_path):
    g = Gated(["x"])
    app, mgr, user, closed = await make(tmp_path, g, "max_open_sessions = 1\n")
    a, b = [await mgr.store.add_session(user["id"], "test") for _ in range(2)]
    ra = await mgr.get(user, a["id"])
    await mgr.get(user, b["id"])  # a is idle -> evicted to make room
    assert list(mgr.runs) == [b["id"]] and closed == [a["sandbox_ref"]]
    rb = mgr.runs[b["id"]]
    await rb.command(p.Prompt(text="hi"))
    with pytest.raises(HTTPException) as e:
        await mgr.get(user, a["id"])
    assert e.value.status_code == 503
    g.go.set()
    await wait_for(lambda: not rb.busy and rb.task.done())
    assert (await mgr.get(user, a["id"])) is not ra
    await mgr.store.close()
