import asyncio
import time
from datetime import datetime

from simp_agent.ai import AssistantMessage, TextContent, ToolCall
from simp_agent.testing import FakeProvider

from simp_server import budget
from simp_server import protocol as p
from simp_server.server import create_app, load_settings

from .test_server import bash, reply, wait_for

PROFILE = '[profiles.test]\napi = "fake"\nmodel = "m"\nprice_in = 1000000\nprice_out = 0\n'  # $1 per input token


def test_cost_and_day_start():
    assert budget.cost({"price_in": 3, "price_out": 15}, {"input": 1_000_000, "output": 100_000}) == 4.5
    assert budget.cost({}, {"input": 10, "output": 10}) == 0
    d = datetime.fromtimestamp(budget.day_start())
    assert (d.hour, d.minute, d.second) == (0, 0, 0) and budget.day_start() <= time.time()


async def make(tmp_path, stream_fn, extra=""):
    (tmp_path / "settings.toml").write_text(extra + PROFILE)
    app = create_app(load_settings(tmp_path), stream_fn)
    mgr = app.state.mgr
    await mgr.store.open()
    token = await mgr.store.add_user("u")
    user = await mgr.store.user_by_token(token)
    row = await mgr.store.add_session(user["id"], "test")
    return app, mgr, user, token, await mgr.get(user, row["id"])


def usage_reply(text, calls=(), inp=1):
    return AssistantMessage([TextContent(text), *calls], stop_reason="tool_use" if calls else "stop",
                            usage={"input": inp, "output": 0})


async def test_run_budget_stops_tool_loop(tmp_path):
    # price_in = $1 per input token and each reply reports 1 input token -> every LLM call costs $1
    fp = FakeProvider(*[usage_reply("", [ToolCall(f"c{i}", "bash", {"command": "true"})]) for i in range(5)])
    app, mgr, user, _, run = await make(tmp_path, fp, "[budget]\nrun_usd = 1.5\nuser_day_usd = 100\n")
    await run.command(p.Prompt(text="go"))
    while run.busy:  # allow every bash call
        if run.pending and not run.answer.done():
            run.answer.set_result("allow")
        await asyncio.sleep(0.01)
    assert fp.calls == 2  # $1 + $1 > $1.5 -> third call refused before reaching the provider
    assert run.state == "error"
    assert any(e["type"] == "notice" and "budget" in e["text"] for e in run.log) or \
        any(e["type"] == "assistant_message" and e.get("error") and "budget" in e["error"] for e in run.log)
    assert await mgr.store.spent(user["id"], 0) == 2
    await mgr.store.close()


async def test_day_budget_and_pause(tmp_path):
    fp = FakeProvider(usage_reply("a"), usage_reply("b"), usage_reply("c"))
    app, mgr, user, token, run = await make(tmp_path, fp, "[budget]\nrun_usd = 100\nuser_day_usd = 1\n")
    await run.command(p.Prompt(text="one"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert run.state == "idle"  # spent $1, limit is reached only after this call
    await run.command(p.Prompt(text="two"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert run.state == "error" and fp.calls == 1

    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        u = (await c.get("/api/usage", headers={"Authorization": f"Bearer {token}"})).json()
        assert u == {"today_usd": 1.0, "day_limit_usd": 1.0, "paused": False}
        (tmp_path / "PAUSED").touch()
        u = (await c.get("/api/usage", headers={"Authorization": f"Bearer {token}"})).json()
        assert u["paused"] is True
    await mgr.store.close()


async def test_pause_refuses_llm_calls(tmp_path):
    fp = FakeProvider(usage_reply("a"))
    app, mgr, user, _, run = await make(tmp_path, fp, "[budget]\nrun_usd = 100\nuser_day_usd = 100\n")
    (tmp_path / "PAUSED").touch()
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert fp.calls == 0 and run.state == "error"
    await mgr.store.close()


async def test_run_budget_spans_follow_ups(tmp_path):
    fp = FakeProvider(*[usage_reply(f"r{i}") for i in range(5)])
    app, mgr, user, _, run = await make(tmp_path, fp, "[budget]\nrun_usd = 1.5\nuser_day_usd = 100\n")
    orig, nxt = run.session.prompt, {"go": "f1", "f1": "f2"}

    async def prompt(text):  # each follow-up arrives after the loop decided to stop -> _turn starts it
        await orig(text)
        if text in nxt:
            run.session.follow_up(nxt[text])
    run.session.prompt = prompt
    await run.command(p.Prompt(text="go"))
    await wait_for(lambda: [e["text"] for e in run.log if e["type"] == "user_message"] == ["go", "f1", "f2"]
                   and not run.busy and run.task.done())
    assert fp.calls == 2 and run.state == "error"
    await mgr.store.close()
