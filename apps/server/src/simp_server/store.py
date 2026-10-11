"""SQLite store (aiosqlite). Every row has user_id; every read is scoped by it."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE, token_sha256 TEXT UNIQUE, password TEXT,
    disabled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS tokens(token_sha256 TEXT PRIMARY KEY, user_id TEXT, created REAL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, user_id TEXT, title TEXT, profile TEXT, sandbox_ref TEXT,
    created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS entries(session_id TEXT, user_id TEXT, seq INTEGER, type TEXT, json TEXT,
    PRIMARY KEY(session_id, seq));
CREATE TABLE IF NOT EXISTS usage(user_id TEXT, session_id TEXT, model TEXT, input INTEGER, output INTEGER, at REAL,
    cost REAL DEFAULT 0);
"""


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${_scrypt(password, salt).hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        _scrypt(password, b"0" * 16)  # same time whether or not the user exists
        return False
    _, salt, h = stored.split("$")
    return hmac.compare_digest(_scrypt(password, bytes.fromhex(salt)), bytes.fromhex(h))


class SqliteStore:
    def __init__(self, settings: dict):
        self.path = Path(settings["data_dir"]) / "simp.db"
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(SCHEMA)
        cols = [r["name"] for r in await self._all("PRAGMA table_info(usage)")]
        if "cost" not in cols:  # db from Stage 1
            await self._do("ALTER TABLE usage ADD COLUMN cost REAL DEFAULT 0")
        cols = [r["name"] for r in await self._all("PRAGMA table_info(users)")]
        if "password" not in cols:  # db from Stage 2
            await self._do("ALTER TABLE users ADD COLUMN password TEXT")
            await self._do("ALTER TABLE users ADD COLUMN disabled INTEGER DEFAULT 0")

    async def close(self) -> None:
        await self.db.close()

    async def _all(self, sql: str, *args) -> list[dict]:
        return [dict(r) for r in await self.db.execute_fetchall(sql, args)]

    async def _do(self, sql: str, *args) -> None:
        await self.db.execute(sql, args)
        await self.db.commit()

    # users: a static token (seed/rotate, users.token_sha256) and/or a password whose logins get per-device tokens
    async def add_user(self, name: str, password: str | None = None, token: bool = True) -> str | None:
        """Returns the static token (shown once); only its sha256 is stored. Raises sqlite3.IntegrityError on a taken name."""
        t = secrets.token_urlsafe(32) if token else None
        await self._do("INSERT INTO users(id, name, token_sha256, password) VALUES(?,?,?,?)", uuid.uuid4().hex, name,
                       t and sha(t), password and hash_password(password))
        return t

    async def user_by_token(self, token: str) -> dict | None:
        rows = await self._all("SELECT id, name FROM users WHERE disabled=0 AND (token_sha256=? OR id IN "
                               "(SELECT user_id FROM tokens WHERE token_sha256=?))", sha(token), sha(token))
        return rows[0] if rows else None

    async def set_password(self, name: str, password: str) -> bool:
        cur = await self.db.execute("UPDATE users SET password=? WHERE name=?", (hash_password(password), name))
        await self.db.commit()
        return cur.rowcount > 0

    async def login(self, name: str, password: str) -> str | None:
        rows = await self._all("SELECT id, password FROM users WHERE name=? AND disabled=0", name)
        if not check_password(password, rows[0]["password"] if rows else None):
            return None
        token = secrets.token_urlsafe(32)
        await self._do("INSERT INTO tokens VALUES(?,?,?)", sha(token), rows[0]["id"], time.time())
        return token

    async def logout(self, token: str) -> None:
        await self._do("DELETE FROM tokens WHERE token_sha256=?", sha(token))

    async def list_users(self) -> list[dict]:
        return await self._all("SELECT id, name, NOT disabled AS active FROM users ORDER BY name")

    async def count_users(self) -> int:  # active users only: a revoked one cannot log in
        return sum(1 for u in await self.list_users() if u["active"])

    async def user_active(self, user_id: str) -> bool:
        return bool(await self._all("SELECT 1 FROM users WHERE id=? AND disabled=0", user_id))

    async def _drop_tokens(self, name: str) -> None:
        await self.db.execute("DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE name=?)", (name,))

    async def rotate_token(self, name: str) -> str | None:  # also re-enables a revoked user
        token = secrets.token_urlsafe(32)
        await self._drop_tokens(name)
        cur = await self.db.execute("UPDATE users SET token_sha256=?, disabled=0 WHERE name=?", (sha(token), name))
        await self.db.commit()
        return token if cur.rowcount else None

    async def revoke(self, name: str) -> bool:
        await self._drop_tokens(name)
        cur = await self.db.execute("UPDATE users SET token_sha256=NULL, disabled=1 WHERE name=? AND disabled=0",
                                    (name,))
        await self.db.commit()
        return cur.rowcount > 0

    # sessions
    async def add_session(self, user_id: str, profile: str, title: str = "") -> dict:
        sid, now = uuid.uuid4().hex[:12], time.time()
        await self._do("INSERT INTO sessions VALUES(?,?,?,?,?,?,?)", sid, user_id, title, profile, sid, now, now)
        return (await self.get_session(user_id, sid))

    async def get_session(self, user_id: str, sid: str) -> dict | None:
        rows = await self._all("SELECT * FROM sessions WHERE id=? AND user_id=?", sid, user_id)
        return rows[0] if rows else None

    async def list_sessions(self, user_id: str) -> list[dict]:
        return await self._all("SELECT * FROM sessions WHERE user_id=? ORDER BY updated DESC", user_id)

    async def delete_session(self, user_id: str, sid: str) -> bool:
        cur = await self.db.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (sid, user_id))
        if cur.rowcount:
            await self.db.execute("DELETE FROM entries WHERE session_id=? AND user_id=?", (sid, user_id))
        await self.db.commit()
        return cur.rowcount > 0

    # entries: protocol durable events (type = event type) and core messages (type = "msg"), one seq counter
    async def add_entry(self, user_id: str, sid: str, seq: int, type: str, data: dict) -> None:
        await self.db.execute("INSERT INTO entries VALUES(?,?,?,?,?)", (sid, user_id, seq, type, json.dumps(data)))
        await self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (time.time(), sid))
        await self.db.commit()

    async def entries(self, user_id: str, sid: str) -> list[dict]:
        rows = await self._all("SELECT seq, type, json FROM entries WHERE session_id=? AND user_id=? ORDER BY seq",
                               sid, user_id)
        return [{"seq": r["seq"], "type": r["type"], "data": json.loads(r["json"])} for r in rows]

    # usage: cost in USD, computed by the server from profile prices
    async def add_usage(self, user_id: str, sid: str, model: str, input: int, output: int, cost: float = 0.0) -> None:
        await self._do("INSERT INTO usage(user_id, session_id, model, input, output, at, cost) VALUES(?,?,?,?,?,?,?)",
                       user_id, sid, model, input, output, time.time(), cost)

    async def spent(self, user_id: str, since: float, session_id: str | None = None) -> float:
        sql, args = "SELECT COALESCE(SUM(cost), 0) AS c FROM usage WHERE user_id=? AND at>=?", [user_id, since]
        if session_id:
            sql, args = sql + " AND session_id=?", args + [session_id]
        return (await self._all(sql, *args))[0]["c"]

    async def usage(self, user_id: str) -> list[dict]:
        return await self._all("SELECT * FROM usage WHERE user_id=?", user_id)
