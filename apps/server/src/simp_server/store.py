"""SQLite store (aiosqlite). Every row has user_id; every read is scoped by it."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE, token_sha256 TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, user_id TEXT, title TEXT, profile TEXT, sandbox_ref TEXT,
    created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS entries(session_id TEXT, user_id TEXT, seq INTEGER, type TEXT, json TEXT,
    PRIMARY KEY(session_id, seq));
CREATE TABLE IF NOT EXISTS usage(user_id TEXT, session_id TEXT, model TEXT, input INTEGER, output INTEGER, at REAL);
"""


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SqliteStore:
    def __init__(self, settings: dict):
        self.path = Path(settings["data_dir"]) / "simp.db"
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)

    async def close(self) -> None:
        await self.db.close()

    async def _all(self, sql: str, *args) -> list[dict]:
        return [dict(r) for r in await self.db.execute_fetchall(sql, args)]

    async def _do(self, sql: str, *args) -> None:
        await self.db.execute(sql, args)
        await self.db.commit()

    # users
    async def add_user(self, name: str) -> str:
        """Returns the token (shown once); only its sha256 is stored."""
        token = secrets.token_urlsafe(32)
        await self._do("INSERT INTO users VALUES(?,?,?)", uuid.uuid4().hex, name, sha(token))
        return token

    async def user_by_token(self, token: str) -> dict | None:
        rows = await self._all("SELECT id, name FROM users WHERE token_sha256=?", sha(token))
        return rows[0] if rows else None

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

    # entries: protocol durable events (type = event type) and core messages (type = "msg"), one seq counter
    async def add_entry(self, user_id: str, sid: str, seq: int, type: str, data: dict) -> None:
        await self.db.execute("INSERT INTO entries VALUES(?,?,?,?,?)", (sid, user_id, seq, type, json.dumps(data)))
        await self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (time.time(), sid))
        await self.db.commit()

    async def entries(self, user_id: str, sid: str) -> list[dict]:
        rows = await self._all("SELECT seq, type, json FROM entries WHERE session_id=? AND user_id=? ORDER BY seq",
                               sid, user_id)
        return [{"seq": r["seq"], "type": r["type"], "data": json.loads(r["json"])} for r in rows]

    # usage (recorded only, no budget yet)
    async def add_usage(self, user_id: str, sid: str, model: str, input: int, output: int) -> None:
        await self._do("INSERT INTO usage VALUES(?,?,?,?,?,?)", user_id, sid, model, input, output, time.time())

    async def usage(self, user_id: str) -> list[dict]:
        return await self._all("SELECT * FROM usage WHERE user_id=?", user_id)
