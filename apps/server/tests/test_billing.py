import sys

import httpx
import pytest
from simp_agent.testing import FakeProvider

from simp_server import protocol as p
from simp_server import server
from simp_server.budget import OUT_OF_POINTS
from simp_server.sandboxes import Compute, SandboxLimit

from .test_budget import make, usage_reply
from .test_server import wait_for

ON = "[billing]\nenabled = true\npoints_per_usd = 10\n[budget]\nrun_usd = 100\nuser_day_usd = 100\n"


async def ask(run, text="hi"):
    await run.command(p.Prompt(text=text))
    await wait_for(lambda: not run.busy and run.task.done())


async def test_billing_off_does_not_block(tmp_path):
    fp = FakeProvider(usage_reply("a"))
    app, mgr, user, _, run = await make(tmp_path, fp, "[budget]\nrun_usd = 100\nuser_day_usd = 100\n")
    await ask(run)
    assert run.state == "idle" and fp.calls == 1
    await mgr.store.close()


async def test_billing_on_blocks_until_credit_and_spending_reduces(tmp_path):
    fp = FakeProvider(usage_reply("a"), usage_reply("b"))
    app, mgr, user, token, run = await make(tmp_path, fp, ON)
    await ask(run)
    assert run.state == "error" and fp.calls == 0
    assert any(OUT_OF_POINTS in str(e) for e in run.log)

    await mgr.store.add_credit(user["id"], 25, "trial")
    await ask(run, "again")
    assert run.state == "idle" and fp.calls == 1  # $1 -> 10 points
    c = Compute({"sandbox": {"price_vcpu_s": 0.01, "price_gib_s": 0.0}}, "e2b")
    c.db, c.billing = mgr.store, (True, 10.0)
    await c.record(user["id"], 50, 1, 1)  # $0.5 -> 5 points
    assert await mgr.store.credits(user["id"], 10) == {"granted": 25, "spent": 15, "balance": 10}
    await c.check(user["id"], 0)  # still positive: sandbox may start

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as cl:
        u = (await cl.get("/api/usage", headers={"Authorization": f"Bearer {token}"})).json()
    assert u["billing_enabled"] is True and u["points_balance"] == 10

    await mgr.store.add_credit(user["id"], -10, "fix")
    with pytest.raises(SandboxLimit, match="out of points"):
        await c.check(user["id"], 0)
    await mgr.store.close()


async def test_credit_cli(tmp_path, monkeypatch, capsys):  # main() calls asyncio.run: run it in a thread
    import asyncio
    (tmp_path / "settings.toml").write_text("[billing]\nenabled = true\npoints_per_usd = 1000\n")
    real = server.load_settings
    monkeypatch.setattr(server, "load_settings", lambda home=None: real(tmp_path))
    await server.with_store(lambda s: s.add_user("A@x.com"))
    await server.with_store(lambda s: s.add_user("b@x.com"))

    async def cli(*args):
        monkeypatch.setattr(sys, "argv", ["simp-server", "credit", *args])
        await asyncio.to_thread(server.main)
        return capsys.readouterr().out

    assert await cli("add", "--email", "a@x.com", "--points", "500", "--note", "trial") == "granted 500\tspent 0\tbalance 500\n"
    assert await cli("add", "--email", "a@x.com", "--points", "-100") == "granted 400\tspent 0\tbalance 400\n"
    assert await cli("show", "--email", "b@x.com") == "granted 0\tspent 0\tbalance 0\n"
    assert await cli("list") == "A@x.com\t400\nb@x.com\t0\n"
    with pytest.raises(SystemExit):
        await cli("show", "--email", "nobody@x.com")
