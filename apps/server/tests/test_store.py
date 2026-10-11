import sqlite3
import time

from simp_server.store import SqliteStore


async def opened(tmp_path):
    s = SqliteStore({"data_dir": str(tmp_path)})
    await s.open()
    return s


async def test_wal_and_spent(tmp_path):
    s = await opened(tmp_path)
    try:
        assert (await s._all("PRAGMA journal_mode"))[0]["journal_mode"] == "wal"
        await s.add_user("a")
        uid = (await s.list_users())[0]["id"]
        t0 = time.time()
        await s.add_usage(uid, "s1", "m", 10, 5, cost=0.25)
        await s.add_usage(uid, "s2", "m", 10, 5, cost=0.5)
        assert await s.spent(uid, t0 - 1) == 0.75
        assert await s.spent(uid, t0 - 1, session_id="s1") == 0.25
        assert await s.spent(uid, time.time() + 1) == 0
    finally:
        await s.close()


async def test_opens_stage1_db(tmp_path):
    db = sqlite3.connect(tmp_path / "simp.db")
    db.execute("CREATE TABLE usage(user_id TEXT, session_id TEXT, model TEXT, input INTEGER, output INTEGER, at REAL)")
    db.execute("INSERT INTO usage VALUES('u','s','m',1,1,0)")
    db.commit()
    db.close()
    s = await opened(tmp_path)
    try:
        assert await s.spent("u", -1) == 0  # old rows cost 0
        await s.add_usage("u", "s", "m", 1, 1, cost=1.0)
        assert await s.spent("u", -1) == 1.0
    finally:
        await s.close()


async def test_revoke_rotate_delete(tmp_path):
    s = await opened(tmp_path)
    try:
        old = await s.add_user("a")
        new = await s.rotate_token("a")
        assert new and new != old
        assert await s.user_by_token(old) is None and (await s.user_by_token(new))["name"] == "a"
        assert await s.rotate_token("nobody") is None
        assert await s.revoke("a") and await s.user_by_token(new) is None
        assert not await s.revoke("a")
        assert await s.count_users() == 0  # revoked: still listed (rows kept) but not counted as a user who can log in
        assert [u["name"] for u in await s.list_users()] == ["a"]

        await s.add_user("b")
        uid = next(u["id"] for u in await s.list_users() if u["name"] == "b")
        row = await s.add_session(uid, "p")
        await s.add_entry(uid, row["id"], 1, "notice", {"x": 1})
        await s.add_usage(uid, row["id"], "m", 1, 1, cost=0.1)
        assert not await s.delete_session("someone-else", row["id"])
        assert await s.delete_session(uid, row["id"])
        assert await s.get_session(uid, row["id"]) is None and await s.entries(uid, row["id"]) == []
        assert await s.spent(uid, -1) == 0.1  # money already spent stays counted for the day
    finally:
        await s.close()


async def test_opens_stage2_users_table(tmp_path):
    db = sqlite3.connect(tmp_path / "simp.db")
    db.execute("CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT UNIQUE, token_sha256 TEXT UNIQUE)")
    db.execute("INSERT INTO users VALUES('u','old','x')")
    db.commit()
    db.close()
    s = await opened(tmp_path)
    try:
        assert await s.count_users() == 1 and await s.set_password("old", "password1")
        assert await s.login("old", "password1")
    finally:
        await s.close()
