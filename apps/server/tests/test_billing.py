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
    await server.with_store(lambda s: s.add_user("A@x.com"))  # stored lowercase
    await server.with_store(lambda s: s.add_user("b@x.com"))

    async def cli(*args):
        monkeypatch.setattr(sys, "argv", ["simp-server", "credit", *args])
        await asyncio.to_thread(server.main)
        return capsys.readouterr().out

    assert await cli("add", "--email", "A@X.com", "--points", "500", "--note", "trial") == "granted 500\tspent 0\tbalance 500\n"
    assert await cli("add", "--email", "a@x.com", "--points", "-100") == "granted 400\tspent 0\tbalance 400\n"
    assert await cli("show", "--email", "b@x.com") == "granted 0\tspent 0\tbalance 0\n"
    assert await cli("list") == "a@x.com\t400\nb@x.com\t0\n"
    with pytest.raises(SystemExit):
        await cli("show", "--email", "nobody@x.com")


async def test_no_grant_usage_goes_negative_and_rounds_up(tmp_path):
    fp = FakeProvider(usage_reply("a"))
    app, mgr, user, _, run = await make(tmp_path, fp, ON)
    uid = user["id"]
    await mgr.store.add_usage(uid, "", "m", 1, 0, cost=0.0001)  # $0.0001 x 10 = 0.001 point -> 1 point
    assert await mgr.store.credits(uid, 10) == {"granted": 0, "spent": 1, "balance": -1}
    await mgr.store.add_usage(uid, "", "m", 1, 0, cost=0.0999)  # total $0.1 x 10 = exactly 1 point, no float noise
    assert (await mgr.store.credits(uid, 10))["spent"] == 1
    await ask(run)
    assert run.state == "error" and fp.calls == 0
    await mgr.store.close()


async def test_persona_generation_blocked_at_zero_points(tmp_path):
    fp = FakeProvider(usage_reply("return null;"))
    app, mgr, user, token, run = await make(tmp_path, fp, ON)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        r = await c.post("/api/persona/generate", headers={"Authorization": f"Bearer {token}"},
                         json={"description": "a wizard", "profile": "test", "slot": "hat"})
    assert fp.calls == 0 and "out of points" in r.text, r.text
    await mgr.store.close()


async def test_email_names_lowercase_and_migrated(tmp_path):
    import aiosqlite
    from simp_server.store import SqliteStore
    s = SqliteStore({"data_dir": str(tmp_path)})
    await s.open()
    await s.add_user("Mixed@X.com")
    await s.add_user("plain")
    assert [u["name"] for u in await s.list_users()] == ["mixed@x.com", "plain"]
    assert await s.revoke("MIXED@x.com")
    await s.add_user("dup@x.com")
    async with aiosqlite.connect(s.path) as db:  # rows from before lowercase names
        await db.execute("INSERT INTO users(id, name) VALUES('o1', 'Old@X.com'), ('o2', 'Dup@x.com')")
        await db.commit()
    await s.close()
    await s.open()
    assert sorted(u["name"] for u in await s.list_users()) == ["Dup@x.com", "dup@x.com", "mixed@x.com", "old@x.com", "plain"]
    await s.close()
