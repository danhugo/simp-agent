import base64
import json
import urllib.parse

import httpx
from simp_agent.testing import FakeProvider

from simp_server.server import create_app, load_settings
from simp_server.store import SqliteStore


async def accounts_app(tmp_path, extra=""):
    (tmp_path / "settings.toml").write_text('allowed_emails = ["ann@gmail.com"]\nweb_url = "http://web/"\n' + extra +
                                            '[profiles.test]\napi = "fake"\nmodel = "m"\n')
    (tmp_path / ".env").write_text("GOOGLE_CLIENT_ID=cid\nGOOGLE_CLIENT_SECRET=csecret\n")
    app = create_app(load_settings(tmp_path), FakeProvider())
    mgr = app.state.mgr
    await mgr.store.open()
    return app, mgr


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")


async def google_signin(c, mgr, email):
    """Start -> fake Google -> callback; returns the callback response."""
    tok = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    mgr.conns.http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"access_token": "a", "id_token": f"h.{tok}.s"})))
    r = await c.get("/api/auth/google/start")
    assert r.status_code == 302
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    assert q["redirect_uri"] == ["http://localhost:8766/api/auth/google/callback"]
    return await c.get("/api/auth/google/callback", params={"code": "x", "state": q["state"][0]})


def token_of(r) -> str:
    assert r.status_code == 302 and r.headers["location"].startswith("http://web/#login=")
    return r.headers["location"].split("#login=")[1]


async def test_google_allowed_email_signs_in(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    try:
        async with client(app) as c:
            t = token_of(await google_signin(c, mgr, "Ann@Gmail.com"))
            h = {"Authorization": f"Bearer {t}"}
            assert (await c.get("/api/me", headers=h)).json() == {"name": "ann@gmail.com"}
            t2 = token_of(await google_signin(c, mgr, "ann@gmail.com"))  # same user, second device
            assert len(await mgr.store.list_users()) == 1
            assert (await c.post("/api/logout", headers=h)).status_code == 200
            assert (await c.get("/api/me", headers=h)).status_code == 401
            assert (await c.get("/api/me", headers={"Authorization": f"Bearer {t2}"})).status_code == 200
            await mgr.store.revoke("ann@gmail.com")
            assert (await google_signin(c, mgr, "ann@gmail.com")).status_code == 403
    finally:
        await mgr.store.close()


async def test_google_other_email_rejected(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    try:
        async with client(app) as c:
            r = await google_signin(c, mgr, "eve@gmail.com")
            assert r.status_code == 403 and "eve@gmail.com is not allowed" in r.text
            assert await mgr.store.list_users() == []
    finally:
        await mgr.store.close()


async def test_google_callback_needs_state_and_cookie(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    try:
        async with client(app) as c:
            assert (await c.get("/api/auth/google/callback", params={"code": "x", "state": "forged"})).status_code == 400
            assert (await c.get("/api/auth/google/callback", params={"error": "access_denied"})).status_code == 400
    finally:
        await mgr.store.close()


async def test_password_endpoints_gone(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    try:
        async with client(app) as c:
            for path in ("/api/login", "/api/signup"):
                assert (await c.post(path, json={"name": "ann", "password": "p"})).status_code in (404, 405)
            assert (await c.get("/api/signup-mode")).status_code in (404, 405)
    finally:
        await mgr.store.close()


async def test_static_token_revoke_rotate(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    s = mgr.store
    try:
        t = await s.add_user("ann")
        async with client(app) as c:
            assert (await c.get("/api/sessions", headers={"Authorization": f"Bearer {t}"})).status_code == 200
            t2 = await s.rotate_token("ann")
            assert (await c.get("/api/sessions", headers={"Authorization": f"Bearer {t}"})).status_code == 401
            await s.revoke("ann")
            assert (await c.get("/api/sessions", headers={"Authorization": f"Bearer {t2}"})).status_code == 401
            assert not await s.user_active((await s.list_users())[0]["id"])
    finally:
        await s.close()


async def test_stage2_revoked_user_stays_revoked_after_upgrade(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "simp.db")
    db.execute("CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT UNIQUE, token_sha256 TEXT UNIQUE)")
    db.execute("INSERT INTO users VALUES('1','alice','h1'), ('2','bob',NULL)")
    db.commit()
    db.close()
    s = SqliteStore({"data_dir": str(tmp_path)})
    await s.open()
    try:
        assert {u["name"]: u["active"] for u in await s.list_users()} == {"alice": 1, "bob": 0}
        assert await s.count_users() == 1
        assert await s.google_login("bob") is None  # revoked: no new token
    finally:
        await s.close()


async def test_me_returns_name(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    try:
        t = await mgr.store.add_user("ann")
        async with client(app) as c:
            assert (await c.get("/api/me")).status_code == 401
            r = await c.get("/api/me", headers={"Authorization": f"Bearer {t}"})
            assert r.status_code == 200 and r.json() == {"name": "ann"}
    finally:
        await mgr.store.close()


async def test_models_maps_profile_to_model(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    try:
        t = await mgr.store.add_user("ann")
        async with client(app) as c:
            assert (await c.get("/api/models")).status_code == 401
            r = await c.get("/api/models", headers={"Authorization": f"Bearer {t}"})
            assert r.status_code == 200 and r.json() == {"test": "m"}
    finally:
        await mgr.store.close()
