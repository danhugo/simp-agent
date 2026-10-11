# Stage 2 (self-hosted, one machine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Stage 1 local server safe to hand to a few users on this machine: Docker isolation by default, money budgets, clean state after restart, token/session admin, shared model wiring, logs and backups.

**Architecture:** All changes live in `apps/server` (plus one small move into `packages/simp_agent` for model wiring and a header widget in `apps/web`). Budgets wrap the `stream_fn` per run and answer with an `error_kind="budget"` assistant error, so the core loop stops without retry (already `NON_RETRYABLE`). Restart safety is derived from the durable log when a run is loaded; no new table.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, pytest + pytest-asyncio, React + Vite, Playwright.

**Spec:** `docs/ROADMAP.md` → "Stage 2 – self-hosted on one machine".

## Global Constraints

- Budgets: `user_day_usd = 2.0`, `run_usd = 0.5` (defaults, overridable in `settings.toml` `[budget]`).
- Cost = `input * price_in / 1e6 + output * price_out / 1e6`; prices per profile in USD per 1M tokens; a profile with no prices costs 0 (budget never trips) and the server logs a warning at startup.
- LLM is an OpenAI-compatible API with a key from `<data_dir>/.env` (unchanged mechanism, `api_key_env`).
- No Postgres, no `org_id`, no OIDC, no rate limit, no TLS, no E2B in this stage.
- SQLite stays; WAL on.
- Day boundary for budgets is local midnight on the server machine.
- Commit after every task; message style `Stage 2: <what>`; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run tests with `uv run pytest apps/server -q` (and the full `uv run pytest -q` at the end of each task).

## Review Focus

- A run that is already over budget mid-loop (tool call loop) must stop at the next LLM call, not after the loop ends → test in Task 3 (`test_run_budget_stops_tool_loop`).
- A DB created by Stage 1 (no `cost` column, journal mode delete) must open and keep working → test in Task 1 (`test_opens_stage1_db`).
- Server restart while a tool approval was pending: the UI must not show a live Allow/Deny card for a dead run → test in Task 4 (`test_restart_with_pending_approval`).
- Revoked token used by an open SSE tab: new requests get 401 → test in Task 2 (`test_revoke_rotate`).
- Deleting a session that is running: the run is aborted and its sandbox closed, then 404 afterwards → test in Task 2 (`test_delete_running_session`).

---

### Task 1: Store foundations (WAL, cost column, user admin, delete, spend query)

**Files:**
- Modify: `apps/server/src/simp_server/store.py`
- Create: `apps/server/tests/test_store.py`

**Interfaces:**
- Produces (all `async` on `SqliteStore`):
  - `add_usage(user_id, sid, model, input, output, cost: float = 0.0) -> None`
  - `spent(user_id: str, since: float, session_id: str | None = None) -> float` (sum of cost)
  - `count_users() -> int`, `list_users() -> list[dict]` (`id, name`)
  - `rotate_token(name: str) -> str | None` (new token, None if no user), `revoke(name: str) -> bool`
  - `delete_session(user_id, sid) -> bool` (deletes the session and its entries; usage rows stay so the daily budget is not reset)

- [ ] **Step 1: Write the failing tests**

```python
# apps/server/tests/test_store.py
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
        assert await s.count_users() == 1  # revoked user keeps its rows; it just cannot log in

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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/server/tests/test_store.py -q`
Expected: FAIL (`spent`, `list_users` etc. missing; `journal_mode` is `delete`).

- [ ] **Step 3: Implement**

In `store.py`:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE, token_sha256 TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, user_id TEXT, title TEXT, profile TEXT, sandbox_ref TEXT,
    created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS entries(session_id TEXT, user_id TEXT, seq INTEGER, type TEXT, json TEXT,
    PRIMARY KEY(session_id, seq));
CREATE TABLE IF NOT EXISTS usage(user_id TEXT, session_id TEXT, model TEXT, input INTEGER, output INTEGER, at REAL,
    cost REAL DEFAULT 0);
"""
```

`open()`:

```python
    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(SCHEMA)
        cols = [r["name"] for r in await self._all("PRAGMA table_info(usage)")]
        if "cost" not in cols:  # db from Stage 1
            await self._do("ALTER TABLE usage ADD COLUMN cost REAL DEFAULT 0")
```

Users (revoke sets the hash to NULL; UNIQUE allows many NULLs):

```python
    async def list_users(self) -> list[dict]:
        return await self._all("SELECT id, name, token_sha256 IS NOT NULL AS active FROM users ORDER BY name")

    async def count_users(self) -> int:
        return len(await self.list_users())

    async def rotate_token(self, name: str) -> str | None:
        token = secrets.token_urlsafe(32)
        cur = await self.db.execute("UPDATE users SET token_sha256=? WHERE name=?", (sha(token), name))
        await self.db.commit()
        return token if cur.rowcount else None

    async def revoke(self, name: str) -> bool:
        cur = await self.db.execute("UPDATE users SET token_sha256=NULL WHERE name=? AND token_sha256 IS NOT NULL",
                                    (name,))
        await self.db.commit()
        return cur.rowcount > 0
```

Sessions:

```python
    async def delete_session(self, user_id: str, sid: str) -> bool:
        cur = await self.db.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (sid, user_id))
        if cur.rowcount:
            await self.db.execute("DELETE FROM entries WHERE session_id=? AND user_id=?", (sid, user_id))
        await self.db.commit()
        return cur.rowcount > 0
```

Usage (replace the "recorded only" section):

```python
    # usage: cost in USD, computed by the server from profile prices
    async def add_usage(self, user_id: str, sid: str, model: str, input: int, output: int, cost: float = 0.0) -> None:
        await self._do("INSERT INTO usage(user_id, session_id, model, input, output, at, cost) VALUES(?,?,?,?,?,?,?)",
                       user_id, sid, model, input, output, time.time(), cost)

    async def spent(self, user_id: str, since: float, session_id: str | None = None) -> float:
        sql, args = "SELECT COALESCE(SUM(cost), 0) AS c FROM usage WHERE user_id=? AND at>=?", [user_id, since]
        if session_id:
            sql, args = sql + " AND session_id=?", args + [session_id]
        return (await self._all(sql, *args))[0]["c"]
```

Also fix the existing `INSERT INTO users VALUES(?,?,?)` — still 3 columns, unchanged. Add `"PRAGMA journal_mode"` result key: aiosqlite returns column `journal_mode`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest apps/server -q`
Expected: all pass (existing `add_usage(..., **u)` call still works because `cost` defaults to 0).

- [ ] **Step 5: Commit**

```bash
git add apps/server/src/simp_server/store.py apps/server/tests/test_store.py
git commit -m "Stage 2: store WAL, usage cost + spent(), token revoke/rotate, delete session"
```

---

### Task 2: Admin CLI, session delete, Docker-by-default guard, configurable hosts

**Files:**
- Modify: `apps/server/src/simp_server/server.py` (`load_settings`, `create_app`, `main`)
- Modify: `apps/server/src/simp_server/__main__.py` (dispatch new subcommands)
- Modify: `apps/web/src/api.ts`, `apps/web/src/App.tsx` (delete button in the session list)
- Modify: `README.md` (server section)
- Test: `apps/server/tests/test_server.py`

**Interfaces:**
- Consumes: Task 1 store methods.
- Produces:
  - `DELETE /api/sessions/{sid}` → `{"ok": true}`; 404 if not the caller's.
  - `SessionManager.drop(sid: str) -> None` (aborts a busy run, waits for its task, closes the sandbox, forgets the run).
  - `settings["host"]` (default `"127.0.0.1"`), `settings["allowed_hosts"]` (default `["localhost", "127.0.0.1"]`).
  - CLI: `simp-server users`, `simp-server revoke --name N`, `simp-server rotate --name N`.
  - `check_sandbox(settings, n_users) -> str | None` returns an error message when the sandbox is `LocalSandbox` and `n_users > 1` and `settings.get("allow_local_sandbox")` is not true.

- [ ] **Step 1: Write failing tests** (append to `test_server.py`)

```python
from simp_server.server import check_sandbox


async def test_revoke_rotate(env):
    app, mgr, user, token, run = await env(FakeProvider(reply("a")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        h = {"Authorization": f"Bearer {token}"}
        assert (await c.get("/api/sessions", headers=h)).status_code == 200
        new = await mgr.store.rotate_token(user["name"])
        assert (await c.get("/api/sessions", headers=h)).status_code == 401
        assert (await c.get("/api/sessions", headers={"Authorization": f"Bearer {new}"})).status_code == 200
        await mgr.store.revoke(user["name"])
        assert (await c.get("/api/sessions", headers={"Authorization": f"Bearer {new}"})).status_code == 401


async def test_delete_running_session(env):
    gated = Gated(["a", "b"])
    app, mgr, user, token, run = await env(gated)
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: gated.calls == 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        h = {"Authorization": f"Bearer {token}"}
        r = await c.delete(f"/api/sessions/{run.sid}", headers=h)
        assert r.status_code == 200
        assert run.task.done() and run.sid not in mgr.runs
        assert (await c.delete(f"/api/sessions/{run.sid}", headers=h)).status_code == 404
        assert (await c.get(f"/api/sessions/{run.sid}/files", headers=h)).status_code == 404


async def test_allowed_hosts_configurable(tmp_path):
    (tmp_path / "settings.toml").write_text(
        'allowed_hosts = ["box.local"]\n[profiles.test]\napi = "fake"\nmodel = "m"\n')
    app = create_app(load_settings(tmp_path), FakeProvider())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://box.local") as c:
        assert (await c.post("/api/hello", json={"type": "hello", "protocol_version": 1})).status_code == 200
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.post("/api/hello", json={"type": "hello", "protocol_version": 1})).status_code == 403


def test_check_sandbox(tmp_path):
    s = load_settings(tmp_path)
    assert check_sandbox(s, 1) is None
    assert "LocalSandbox" in check_sandbox(s, 2)
    assert check_sandbox({**s, "allow_local_sandbox": True}, 2) is None
    s["plugins"]["sandbox"] = "simp_server.sandboxes.docker:DockerSandbox"
    assert check_sandbox(s, 5) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/server/tests/test_server.py -q -k "revoke or delete_running or allowed_hosts or check_sandbox"`
Expected: FAIL (`check_sandbox` import error).

- [ ] **Step 3: Implement**

`server.py`:
- Delete the `ALLOWED_HOSTS` constant. In `load_settings` add:

```python
    s.setdefault("host", "127.0.0.1")
    s["allowed_hosts"] = set(s.get("allowed_hosts", ["localhost", "127.0.0.1"]))
```

- In `host_guard` use `settings["allowed_hosts"]`.
- Add after `load_plugin`:

```python
def check_sandbox(settings: dict, n_users: int) -> str | None:
    """LocalSandbox runs tools on this machine as the server user: fine for one person, not for several."""
    if settings["plugins"]["sandbox"].endswith(":LocalSandbox") and n_users > 1 and not settings.get("allow_local_sandbox"):
        return (f"{n_users} users but the sandbox is LocalSandbox (no isolation). Run `simp-server build-sandbox` and set "
                "[plugins] sandbox = \"simp_server.sandboxes.docker:DockerSandbox\" (or SIMP_SANDBOX=docker), "
                "or set allow_local_sandbox = true.")
    return None
```

- In `lifespan`, after `await store.open()`:

```python
        if err := check_sandbox(settings, await store.count_users()):
            raise SystemExit(err)
```

- `SessionManager.drop`:

```python
    async def drop(self, sid: str) -> None:
        run = self.runs.pop(sid, None)
        if run is None:
            return
        if run.task and not run.task.done():
            run.session.abort()
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
        await self.sandbox.close(run.ref)
```

- Endpoint:

```python
    @app.delete("/api/sessions/{sid}")
    async def delete_session(sid: str, u=Depends(user)):
        if await store.get_session(u["id"], sid) is None:
            raise HTTPException(404, "no such session")
        await mgr.drop(sid)
        await store.delete_session(u["id"], sid)
        return {"ok": True}
```

- `main()`: add subparsers `users`, `revoke --name`, `rotate --name`; reuse one helper:

```python
    async def with_store(fn):
        settings = load_settings()
        store = load_plugin(settings["plugins"]["store"])(settings)
        await store.open()
        try:
            return await fn(store)
        finally:
            await store.close()
```

  - `seed`: `print(asyncio.run(with_store(lambda s: s.add_user(a.name))))`
  - `users`: print `name<TAB>active` per row.
  - `revoke`: print `revoked` or exit 1 with `no active user named X`.
  - `rotate`: print the new token or exit 1 with `no user named X`.
  - `run`: `host=settings["host"]` instead of the literal `"127.0.0.1"`.
- `__main__.py`: dispatch `["run"], ["seed"], ["users"], ["revoke"], ["rotate"]` to `server_main`.

Web:
- `api.ts`: `deleteSession: (sid: string) => call(\`/api/sessions/${sid}\`, { method: "DELETE" }),`
- `App.tsx`: in the session list, a small `×` button per row (`aria-label="Delete session"`) that calls `api.deleteSession(id)` then reloads the list and clears the selection if it was the open one. No confirm dialog (Playwright and the browser-automation rules forbid native dialogs); ask by toggling the button text to "Delete?" on first click and deleting on the second.

README: document `users/revoke/rotate`, `host`, `allowed_hosts`, `allow_local_sandbox`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest apps/server -q && (cd apps/web && pnpm test && pnpm build)`
Expected: PASS. Note `env` fixture creates one user per `make()`, so `check_sandbox` never trips in existing tests; tests that create two apps in one fixture share nothing.

- [ ] **Step 5: Commit**

```bash
git add -A apps/server apps/web/src README.md
git commit -m "Stage 2: users/revoke/rotate CLI, DELETE session, LocalSandbox guard for several users, configurable hosts"
```

---

### Task 3: Budgets, kill switch, usage in the UI

**Files:**
- Create: `apps/server/src/simp_server/budget.py`
- Modify: `apps/server/src/simp_server/server.py` (`Run.__init__`, usage recording, new endpoints, startup warning)
- Modify: `apps/server/src/simp_server/__main__.py`, `server.main` (`pause`, `resume` subcommands)
- Modify: `apps/web/src/api.ts`, `apps/web/src/Chat.tsx` (spend chip in header)
- Modify: `apps/web/e2e/serve.sh`, `apps/web/e2e/app.spec.ts`
- Test: `apps/server/tests/test_budget.py`

**Interfaces:**
- Consumes: `store.spent`, `store.add_usage(..., cost=)`.
- Produces:
  - `budget.cost(profile: dict, usage: dict) -> float`
  - `budget.day_start(now: float | None = None) -> float` (local midnight)
  - `budget.Limits(user_day_usd: float = 2.0, run_usd: float = 0.5)`, `budget.limits(settings) -> Limits`
  - `budget.guard(stream_fn, check: Callable[[], Awaitable[str | None]])` → a stream_fn that, when `check()` returns a message, yields one `{"type": "error", "message": AssistantMessage(stop_reason="error", error=msg, error_kind="budget")}` and does not call the provider.
  - `Run.run_start: float` set in `Run.start`.
  - `GET /api/usage` → `{"today_usd": float, "day_limit_usd": float, "paused": bool}`
  - Kill switch: file `<data_dir>/PAUSED`; `simp-server pause` creates it, `simp-server resume` removes it.
- Settings: `[budget] user_day_usd`, `run_usd`; per profile `price_in`, `price_out` (USD per 1M tokens).

- [ ] **Step 1: Write failing tests**

```python
# apps/server/tests/test_budget.py
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
```

Before Step 3, check whether `FakeProvider` (`packages/simp_agent/src/simp_agent/testing/__init__.py`) counts calls; if it has no `calls` attribute, add `self.calls = 0` in `__init__` and `self.calls += 1` per call as part of this task.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/server/tests/test_budget.py -q`
Expected: FAIL (`budget` module missing).

- [ ] **Step 3: Implement**

```python
# apps/server/src/simp_server/budget.py
"""Money budgets. Cost comes from per-profile prices (USD per 1M tokens); the check runs before every LLM call."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from simp_agent.ai import AssistantMessage


@dataclass
class Limits:
    user_day_usd: float = 2.0
    run_usd: float = 0.5


def limits(settings: dict) -> Limits:
    return Limits(**settings.get("budget", dict()))


def cost(profile: dict, usage: dict) -> float:
    return (usage.get("input", 0) * profile.get("price_in", 0) + usage.get("output", 0) * profile.get("price_out", 0)) / 1e6


def day_start(now: float | None = None) -> float:
    d = datetime.fromtimestamp(now if now is not None else time.time())
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def guard(stream_fn, check):
    async def fn(model, ctx, **kw):
        if msg := await check():
            yield {"type": "error", "message": AssistantMessage(stop_reason="error", error=msg, error_kind="budget")}
            return
        async for ev in stream_fn(model, ctx, **kw):
            yield ev

    return fn
```

In `server.py`:
- `Run.__init__`: `self.profile = mgr.settings["profiles"][row["profile"]]`; `self.run_start = time.time()`; pass `stream_fn=budget.guard(mgr.stream_fn, self.over_budget)` to `AgentSession`.
- `Run.start`: set `self.run_start = time.time()` before `set_state("running")`.
- New method:

```python
    async def over_budget(self) -> str | None:
        lim, store = self.mgr.limits, self.mgr.store
        if self.mgr.paused():
            return "budget: server paused by the admin"
        if await store.spent(self.user_id, budget.day_start()) >= lim.user_day_usd:
            return f"budget: daily limit ${lim.user_day_usd:g} reached"
        if await store.spent(self.user_id, self.run_start, self.sid) >= lim.run_usd:
            return f"budget: run limit ${lim.run_usd:g} reached"
        return None
```

- usage recording: `await self.mgr.store.add_usage(self.user_id, self.sid, self.model.id, **u, cost=budget.cost(self.profile, u))`
- `SessionManager.__init__`: `self.limits = budget.limits(settings)`; `def paused(self) -> bool: return (Path(self.settings["data_dir"]) / "PAUSED").exists()`.
- Endpoint:

```python
    @app.get("/api/usage")
    async def usage(u=Depends(user)):
        return {"today_usd": round(await store.spent(u["id"], budget.day_start()), 4),
                "day_limit_usd": mgr.limits.user_day_usd, "paused": mgr.paused()}
```

- `lifespan`: for each profile without `price_in`/`price_out`, `log.warning("profile %s has no prices: its calls cost $0 and never hit a budget", name)` (use `logging.getLogger("simp_server")`; Task 6 makes it JSON).
- `main()`: `pause` → touch `<data_dir>/PAUSED`; `resume` → unlink with `missing_ok=True`. Both apply to running servers immediately (checked per LLM call). Add to `__main__.py` dispatch.

Web:
- `api.ts`: `usage: async (): Promise<{ today_usd: number; day_limit_usd: number; paused: boolean }> => (await call("/api/usage")).json(),`
- `Chat.tsx` header: a `<span className="spend" title="Spent today">` showing `$0.12 / $2` (and ` · paused` when paused), refreshed on mount and whenever `state.runState` becomes `idle` or `error`.

E2e:
- `serve.sh`: add `price_in = 100000` to the fake profile and `[budget]\nuser_day_usd = 1\nrun_usd = 1\n` (FakeLLM usage is 1 input token = $0.1 per call).
- `app.spec.ts`: new test "budget: header shows spend" → after one prompt, `.spend` contains `$0.1`. Do not add a test that exhausts the day budget in e2e (it would break later tests sharing the server); the unit tests cover the refusal.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q && make e2e`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A apps/server apps/web packages/simp_agent/src/simp_agent/testing
git commit -m "Stage 2: money budgets per user/day and per run, kill switch (pause/resume), spend in the UI"
```

---

### Task 4: Restart safety

**Files:**
- Modify: `apps/server/src/simp_server/server.py` (`Run.__init__`, new `Run.recover`, `SessionManager.get`, `SessionManager.info`)
- Test: `apps/server/tests/test_server.py`

**Interfaces:**
- Produces: `Run.recover() -> None` (async). Called once by `SessionManager.get` right after constructing a run. If the last durable `run_state` in the log is `running`, `waiting_approval` or `aborting`, it writes: `ApprovalResolved(decision="aborted")` for an approval request with no resolution, then `RunState(state="error")`, then `Notice(level="warning", text="interrupted: the server restarted during this run")`. `Run.info.run_state` starts from the last logged state (today it always starts `idle`).
- `SessionManager.info(row)` for a session not loaded in memory still returns `idle` (cheap list); the state is fixed when the session is opened.

- [ ] **Step 1: Write failing test**

```python
async def test_restart_with_pending_approval(tmp_path):
    (tmp_path / "settings.toml").write_text('[profiles.test]\napi = "fake"\nmodel = "m"\n')
    settings = load_settings(tmp_path)
    app = create_app(settings, FakeProvider(bash("c1", "echo hi")))
    mgr = app.state.mgr
    await mgr.store.open()
    user = await mgr.store.user_by_token(await mgr.store.add_user("u"))
    sid = (await mgr.store.add_session(user["id"], "test"))["id"]
    run = await mgr.get(user, sid)
    await run.command(p.Prompt(text="go"))
    await wait_for(lambda: run.pending is not None)
    run.task.cancel()  # simulate the process dying: no finally-handler writes reach the db
    await mgr.store.close()

    app2 = create_app(settings, FakeProvider(reply("after")))
    mgr2 = app2.state.mgr
    await mgr2.store.open()
    try:
        run2 = await mgr2.get(user, sid)
        assert run2.state == "error" and run2.pending is None
        tail = [e["type"] for e in run2.log[-3:]]
        assert tail == ["approval_resolved", "run_state", "notice"]
        assert run2.log[-3]["decision"] == "aborted" and "interrupted" in run2.log[-1]["text"]
        await run2.command(p.Prompt(text="again"))  # usable afterwards (core repairs the dangling tool call)
        await wait_for(lambda: run2.state == "idle" and run2.task.done())
    finally:
        await mgr2.store.close()
```

Note: cancelling the task lets `Run._run`'s `finally` write an `error` state before the store closes, which would hide the bug. Make the simulation honest: close the store first (`await mgr.store.close()`), then cancel, and wrap in `contextlib.suppress(Exception)`; or monkeypatch `run.durable` to a no-op before cancelling. Use the monkeypatch: `run.durable = lambda *a, **k: asyncio.sleep(0)` then `run.task.cancel()`; `await asyncio.gather(run.task, return_exceptions=True)`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/server/tests/test_server.py -q -k restart`
Expected: FAIL (`run2.state == "idle"`).

- [ ] **Step 3: Implement**

In `Run.__init__`, after `self.log = ...`:

```python
        states = [e["state"] for e in self.log if e["type"] == "run_state"]
        self.info.run_state = states[-1] if states else "idle"
```

New method:

```python
    async def recover(self) -> None:
        """A run that was busy when the process died: close it in the log so clients see a settled session."""
        if not self.busy:
            return
        resolved = {e["call_id"] for e in self.log if e["type"] == "approval_resolved"}
        for e in self.log:
            if e["type"] == "approval_request" and e["call_id"] not in resolved:
                await self.durable(p.ApprovalResolved, call_id=e["call_id"], decision="aborted")
        self.info.run_state = "error"  # any busy state -> error, bypassing check_transition on purpose
        await self.durable(p.RunState, state="error")
        await self.durable(p.Notice, level="warning", text="interrupted: the server restarted during this run")
```

`SessionManager.get`: after creating the Run, `await self.runs[sid].recover()` (inside the lock).

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: PASS. If the follow-up prompt fails because the core history ends with an assistant tool call that has no result, confirm `AgentSession` history repair (commit f41b8a0) covers it; if not, stop and report rather than patching core.

- [ ] **Step 5: Commit**

```bash
git add apps/server
git commit -m "Stage 2: runs busy at restart are closed as error with an 'interrupted' notice; state restored from the log"
```

---

### Task 5: Shared model wiring + plugins per profile

**Files:**
- Create: `packages/simp_agent/src/simp_agent/session/profile.py`
- Modify: `apps/server/src/simp_server/server.py` (`build_model` → import; `Run.__init__` plugins)
- Modify: `apps/cli/src/simp_cli/__init__.py` (`build_model` delegates)
- Test: `packages/simp_agent/tests/test_profile.py`, existing CLI and server tests

**Interfaces:**
- Produces:
  - `simp_agent.session.profile.build_model(pr: dict) -> Model` — the server's current behaviour (keys: `api` default `"anthropic-messages"`, `model`, `base_url`, `api_key_env`, `compat`, `max_tokens`, `context_window`; openai apis get `compat.include_usage = True` unless set).
  - `simp_agent.session.profile.build_plugins(names: list[str]) -> list` — maps `"redact_secrets"` → `RedactSecrets()`, `"plan_mode"` → `PlanMode()`; unknown name → `ValueError(f"unknown plugin {name!r}; have [...]")`.
  - Profile key `plugins = ["plan_mode"]` (server always adds `redact_secrets`).
- Layering: `session` may not import `plugins` (see `test_layers.py`: `ai <- agent <- coding <- session <- plugins`). Therefore put `build_plugins` in `simp_agent/plugins/__init__.py` instead, and `build_model` in `session/profile.py`.

- [ ] **Step 1: Write failing tests**

```python
# packages/simp_agent/tests/test_profile.py
import pytest

from simp_agent.plugins import build_plugins
from simp_agent.session.profile import build_model


def test_build_model_openai_defaults():
    m = build_model({"api": "openai-completions", "model": "x", "base_url": "http://h/v1", "context_window": 1000,
                     "api_key_env": "K"})
    assert (m.id, m.api, m.provider, m.base_url, m.api_key_env) == ("x", "openai-completions", "openai", "http://h/v1", "K")
    assert m.compat["include_usage"] is True and m.context_window == 1000


def test_build_model_keeps_explicit_compat():
    m = build_model({"api": "openai-responses", "model": "x", "compat": {"include_usage": False}})
    assert m.compat["include_usage"] is False


def test_build_plugins():
    assert [type(p).__name__ for p in build_plugins(["plan_mode", "redact_secrets"])] == ["PlanMode", "RedactSecrets"]
    with pytest.raises(ValueError, match="unknown plugin"):
        build_plugins(["nope"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/simp_agent/tests/test_profile.py -q`
Expected: FAIL (import errors).

- [ ] **Step 3: Implement**

`session/profile.py`: move the body of `server.build_model` verbatim. `server.py`: `from simp_agent.session.profile import build_model` and delete the local one. `plugins/__init__.py`:

```python
def build_plugins(names: list[str]) -> list:
    known = {"redact_secrets": RedactSecrets, "plan_mode": PlanMode}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(f"unknown plugin {unknown[0]!r}; have {sorted(known)}")
    return [known[n]() for n in names]
```

(import `RedactSecrets`, `PlanMode` from their modules at the top of `plugins/__init__.py` if not already exported.)

Server `Run.__init__`: `plugins=build_plugins(["redact_secrets", *[n for n in self.profile.get("plugins", []) if n != "redact_secrets"]])`. Validate at startup: in `create_app`, call `build_plugins(pr.get("plugins", []))` for every profile so a typo fails at boot, not on first chat.

CLI: keep its stricter validation (context_window required for openai, `OPENAI_BASE_URL` fallback, dropping falsy values) by building a cleaned dict and calling the shared function:

```python
def build_model(cfg: dict) -> Model:
    if cfg["api"] in ("openai-completions", "openai-responses"):
        if not cfg.get("model") or not cfg.get("context_window"):
            raise ValueError(f"model and context_window are required for {cfg['api']}")
        cfg = {**cfg, "base_url": cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")}
    return profile.build_model({k: v for k, v in cfg.items() if v not in (None, "")})
```

Check `apps/cli/tests` still pass; if a CLI test pins the anthropic default model id (the old CLI code omitted `id` when empty so `Model`'s default applied), keep that: the shared `build_model` must use `pr.get("model")` and drop `None` values before `Model(**kw)` rather than `pr["model"]`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: PASS, including `test_layers.py`.

- [ ] **Step 5: Commit**

```bash
git add -A packages/simp_agent apps/server apps/cli
git commit -m "Stage 2: shared build_model for CLI and server; agent plugins per profile"
```

---

### Task 6: Ops — JSON logs with run_id, backup command, run as a service

**Files:**
- Create: `apps/server/src/simp_server/ops.py`
- Create: `deploy/launchd/com.simp.server.plist`
- Modify: `apps/server/src/simp_server/server.py` (log calls in `Run.start`, `Run._run` finally, `over_budget` refusals, `recover`; `main` gains `backup`)
- Modify: `apps/server/src/simp_server/__main__.py`, `README.md`
- Test: `apps/server/tests/test_ops.py`

**Interfaces:**
- Produces:
  - `ops.setup_logging() -> None` — root handler on stderr, one JSON object per line: `{"ts", "level", "msg", ...extra}`; extras passed as `log.info("run start", extra={"run_id": ..., "session": ..., "user": ...})`.
  - `ops.backup(data_dir: Path, dest: Path) -> Path` — writes `dest/simp-<YYYYmmdd-HHMMSS>.tar.gz` containing `simp.db` (made with the sqlite3 online backup API, safe while the server runs), `settings.toml`, and `workspaces/` + `sandboxes/` dirs if present. Never includes `.env`.
  - CLI: `simp-server backup --to DIR`.
  - `Run.run_id: str` (new uuid hex[:8] per `start`).

- [ ] **Step 1: Write failing tests**

```python
# apps/server/tests/test_ops.py
import json
import logging
import sqlite3
import tarfile

from simp_server import ops


def test_json_log_line(capsys):
    ops.setup_logging()
    logging.getLogger("simp_server").info("run start", extra={"run_id": "r1", "session": "s1"})
    line = capsys.readouterr().err.strip().splitlines()[-1]
    d = json.loads(line)
    assert d["msg"] == "run start" and d["run_id"] == "r1" and d["session"] == "s1" and d["level"] == "INFO"


def test_backup_and_restore(tmp_path):
    home, out = tmp_path / "home", tmp_path / "out"
    home.mkdir()
    db = sqlite3.connect(home / "simp.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE t(x)")
    db.execute("INSERT INTO t VALUES(42)")
    db.commit()  # left open on purpose: backup must work while the server holds the db
    (home / ".env").write_text("OPENAI_API_KEY=secret")
    (home / "settings.toml").write_text("x = 1")
    (home / "workspaces" / "s1").mkdir(parents=True)
    (home / "workspaces" / "s1" / "a.txt").write_text("hi")

    f = ops.backup(home, out)
    names = tarfile.open(f).getnames()
    assert ".env" not in names and "settings.toml" in names and "workspaces/s1/a.txt" in names

    restored = tmp_path / "restored"
    tarfile.open(f).extractall(restored, filter="data")
    assert sqlite3.connect(restored / "simp.db").execute("SELECT x FROM t").fetchone() == (42,)
    db.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/server/tests/test_ops.py -q`
Expected: FAIL (no `ops`).

- [ ] **Step 3: Implement**

```python
# apps/server/src/simp_server/ops.py
"""JSON logs and backups for running the server as a long-lived service on one machine."""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

_STD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {"ts": round(r.created, 3), "level": r.levelname, "msg": r.getMessage()}
        d.update({k: v for k, v in vars(r).items() if k not in _STD})
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)


def backup(data_dir: Path, dest: Path) -> Path:
    data_dir, dest = Path(data_dir), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"simp-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(out, "w:gz") as tar:
        if (data_dir / "simp.db").exists():
            snap = Path(tmp) / "simp.db"
            src, dst = sqlite3.connect(data_dir / "simp.db"), sqlite3.connect(snap)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            tar.add(snap, "simp.db")
        for name in ("settings.toml", "workspaces", "sandboxes"):
            if (data_dir / name).exists():
                tar.add(data_dir / name, name)
    return out
```

`server.py`:
- `log = logging.getLogger("simp_server")`.
- `Run.start`: `self.run_id = uuid.uuid4().hex[:8]`; `log.info("run start", extra=self._ctx())` where `_ctx()` returns `{"run_id": self.run_id, "session": self.sid, "user": self.user_id}`.
- end of `_turn`: `log.info("run end", extra={**self._ctx(), "state": self.state})`; `_run` finally (stuck path): `log.error("run stopped unexpectedly", extra=self._ctx(), exc_info=True)`.
- `over_budget` when returning a message: `log.warning(msg, extra=self._ctx())`.
- `recover`: `log.warning("recovered interrupted run", extra={"session": self.sid})`.
- `main()` for `run`: call `ops.setup_logging()` before `uvicorn.run(..., log_config=None)` so uvicorn's loggers propagate to the JSON root handler. `backup --to DIR`: `print(ops.backup(Path(load_settings()["data_dir"]), Path(a.to)))`.

`deploy/launchd/com.simp.server.plist`: a LaunchAgent running `/usr/bin/env uv run --project <REPO> simp-server run --port 8766`, `KeepAlive` true, `RunAtLoad` true, `EnvironmentVariables` `SIMP_SANDBOX=docker`, `StandardErrorPath` `~/.simp-server/server.log`, plus a second plist `com.simp.backup.plist` with `StartCalendarInterval` Hour 3 running `simp-server backup --to ~/.simp-server/backups`. Use the literal placeholder `__REPO__` and `__HOME__` and document in README: `sed "s#__REPO__#$PWD#; s#__HOME__#$HOME#" deploy/launchd/com.simp.server.plist > ~/Library/LaunchAgents/com.simp.server.plist && launchctl load ~/Library/LaunchAgents/com.simp.server.plist`.

README: "Running as a service", "Backups and restore" (restore = stop server, `tar xzf <file> -C ~/.simp-server`, start), "Budgets", "Admin commands".

- [ ] **Step 4: Run tests + one manual restore drill**

Run: `uv run pytest -q`
Then the drill (record output in the commit message body):

```bash
export SIMP_SERVER_HOME=$(mktemp -d)
printf '[profiles.fake]\napi = "fake"\nmodel = "fake"\n' > $SIMP_SERVER_HOME/settings.toml
uv run simp-server seed --name drill > $SIMP_SERVER_HOME/token
uv run simp-server backup --to $SIMP_SERVER_HOME/b
mkdir $SIMP_SERVER_HOME/r && tar xzf $SIMP_SERVER_HOME/b/*.tar.gz -C $SIMP_SERVER_HOME/r
SIMP_SERVER_HOME=$SIMP_SERVER_HOME/r uv run simp-server users   # expect: drill	1
```

- [ ] **Step 5: Commit**

```bash
git add -A apps/server deploy README.md
git commit -m "Stage 2: JSON logs with run_id, backup command, launchd service files"
```

---

### Task 7: Roadmap + final check

**Files:** `docs/ROADMAP.md`

- [ ] Move Stage 2 into "Done" with a one-paragraph summary; keep the "Deferred" list.
- [ ] Run `uv run pytest -q && make e2e && (cd apps/web && pnpm test && pnpm build)`; all pass.
- [ ] Commit: `docs: Stage 2 done`.

---

## Parallel execution (replaces the task order above)

Each agent works in its own git worktree on its own branch; the coordinator merges into `stage2`.
Files several tasks touch (`server.py`, `__main__.py`, `README.md`) get small, local edits only, so merges stay mechanical.

| Wave | Agents (parallel) | Depends on |
|---|---|---|
| 1 | Task 1 (store), Task 4 (restart), Task 5 (wiring), Task 6 (ops) | — |
| 2 | Task 2 (admin), Task 3 (budget) | Task 1 merged |
| 3 | Coordinator: merge, full test + e2e, whole-branch review, Task 7 | all |

Ownership rules to avoid conflicts:
- Only Task 1 edits `store.py`. Task 2/3 only call its methods.
- Task 6 adds logging in `Run.start`/`_turn`/`_run` and `main` only; the `over_budget` log line belongs to Task 3, the `recover` log line to Task 4 (they use `logging.getLogger("simp_server")`, which Task 6 formats).
- Only Task 5 touches `build_model` and the `plugins=` argument in `Run.__init__`.
- Only Task 3 changes `stream_fn=` in `Run.__init__`.
- `__main__.py` dispatch: each task adds its own subcommand names to the list; coordinator unions them on merge.
