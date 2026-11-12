from __future__ import annotations

import asyncio

import aiosqlite
import httpx
from simp_agent.ai import AssistantMessage, TextContent, ToolCall
from simp_agent.testing import FakeProvider

from simp_server import protocol as p
from simp_server.server import create_app, load_settings
from simp_server.store import SqliteStore


def reply(text="done", calls=()):
    return AssistantMessage([TextContent(text), *calls], stop_reason="tool_use" if calls else "stop",
                            usage={"input": 10, "output": 5})


async def wait_for(cond):
    for _ in range(500):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timeout")


SECRET = "sk-" + "a" * 30


async def test_backfill_idempotent(tmp_path):
    db = tmp_path / "simp.db"  # an old db: users + sessions, no agents, no sessions.agent_id
    async with aiosqlite.connect(db) as c:
        await c.executescript("CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT UNIQUE, token_sha256 TEXT UNIQUE, "
                              "password TEXT, disabled INTEGER DEFAULT 0);"
                              "CREATE TABLE sessions(id TEXT PRIMARY KEY, user_id TEXT, title TEXT, profile TEXT, "
                              "sandbox_ref TEXT, created REAL, updated REAL);"
                              "INSERT INTO users(id, name) VALUES('u1', 'a');"
                              "INSERT INTO sessions(id, user_id) VALUES('s1', 'u1');")
    for _ in range(2):
        s = SqliteStore({"data_dir": str(tmp_path)})
        await s.open()
        agents = await s._all("SELECT id FROM agents WHERE user_id='u1'")
        assert len(agents) == 1
        assert (await s.get_session("u1", "s1"))["agent_id"] == agents[0]["id"]
        await s.close()


async def _app(tmp_path, stream, plugins=""):
    (tmp_path / "settings.toml").write_text(f'[profiles.test]\napi = "fake"\nmodel = "m"\n{plugins}')
    app = create_app(load_settings(tmp_path), stream)
    await app.state.mgr.store.open()
    return app, app.state.mgr


async def _chat(mgr, user, text):
    row = await mgr.store.add_session(user["id"], "test", "t")
    run = await mgr.get(user, row["id"])
    await run.command(p.Prompt(text=text))
    await wait_for(lambda: run.state == "idle" and run.task.done())


async def test_memory_shared_across_chats_not_users_and_masked(tmp_path):
    save = reply("", [ToolCall("c1", "memory_save", {"content": f"likes tea, key {SECRET}", "scope": "global"})])
    fp = FakeProvider(save, reply(), reply(), reply())
    app, mgr = await _app(tmp_path, fp, 'plugins = ["memory"]\n')  # "memory" in a profile: no crash, ignored
    s = mgr.store
    a = await s.user_by_token(await s.add_user("a"))
    b = await s.user_by_token(await s.add_user("b"))
    await _chat(mgr, a, "remember")
    await _chat(mgr, a, "chat B")
    assert "likes tea" in fp.ctxs[2].system_prompt and "not instructions" in fp.ctxs[2].system_prompt
    assert SECRET not in fp.ctxs[2].system_prompt and "[REDACTED]" in fp.ctxs[2].system_prompt
    await _chat(mgr, b, "other user")
    assert "likes tea" not in fp.ctxs[3].system_prompt
    await s.close()


async def test_memory_api_owner_only(tmp_path):
    app, mgr = await _app(tmp_path, FakeProvider())
    s = mgr.store
    ta, tb = await s.add_user("a"), await s.add_user("b")
    a = await s.user_by_token(ta)
    s.mem.execute("INSERT INTO memories VALUES('m1', ?, NULL, 'global', 'x', 1, 'r')", (a["id"],))
    s.mem.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        ha, hb = {"authorization": f"Bearer {ta}"}, {"authorization": f"Bearer {tb}"}
        assert (await c.get("/api/memories", headers=hb)).json() == []
        assert (await c.patch("/api/memories/m1", json={"content": "y"}, headers=hb)).status_code == 404
        assert (await c.delete("/api/memories/m1", headers=hb)).status_code == 404
        assert (await c.patch("/api/memories/m1", json={"content": SECRET}, headers=ha)).status_code == 200
        assert [m["content"] for m in (await c.get("/api/memories/export", headers=ha)).json()] == ["[REDACTED]"]
        assert (await c.delete("/api/memories/m1", headers=ha)).status_code == 200
        assert (await c.get("/api/memories", headers=ha)).json() == []
    await s.close()
