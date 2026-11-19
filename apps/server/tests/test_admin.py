import httpx
import pytest
from simp_agent.testing import FakeProvider

from simp_server import protocol as p
from simp_server.server import create_app, load_settings

from .test_budget import PROFILE, usage_reply
from .test_server import wait_for

ROUTES = [("get", "/api/admin/me"), ("get", "/api/admin/users"), ("get", "/api/admin/users/x"),
          ("post", "/api/admin/users/x/credit"), ("post", "/api/admin/users/x/revoke"),
          ("post", "/api/admin/users/x/unrevoke"), ("get", "/api/admin/system"), ("post", "/api/admin/system/pause"),
          ("post", "/api/admin/system/resume"), ("get", "/api/admin/audit"), ("get", "/api/admin/settings"),
          ("put", "/api/admin/settings/budget.run_usd"), ("get", "/api/admin/settings/history"),
          ("post", "/api/admin/settings/history/1/rollback")]


async def setup(tmp_path, admins="boss@example.com", fp=None):
    (tmp_path / "settings.toml").write_text('allowed_emails = ["boss@example.com", "joe@example.com"]\nallow_local_sandbox = true\n'
                                            "[budget]\nrun_usd = 100\nuser_day_usd = 100\n" + PROFILE)
    (tmp_path / ".env").write_text(f"ADMIN_EMAILS={admins}\n" if admins is not None else "")
    app = create_app(load_settings(tmp_path), fp or FakeProvider())
    mgr = app.state.mgr
    await mgr.store.open()
    toks = {}
    for e in ("boss@example.com", "joe@example.com"):
        toks[e] = await mgr.store.google_login(e)
    ids = {u["name"]: u["id"] for u in await mgr.store.list_users()}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
    return app, mgr, c, toks, ids


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


async def call(c, method, url, tok, body=None):
    kw = {"json": body if body is not None else {"reason": "r"}} if method in ("post", "put") else {}
    return await getattr(c, method)(url, headers=h(tok), **kw)


@pytest.mark.parametrize("admins", ["", None, "other@example.com"])
async def test_non_admin_403_everywhere(tmp_path, admins):
    app, mgr, c, toks, _ = await setup(tmp_path, admins)
    for tok in toks.values():
        for m, url in ROUTES:
            assert (await call(c, m, url, tok)).status_code == 403, (m, url)
    for m, url in ROUTES:
        assert (await call(c, m, url, "bad")).status_code == 401
    assert not (tmp_path / "PAUSED").exists()
    await mgr.store.close()


async def test_admin_users_credit_revoke_pause_audit(tmp_path):
    app, mgr, c, toks, ids = await setup(tmp_path)
    t, joe = toks["boss@example.com"], ids["joe@example.com"]
    assert (await call(c, "get", "/api/admin/me", t)).json() == {"admin": True}
    assert (await call(c, "get", "/api/admin/me", toks["joe@example.com"])).status_code == 403
    r = (await call(c, "get", "/api/admin/users?q=JOE", t)).json()
    assert r["total"] == 1 and r["users"][0]["email"] == "joe@example.com" and r["users"][0]["revoked"] is False

    url = f"/api/admin/users/{joe}/credit"
    assert (await call(c, "post", url, t, {"points": 50})).status_code == 422  # no reason
    assert (await call(c, "post", url, t, {"points": 50, "reason": ""})).status_code == 422
    assert (await call(c, "post", url, t, {"points": 200_000, "reason": "big"})).status_code == 400
    r = await call(c, "post", url, t, {"points": 200_000, "reason": "big", "confirm": True})
    assert r.json()["balance"] == 200_000
    r = await call(c, "post", url, t, {"points": -1000, "reason": "fix"})
    assert r.json()["balance"] == 199_000
    d = (await call(c, "get", f"/api/admin/users/{joe}", t)).json()
    assert [x["note"] for x in d["ledger"]] == ["fix", "big"] and d["points_balance"] == 199_000

    assert (await call(c, "post", f"/api/admin/users/{joe}/revoke", t, {})).status_code == 422
    assert (await call(c, "post", f"/api/admin/users/{ids['boss@example.com']}/revoke", t)).status_code == 400
    assert (await call(c, "post", f"/api/admin/users/{joe}/revoke", t)).status_code == 200
    assert (await c.get("/api/me", headers=h(toks["joe@example.com"]))).status_code == 401
    assert (await call(c, "post", f"/api/admin/users/{joe}/unrevoke", t)).status_code == 200
    assert await mgr.store.user_active(joe)

    assert (await call(c, "post", "/api/admin/system/pause", t, {})).status_code == 422
    assert (await call(c, "post", "/api/admin/system/pause", t)).json() == {"paused": True}
    assert mgr.paused() and (await call(c, "get", "/api/admin/system", t)).json()["paused"] is True
    assert (await call(c, "post", "/api/admin/system/resume", t)).json() == {"paused": False}

    log = (await call(c, "get", "/api/admin/audit", t)).json()
    assert [a["action"] for a in log] == ["resume", "pause", "unrevoke", "revoke", "credit", "credit"]
    assert log[-1]["actor"] == "boss@example.com" and log[-1]["target"] == "joe@example.com"
    assert log[-1]["detail"]["reason"] == "big"
    await mgr.store.close()


async def test_settings_validate_persist_take_effect_and_rollback(tmp_path):
    fp = FakeProvider(*[usage_reply(str(i)) for i in range(5)])  # every call costs $1
    app, mgr, c, toks, ids = await setup(tmp_path, fp=fp)
    t, joe = toks["boss@example.com"], ids["joe@example.com"]
    put = "/api/admin/settings/budget.user_day_usd"
    assert (await call(c, "put", "/api/admin/settings/plugins.store", t, {"value": "x", "reason": "r"})).status_code == 400
    assert (await call(c, "put", "/api/admin/settings/allowed_hosts", t, {"value": [], "reason": "r"})).status_code == 400
    assert (await call(c, "put", put, t, {"value": -1, "reason": "r"})).status_code == 400
    assert (await call(c, "put", put, t, {"value": "1", "reason": "r"})).status_code == 400
    assert (await call(c, "put", put, t, {"value": 1})).status_code == 422

    row = await mgr.store.add_session(joe, "test", "t")
    run = await mgr.get({"id": joe, "name": "joe@example.com"}, row["id"])
    await run.command(p.Prompt(text="a"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert run.state == "idle" and fp.calls == 1  # $1 spent today, limit 100

    assert (await call(c, "put", put, t, {"value": 0.5, "reason": "tighten"})).status_code == 200
    await run.command(p.Prompt(text="b"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert run.state == "error" and fp.calls == 1  # no restart: the new limit blocks the next run

    s = {x["key"]: x for x in (await call(c, "get", "/api/admin/settings", t)).json()}
    assert s["budget.user_day_usd"]["value"] == 0.5 and s["budget.user_day_usd"]["source"] == "db"
    assert s["budget.run_usd"]["source"] == "file" and "profiles.test.price_in" in s
    # never buckets/endpoints/mount scope; the storage quota is the one workspace key an admin may change
    assert not any(k.startswith(("plugins", "workspace")) and k != "workspace.quota_mb" or "ADMIN" in k for k in s)

    hist = (await call(c, "get", "/api/admin/settings/history?key=budget.user_day_usd", t)).json()
    assert len(hist) == 1 and hist[0]["old"] == 100 and hist[0]["new"] == 0.5 and hist[0]["reason"] == "tighten"
    rb = f"/api/admin/settings/history/{hist[0]['id']}/rollback"
    assert (await call(c, "post", rb, t, {})).status_code == 422
    assert (await call(c, "post", rb, t, {"reason": "undo"})).json()["value"] == 100
    assert mgr.limits.user_day_usd == 100

    # persisted: a fresh app over the same data dir loads the override
    await call(c, "put", "/api/admin/settings/billing.points_per_usd", t, {"value": 7, "reason": "r"})
    await mgr.store.close()
    app2 = create_app(load_settings(tmp_path), FakeProvider())
    async with app2.router.lifespan_context(app2):
        assert app2.state.mgr.settings["billing"]["points_per_usd"] == 7
        assert app2.state.mgr.limits.user_day_usd == 100


async def test_rate_limit(tmp_path, monkeypatch):
    from simp_server import admin
    monkeypatch.setitem(admin.RATE, "write", 2)
    app, mgr, c, toks, _ = await setup(tmp_path)
    t = toks["boss@example.com"]
    codes = [(await call(c, "post", "/api/admin/system/resume", t)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    await mgr.store.close()


async def test_admin_per_user_storage_quota(tmp_path):
    app, mgr, c, toks, ids = await setup(tmp_path)
    t, joe = toks["boss@example.com"], ids["joe@example.com"]
    assert (await call(c, "put", f"/api/admin/users/{joe}/quota", toks["joe@example.com"], {"quota_mb": 1, "reason": "r"})).status_code == 403
    w = (await call(c, "get", f"/api/admin/users/{joe}", t)).json()["workspace"]
    assert w == {"used": 0, "quota": 10240 * 2**20, "state": "ok", "quota_mb_override": None}  # default 10 GB
    assert (await call(c, "put", f"/api/admin/users/{joe}/quota", t, {"quota_mb": 20480})).status_code == 422  # reason
    assert (await call(c, "put", f"/api/admin/users/{joe}/quota", t, {"quota_mb": -1, "reason": "r"})).status_code == 422
    assert (await call(c, "put", f"/api/admin/users/{joe}/quota", t, {"quota_mb": 20480, "reason": "needs room"})).status_code == 200
    w = (await call(c, "get", f"/api/admin/users/{joe}", t)).json()["workspace"]
    assert w["quota"] == 20480 * 2**20 and w["quota_mb_override"] == 20480
    assert (await call(c, "put", f"/api/admin/users/{joe}/quota", t, {"quota_mb": None, "reason": "back"})).status_code == 200
    assert (await call(c, "get", f"/api/admin/users/{joe}", t)).json()["workspace"]["quota_mb_override"] is None
    audit = (await call(c, "get", "/api/admin/audit", t)).json()
    assert [a["detail"]["after_mb"] for a in audit if a["action"] == "quota"] == [None, 20480]
    await mgr.store.close()
