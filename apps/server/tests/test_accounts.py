import httpx
from simp_agent.testing import FakeProvider

from simp_server.server import create_app, load_settings
from simp_server.store import SqliteStore


async def accounts_app(tmp_path, extra=""):
    (tmp_path / "settings.toml").write_text(extra + '[profiles.test]\napi = "fake"\nmodel = "m"\n')
    app = create_app(load_settings(tmp_path), FakeProvider())
    mgr = app.state.mgr
    await mgr.store.open()
    return app, mgr


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")


async def test_signup_gated_by_code(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    try:
        async with client(app) as c:
            r = await c.post("/api/signup", json={"name": "ann", "password": "password1", "code": "x"})
            assert r.status_code == 403
    finally:
        await mgr.store.close()
    app, mgr = await accounts_app(tmp_path, 'signup_code = "sesame"\n')
    try:
        async with client(app) as c:
            body = {"name": "ann", "password": "password1", "code": "nope"}
            assert (await c.post("/api/signup", json=body)).status_code == 403
            assert (await c.post("/api/signup", json={**body, "code": "sesame", "password": "short"})).status_code == 400
            assert (await c.post("/api/signup", json={**body, "code": "sesame", "name": "Bad Name"})).status_code == 400
            r = await c.post("/api/signup", json={**body, "code": "sesame"})
            assert r.status_code == 200
            h = {"Authorization": f"Bearer {r.json()['token']}"}
            assert (await c.get("/api/sessions", headers=h)).status_code == 200
            assert (await c.post("/api/signup", json={**body, "code": "sesame"})).status_code == 409
    finally:
        await mgr.store.close()


async def test_signup_refused_for_local_sandbox_multi_user(tmp_path):
    app, mgr = await accounts_app(tmp_path, 'signup_code = "c"\n')
    try:
        await mgr.store.add_user("owner")
        async with client(app) as c:
            r = await c.post("/api/signup", json={"name": "ann", "password": "password1", "code": "c"})
            assert r.status_code == 409 and "LocalSandbox" in r.json()["detail"]
        assert await mgr.store.count_users() == 1
    finally:
        await mgr.store.close()


async def test_login_logout_revoke_rotate(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    s = mgr.store
    try:
        await s.add_user("ann", password="password1")
        async with client(app) as c:
            assert (await c.post("/api/login", json={"name": "ann", "password": "wrong-pass"})).status_code == 401
            bad = await c.post("/api/login", json={"name": "bob", "password": "password1"})
            assert bad.status_code == 401
            ok = [(await c.post("/api/login", json={"name": "ann", "password": "password1"})).json()["token"]
                  for _ in range(3)]
            h = [{"Authorization": f"Bearer {t}"} for t in ok]
            for x in h:
                assert (await c.get("/api/sessions", headers=x)).status_code == 200
            assert (await c.post("/api/logout", headers=h[0])).status_code == 200
            assert (await c.get("/api/sessions", headers=h[0])).status_code == 401
            assert (await c.get("/api/sessions", headers=h[1])).status_code == 200
            await s.rotate_token("ann")
            assert (await c.get("/api/sessions", headers=h[1])).status_code == 401
            t = (await c.post("/api/login", json={"name": "ann", "password": "password1"})).json()["token"]
            await s.revoke("ann")
            assert (await c.get("/api/sessions", headers={"Authorization": f"Bearer {t}"})).status_code == 401
            assert (await c.post("/api/login", json={"name": "ann", "password": "password1"})).status_code == 401
            assert not await s.user_active((await s.list_users())[0]["id"])
    finally:
        await s.close()


async def test_set_password_and_hash_format(tmp_path):
    app, mgr = await accounts_app(tmp_path)
    s = mgr.store
    try:
        await s.add_user("ann")
        assert await s.login("ann", "password1") is None
        assert await s.set_password("ann", "password1") and not await s.set_password("nobody", "password1")
        stored = (await s._all("SELECT password FROM users"))[0]["password"]
        assert stored.startswith("scrypt$") and "password1" not in stored
        assert await s.user_by_token(await s.login("ann", "password1"))
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
        await s.set_password("bob", "password123")
        assert await s.login("bob", "password123") is None
    finally:
        await s.close()


async def test_password_length_capped(tmp_path):
    app, mgr = await accounts_app(tmp_path, 'signup_code = "c"\n')
    async with client(app) as c:
        r = await c.post("/api/signup", json={"name": "big", "password": "x" * 5000, "code": "c"})
        assert r.status_code in (400, 422)
        r = await c.post("/api/login", json={"name": "big", "password": "x" * 5000})
        assert r.status_code in (401, 422)
    await mgr.store.close()
