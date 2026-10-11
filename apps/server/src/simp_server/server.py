"""Real server: same HTTP API as fake.py, backed by AgentSession + SQLite. Plugin slots come from settings.toml.

GET/POST /api/sessions, GET /api/sessions/{id}/events (SSE), POST /api/sessions/{id}/commands,
GET /api/sessions/{id}/files?path=, GET|PUT /api/sessions/{id}/files/raw?path=   (all need Authorization: Bearer)
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import hmac
import re
import sqlite3
import shutil
import sys
import logging
import os
import time
import tomllib
import uuid
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from typing import Protocol

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ValidationError

from simp_agent import ai
from simp_agent.agent import api_key_opts
from simp_agent.agent.env import ExecutionEnv, LocalEnv
from simp_agent.ai import Context, CustomEntry, Model, ThinkingContent, UserMessage, from_dict, to_dict
from simp_agent.plugins import PlanMode, build_plugins
from simp_agent.session import AgentSession
from simp_agent.session.profile import build_model

from . import budget, ops
from . import protocol as p
from .fake import sse

log = logging.getLogger("simp_server")

SHUTDOWN_GRACE = 2  # seconds
HEARTBEAT = 15  # seconds between SSE ": ping" comments
QUEUE_MAX = 1000  # events buffered per SSE client; a client that falls this far behind is dropped and reconnects
MAX_QUEUED = 20  # steer + follow-up messages waiting per session
HOME = Path(os.environ.get("SIMP_SERVER_HOME", Path.home() / ".simp-server"))
TITLE_PROMPT = "Name this coding session in 3 to 6 words. Reply with the title only."
DEFAULT_PLUGINS = {"sandbox": "simp_server.server:LocalSandbox", "store": "simp_server.store:SqliteStore",
                   "auth": "simp_server.server:StaticTokenAuth"}


# ---- plugin slots ---------------------------------------------------------------------------------------------------

class Sandbox(Protocol):
    async def open(self, session_id: str) -> ExecutionEnv: ...

    async def close(self, session_id: str) -> None: ...

    async def remove(self, session_id: str) -> None: ...  # delete the workspace files (session deleted)


class Store(Protocol):  # see store.SqliteStore for the full method list
    async def open(self) -> None: ...


class Auth(Protocol):
    async def authenticate(self, request: Request) -> dict | None: ...  # user {id, name} or None


class LocalSandbox:
    """A per-session dir under the data dir; LocalEnv rooted there. Not isolation: DockerSandbox replaces it."""

    def __init__(self, settings: dict):
        self.root = Path(settings["data_dir"]) / "workspaces"

    async def open(self, session_id: str) -> LocalEnv:
        d, old = self.root / session_id, self.root.parent / "sandboxes" / session_id
        if old.exists() and not d.exists():  # Stage 2 layout: keep old sessions' files
            self.root.mkdir(parents=True, exist_ok=True)
            shutil.move(old, d)
        d.mkdir(parents=True, exist_ok=True)
        return LocalEnv(str(d.resolve()))

    async def close(self, session_id: str) -> None:
        pass

    async def remove(self, session_id: str) -> None:
        shutil.rmtree(self.root / session_id, ignore_errors=True)


class StaticTokenAuth:
    def __init__(self, store):
        self.store = store

    async def authenticate(self, request: Request) -> dict | None:
        h = request.headers.get("authorization", "")
        return await self.store.user_by_token(h[7:]) if h.startswith("Bearer ") else None


class Account(BaseModel):
    name: str
    password: str
    code: str = ""


NAME_RE = re.compile(r"[a-z0-9_-]{2,32}")
MIN_PASSWORD = 8


def load_plugin(path: str):
    mod, _, name = path.partition(":")
    return getattr(import_module(mod), name)


def check_sandbox(settings: dict, n_users: int) -> str | None:
    """LocalSandbox runs tools on this machine as the server user: fine for one person, not for several."""
    if settings["plugins"]["sandbox"].endswith(":LocalSandbox") and n_users > 1 and not settings.get("allow_local_sandbox"):
        return (f"{n_users} users but the sandbox is LocalSandbox (no isolation). Run `simp-server build-sandbox` and set "
                "[plugins] sandbox = \"simp_server.sandboxes.docker:DockerSandbox\" (or SIMP_SANDBOX=docker), "
                "or set allow_local_sandbox = true.")
    return None


# ---- settings + keys ------------------------------------------------------------------------------------------------

def load_settings(home: Path = HOME) -> dict:
    f = home / "settings.toml"
    s = tomllib.loads(f.read_text()) if f.exists() else dict()
    s.setdefault("data_dir", str(home))
    s["data_dir"] = str(Path(s["data_dir"]).expanduser())
    docker = {"sandbox": "simp_server.sandboxes.docker:DockerSandbox"} if os.environ.get("SIMP_SANDBOX") == "docker" else {}
    s["plugins"] = {**DEFAULT_PLUGINS, **docker, **s.get("plugins", dict())}
    s.setdefault("profiles", dict())
    s.setdefault("host", "127.0.0.1")
    s["allowed_hosts"] = set(s.get("allowed_hosts", ["localhost", "127.0.0.1"]))
    s.setdefault("default_profile", next(iter(s["profiles"]), None))
    return s


def take_keys(settings: dict) -> dict:
    """Model keys from <data_dir>/.env and the process env. Removed from os.environ so sandboxed commands never see them."""
    names = {pr.get("api_key_env") for pr in settings["profiles"].values()} | {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    keys = dict()
    f = Path(settings["data_dir"]) / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                keys[k.strip()] = v.strip().strip("'\"")
    for n in names - {None}:
        if n in os.environ:
            keys.setdefault(n, os.environ.pop(n))
    return {k: v for k, v in keys.items() if v}  # an empty value is no key


# ---- one conversation -----------------------------------------------------------------------------------------------

log = logging.getLogger("simp_server")


class Run:
    """AgentSession + durable protocol log + in-flight buffers. Subscribers only get per-connection queues."""

    def __init__(self, mgr: "SessionManager", row: dict, env: ExecutionEnv, entries: list[dict]):
        self.mgr, self.sid, self.user_id, self.env, self.ref = mgr, row["id"], row["user_id"], env, row["sandbox_ref"]
        self.info = p.SessionInfo(id=row["id"], title=row["title"] or "")
        self.log = [e["data"] for e in entries if e["type"] != "msg"]  # ponytail: whole log in memory
        states = [e["state"] for e in self.log if e["type"] == "run_state"]
        self.info.run_state = states[-1] if states else "idle"
        self.seq = entries[-1]["seq"] if entries else 0
        self.inflight, self.pending, self.answer = p.InFlight(), None, None
        self.subs, self.task, self.title_task = set(), None, None
        self.profile = mgr.settings["profiles"][row["profile"]]
        self.model = build_model(self.profile)
        self.run_start = time.time()
        self.session = AgentSession(
            self.model, store=self, env=env, cwd=getattr(env, "root", None) or "/", stream_fn=self.guarded_stream,
            get_api_key=mgr.api_key_for(self.model), approve=self.approve,
            messages=[from_dict(e["data"]) for e in entries if e["type"] == "msg"],
            plugins=build_plugins(["redact_secrets", "plan_mode",
                                   *[n for n in self.profile.get("plugins", []) if n not in ("redact_secrets", "plan_mode")]]),
            plugin_config={"redact_secrets": {"secrets": list(mgr.keys.values())}})
        self.session.subscribe(self.on_event)

    @property
    def guarded_stream(self):
        return budget.guard(self.mgr.stream_fn, self.over_budget)

    @property
    def plan_mode(self) -> bool:
        last = next((m for m in reversed(self.session.messages) if isinstance(m, CustomEntry) and m.type == "plan_mode"), None)
        return bool(last and last.data["enabled"])

    @property
    def state(self) -> str:
        return self.info.run_state

    @property
    def busy(self) -> bool:
        return self.state in ("running", "waiting_approval", "aborting")

    # SessionStore for AgentSession: core messages share the seq counter with protocol events
    async def append(self, entry) -> None:
        self.seq += 1
        await self.mgr.store.add_entry(self.user_id, self.sid, self.seq, "msg", to_dict(entry))

    def _send(self, ev: dict) -> None:
        for q in list(self.subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:  # never block the run: drop the slow client; it reconnects and gets a snapshot
                self.subs.discard(q)

    async def durable(self, cls, **kw) -> None:
        self.seq += 1
        ev = cls(seq=self.seq, **kw).model_dump()
        self.log.append(ev)
        self._send(ev)
        await self.mgr.store.add_entry(self.user_id, self.sid, ev["seq"], ev["type"], ev)

    async def recover(self) -> None:
        """A run that was busy when the process died: close it in the log so clients see a settled session."""
        if not self.busy:
            return
        log.warning("recovered interrupted run", extra={"session": self.sid})
        resolved = {e["call_id"] for e in self.log if e["type"] == "approval_resolved"}
        for e in self.log:
            if e["type"] == "approval_request" and e["call_id"] not in resolved:
                await self.durable(p.ApprovalResolved, call_id=e["call_id"], decision="aborted")
        self.info.run_state = "error"  # any busy state -> error, bypassing check_transition on purpose
        await self.durable(p.RunState, state="error")
        await self.durable(p.Notice, level="warning", text="interrupted: the server restarted during this run")

    async def set_state(self, s: str) -> None:
        p.check_transition(self.state, s)
        self.info.run_state = s
        await self.durable(p.RunState, state=s)

    def subscribe(self, after: int) -> tuple[list[dict], asyncio.Queue]:
        """Missed durable events, then a snapshot, then live. No await here, so nothing slips in between."""
        q = asyncio.Queue(QUEUE_MAX)
        self.subs.add(q)
        snap = p.Snapshot(last_seq=self.seq, run_state=self.state, in_flight=self.inflight, pending_approval=self.pending,
                          title=self.info.title, plan_mode=self.plan_mode)
        return [*(e for e in self.log if e["seq"] > after), snap.model_dump()], q

    async def on_event(self, e: dict) -> None:
        t, f = e["type"], self.inflight
        if t == "message_update" and e["event"]["type"] == "start":  # a new assistant message begins
            self.inflight = p.InFlight(msg_id=uuid.uuid4().hex[:8], tool_outputs=f.tool_outputs)
        elif t == "message_update" and e["event"]["type"] in ("text_delta", "thinking_delta"):
            kind, delta = e["event"]["type"][:-6], e["event"]["delta"]
            off = len(getattr(f, kind))
            setattr(f, kind, getattr(f, kind) + delta)
            cls = p.TextDelta if kind == "text" else p.ThinkingDelta
            self._send(cls(msg_id=f.msg_id, offset=off, delta=delta).model_dump())
        elif t == "tool_execution_update":
            cid, old = e["call"].id, f.tool_outputs.get(e["call"].id, "")
            f.tool_outputs[cid] = old + e["text"]
            self._send(p.ToolOutput(call_id=cid, offset=len(old), delta=e["text"]).model_dump())
        elif t == "message_end":
            m = e["message"]
            if m.role == "user":
                await self.durable(p.UserMessage, text=m.content)
            elif m.role == "assistant":
                self.inflight = p.InFlight(tool_outputs=f.tool_outputs)
                u = {"input": m.usage.get("input", 0), "output": m.usage.get("output", 0)}
                await self.durable(
                    p.AssistantMessage, msg_id=f.msg_id or uuid.uuid4().hex[:8], text=m.text(), usage=p.Usage(**u),
                    thinking="".join(c.thinking for c in m.content if isinstance(c, ThinkingContent) and not c.redacted),
                    tool_calls=[p.ToolCall(id=c.id, name=c.name, arguments=c.arguments) for c in m.tool_calls()],
                    stop_reason=m.stop_reason, error=m.error)
                await self.mgr.store.add_usage(self.user_id, self.sid, self.model.id, **u, cost=budget.cost(self.profile, u))
                if not self.info.title and self.title_task is None:
                    self.title_task = asyncio.create_task(self._title())
            elif m.role == "tool_result":
                f.tool_outputs.pop(m.tool_call_id, None)
                await self.durable(p.ToolResult, call_id=m.tool_call_id, tool=m.tool_name, content=m.content,
                                   is_error=m.is_error)
        elif t == "compaction_end":
            if e["error"]:
                await self.durable(p.Notice, level="error", text=f"compaction failed: {e['error']}")
            else:
                summary = next((m.summary for m in reversed(self.session.messages) if m.role == "compaction"), "")
                await self.durable(p.Compaction, summary=summary, tokens_before=e["tokens_before"],
                                   tokens_after=e["tokens_after"])
        elif t == "auto_retry_start":
            await self.durable(p.Notice, level="warning", text=f"retry {e['attempt']}/{e['max_attempts']}: {e['error']}")
        elif t == "auto_retry_end":
            await self.durable(p.Notice, text=f"retry {'succeeded' if e['success'] else 'failed'}")
        elif t == "plugin_error":
            await self.durable(p.Notice, level="error", text=f"plugin {e['plugin']}.{e['hook']}: {e['error']}")

    async def approve(self, call) -> str:
        """AgentSession approve callback: ask every tab, wait for a decision. Abort cancels this."""
        self.answer = asyncio.get_running_loop().create_future()
        self.pending = p.PendingApproval(call_id=call.id, tool=call.name, args=call.arguments)
        try:  # an abort can land at any await here, not only while waiting for the answer
            await self.durable(p.ApprovalRequest, call_id=call.id, tool=call.name, args=call.arguments)
            if self.state == "running":
                await self.set_state("waiting_approval")
            decision = await self.answer
        except asyncio.CancelledError:
            self.pending = None
            await self.durable(p.ApprovalResolved, call_id=call.id, decision="aborted")
            raise
        self.pending = None
        await self.durable(p.ApprovalResolved, call_id=call.id, decision=decision)
        if self.state == "waiting_approval":
            await self.set_state("running")
        return decision

    async def _title(self) -> None:
        """One extra small LLM call to name the session. Any failure leaves the title empty."""
        try:
            first = next(e["text"] for e in self.log if e["type"] == "user_message")[:2000]
            # reasoning models think before answering: leave room, and use the lowest effort all of them accept
            model = dataclasses.replace(self.model, max_tokens=200, compat={**self.model.compat, "reasoning_effort": "low"})
            msg = None
            async for ev in self.guarded_stream(model, Context(TITLE_PROMPT, [UserMessage(first)], []),
                                                **await api_key_opts(self.mgr.api_key_for(model), model)):
                if ev["type"] in ("done", "error"):
                    msg = ev["message"]
            if msg is None or msg.stop_reason == "error":
                raise RuntimeError(msg.error if msg else "no response")
            u = {"input": msg.usage.get("input", 0), "output": msg.usage.get("output", 0)}
            await self.mgr.store.add_usage(self.user_id, self.sid, self.model.id, **u, cost=budget.cost(self.profile, u))
            title = " ".join(msg.text().replace('"', "").replace("'", "").split())[:60]
            if not title:
                raise RuntimeError(f"empty title (stop_reason={msg.stop_reason}, usage={u})")
            self.info.title = title
            await self.mgr.store.set_title(self.user_id, self.sid, title)
            await self.durable(p.SessionTitle, title=title)
        except Exception as e:
            log.warning("session title failed: %s", e, extra={"session": self.sid})

    async def start(self, text, fresh: bool = True) -> None:  # text: a prompt, or a coroutine factory (continue_, compact)
        if fresh:  # a queued follow-up stays inside the same run budget
            self.run_start = time.time()
        await self.set_state("running")
        self.run_id = uuid.uuid4().hex[:8]
        log.info("run start", extra=self._ctx())
        fn = text if callable(text) else functools.partial(self.session.prompt, text)
        self.task = asyncio.create_task(self._run(fn))

    async def over_budget(self) -> str | None:
        lim, store, msg = self.mgr.limits, self.mgr.store, None
        if self.mgr.paused():
            msg = "budget: server paused by the admin"
        elif not await store.user_active(self.user_id):
            msg = "budget: user revoked"
        elif await store.spent(self.user_id, budget.day_start()) >= lim.user_day_usd:
            msg = f"budget: daily limit ${lim.user_day_usd:g} reached"
        elif await store.spent(self.user_id, self.run_start, self.sid) >= lim.run_usd:
            msg = f"budget: run limit ${lim.run_usd:g} reached"
        if msg:
            log.warning("over budget: %s", msg, extra=self._ctx())
        return msg

    def _ctx(self) -> dict:
        return {"run_id": self.run_id, "session": self.sid, "user": self.user_id}

    async def _run(self, fn) -> None:
        try:
            await self._turn(fn)
        finally:  # never leave the session stuck busy, whatever failed (even a store write or a cancel)
            self.mgr.last_used[self.sid] = time.monotonic()
            if self.busy and self.task is asyncio.current_task():
                log.error("run stopped unexpectedly", extra=self._ctx(), exc_info=True)
                self.pending, self.inflight, self.info.run_state = None, p.InFlight(), "error"
                try:
                    await self.durable(p.RunState, state="error")
                    await self.durable(p.Notice, level="error", text="run stopped unexpectedly")
                except Exception:
                    pass

    async def _turn(self, fn) -> None:
        try:
            await fn()
        except Exception as e:
            await self.durable(p.Notice, level="error", text=f"{type(e).__name__}: {e}")
        self.inflight = p.InFlight()
        agent = self.session.agent
        if self.state == "aborting":
            agent.clear_queues()
            await self.set_state("idle")
            await self.durable(p.Notice, level="warning", text="run aborted")
            log.info("run end", extra={**self._ctx(), "state": "aborted"})
            return
        last = agent.messages[-1] if agent.messages else None
        await self.set_state("error" if last and last.role == "assistant" and last.stop_reason == "error" else "idle")
        log.info("run end", extra={**self._ctx(), "state": self.state})
        if agent.follow_ups:  # came in after the loop decided to stop
            await self.start(agent.follow_ups.pop(0).content, fresh=False)

    async def command(self, c) -> None:
        if isinstance(c, (p.Prompt, p.FollowUp, p.Steer)):
            if not self.busy:
                await self.start(c.text)
            elif len(self.session.agent.steering) + len(self.session.agent.follow_ups) >= MAX_QUEUED:
                raise HTTPException(429, f"{MAX_QUEUED} messages already queued")
            elif isinstance(c, p.Steer):
                self.session.steer(c.text)
            else:
                self.session.follow_up(c.text)
        elif isinstance(c, p.Abort):
            if self.busy and self.state != "aborting":
                await self.set_state("aborting")
                self.session.abort()
        elif isinstance(c, p.Approve):
            if not self.pending or self.pending.call_id != c.call_id or self.answer.done():
                raise HTTPException(409, "no pending approval with that call_id")
            self.answer.set_result(c.decision)
        elif isinstance(c, (p.Compact, p.Continue)):
            if self.busy:
                raise HTTPException(409, f"cannot {c.type} while the session is {self.state}")
            await self.start(self.session.compact if isinstance(c, p.Compact) else self.session.continue_)
        elif isinstance(c, p.SetPlanMode):
            await self.session.start()  # plugin setup runs here (first prompt otherwise)
            await next(pl for pl in self.session.plugins if isinstance(pl, PlanMode)).set_enabled(c.enabled)
            await self.durable(p.Notice, text=f"plan mode {'on' if c.enabled else 'off'}")


class SessionManager:
    def __init__(self, settings: dict, store, sandbox, stream_fn):
        self.settings, self.store, self.sandbox, self.stream_fn = settings, store, sandbox, stream_fn
        self.keys = take_keys(settings)
        self.limits = budget.limits(settings)
        self.runs: dict[str, Run] = dict()
        self.last_used: dict[str, float] = dict()
        self.idle_s = settings.get("idle_minutes", 15) * 60
        self.cap = settings.get("max_open_sessions", 8)
        self.lock = asyncio.Lock()  # ponytail: one lock for loading runs; per-session locks if it ever matters

    def paused(self) -> bool:
        return (Path(self.settings["data_dir"]) / "PAUSED").exists()

    def api_key_for(self, model: Model):
        name = model.api_key_env or ("OPENAI_API_KEY" if model.api.startswith("openai") else "ANTHROPIC_API_KEY")
        return lambda provider: self.keys.get(name)

    async def get(self, user: dict, sid: str) -> Run:
        row = await self.store.get_session(user["id"], sid)
        if row is None:
            raise HTTPException(404, "no such session")
        async with self.lock:
            if sid not in self.runs:
                if len(self.runs) >= self.cap:
                    lru = min((s for s, r in self.runs.items() if self.evictable(r)), key=self.last_used.get, default=None)
                    if lru is None:
                        raise HTTPException(503, "too many active sessions, try again later")
                    await self.evict(lru)
                env = await self.sandbox.open(row["sandbox_ref"])
                self.runs[sid] = Run(self, row, env, await self.store.entries(user["id"], sid))
                await self.runs[sid].recover()
            self.last_used[sid] = time.monotonic()
        return self.runs[sid]

    def evictable(self, run: Run) -> bool:
        return not run.busy and not run.subs and (run.task is None or run.task.done())

    async def evict(self, sid: str) -> None:
        """Free RAM and the container; files and log stay, the next get reloads from the store."""
        run = self.runs.pop(sid)
        self.last_used.pop(sid, None)
        await self.sandbox.close(run.ref)

    async def evict_idle(self) -> None:
        async with self.lock:
            now = time.monotonic()
            for sid, run in list(self.runs.items()):
                if self.evictable(run) and now - self.last_used.get(sid, 0) >= self.idle_s:
                    await self.evict(sid)

    async def evict_loop(self, every: float) -> None:
        while True:
            await asyncio.sleep(every)
            try:
                await self.evict_idle()
            except Exception:
                log.exception("idle eviction failed")

    async def drop(self, sid: str, ref: str) -> None:
        """Stop the run (if loaded), close its sandbox, and delete its workspace files."""
        run = self.runs.pop(sid, None)
        self.last_used.pop(sid, None)
        if run and run.task and not run.task.done():
            run.session.abort()
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
        await self.sandbox.close(ref)
        await self.sandbox.remove(ref)

    def info(self, row: dict) -> p.SessionInfo:
        r = self.runs.get(row["id"])
        return p.SessionInfo(id=row["id"], title=row["title"] or "", run_state=r.state if r else "idle",
                             plan_mode=r.plan_mode if r else False)


# ---- app ------------------------------------------------------------------------------------------------------------

def create_app(settings: dict, stream_fn=ai.stream) -> FastAPI:
    pl = settings["plugins"]
    for pr in settings["profiles"].values():
        build_plugins(pr.get("plugins", []))  # a typo fails at boot, not on first chat
    store = load_plugin(pl["store"])(settings)
    sandbox = load_plugin(pl["sandbox"])(settings)
    auth = load_plugin(pl["auth"])(store)
    mgr = SessionManager(settings, store, sandbox, stream_fn)

    @asynccontextmanager
    async def lifespan(app):
        await store.open()
        if err := check_sandbox(settings, await store.count_users()):
            raise SystemExit(err)
        for name, pr in settings["profiles"].items():
            if "price_in" not in pr or "price_out" not in pr:
                log.warning("profile %s has no prices: its calls cost $0 and never hit a budget", name)
        evictor = asyncio.create_task(mgr.evict_loop(settings.get("evict_every", 60)))
        yield
        evictor.cancel()
        for run in list(mgr.runs.values()):
            await sandbox.close(run.ref)
        if hasattr(sandbox, "close_all"):
            await sandbox.close_all()
        await store.close()

    app = FastAPI(lifespan=lifespan)
    app.state.mgr = mgr

    @app.middleware("http")
    async def host_guard(request: Request, call_next):  # DNS rebinding: only our own host names
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in settings["allowed_hosts"]:
            return JSONResponse({"detail": "bad host"}, status_code=403)
        return await call_next(request)

    async def user(request: Request) -> dict:
        u = await auth.authenticate(request)
        if u is None:
            raise HTTPException(401, "bad token")
        return u

    @app.post("/api/signup")
    async def signup(a: Account):
        code = settings.get("signup_code")
        if not code or not hmac.compare_digest(a.code.encode(), str(code).encode()):
            raise HTTPException(403, "sign-up is closed or the invite code is wrong")
        if not NAME_RE.fullmatch(a.name):
            raise HTTPException(400, "username: 2-32 of a-z 0-9 _ -")
        if len(a.password) < MIN_PASSWORD:
            raise HTTPException(400, f"password: at least {MIN_PASSWORD} characters")
        if err := check_sandbox(settings, await store.count_users() + 1):
            raise HTTPException(409, err)
        try:
            await store.add_user(a.name, password=a.password, token=False)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "that username is taken") from None
        return {"token": await store.login(a.name, a.password)}

    @app.post("/api/login")
    async def login(a: Account):
        if (token := await store.login(a.name, a.password)) is None:
            raise HTTPException(401, "Wrong username or password.")
        return {"token": token}

    @app.post("/api/logout")
    async def logout(request: Request, u=Depends(user)):
        await store.logout(request.headers["authorization"][7:])
        return {"ok": True}

    @app.post("/api/hello")
    def hello(h: p.Hello):
        r = p.check_hello(h)
        return JSONResponse(r.model_dump(), status_code=400 if isinstance(r, p.HelloError) else 200)

    @app.get("/api/profiles")
    async def profiles(u=Depends(user)) -> list[str]:
        return list(settings["profiles"])

    @app.get("/api/usage")
    async def usage(u=Depends(user)):
        return {"today_usd": round(await store.spent(u["id"], budget.day_start()), 4),
                "day_limit_usd": mgr.limits.user_day_usd, "paused": mgr.paused()}

    @app.get("/api/sessions")
    async def list_sessions(u=Depends(user)) -> list[p.SessionInfo]:
        return [mgr.info(r) for r in await store.list_sessions(u["id"])]

    @app.post("/api/sessions")
    async def new_session(request: Request, u=Depends(user)) -> p.SessionInfo:
        body = await request.json() if await request.body() else dict()
        profile = body.get("profile") or settings["default_profile"]
        if profile not in settings["profiles"]:
            raise HTTPException(400, f"unknown profile {profile!r}; have {sorted(settings['profiles'])}")
        return mgr.info(await store.add_session(u["id"], profile, body.get("title", "")))

    @app.delete("/api/sessions/{sid}")
    async def delete_session(sid: str, u=Depends(user)):
        if (row := await store.get_session(u["id"], sid)) is None:
            raise HTTPException(404, "no such session")
        await mgr.drop(sid, row["sandbox_ref"])
        await store.delete_session(u["id"], sid)
        return {"ok": True}

    @app.post("/api/sessions/{sid}/commands")
    async def post_command(sid: str, request: Request, u=Depends(user)):
        try:
            c = p.command.validate_python(await request.json())
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False)) from None
        await (await mgr.get(u, sid)).command(c)
        return {"ok": True}

    @app.get("/api/sessions/{sid}/events")
    async def events(sid: str, request: Request, after: int | None = None, u=Depends(user)):
        run = await mgr.get(u, sid)
        first, q = run.subscribe(after if after is not None else int(request.headers.get("last-event-id") or 0))

        async def gen():
            try:
                for ev in first:
                    yield sse(ev)
                while q in run.subs or not q.empty():  # dropped (queue overflow): send what we have, then end
                    try:
                        yield sse(await asyncio.wait_for(q.get(), HEARTBEAT))
                    except TimeoutError:
                        if await request.is_disconnected() or await auth.authenticate(request) is None:
                            return  # gone, or its token was revoked/rotated
                        yield ": ping\n\n"
            finally:
                run.subs.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    async def fs(coro):
        try:
            return await coro
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None
        except (FileNotFoundError, NotADirectoryError) as e:
            raise HTTPException(404, str(e)) from None
        except IsADirectoryError as e:
            raise HTTPException(400, str(e)) from None

    @app.get("/api/sessions/{sid}/files")
    async def list_files(sid: str, path: str = ".", u=Depends(user)):
        return await fs((await mgr.get(u, sid)).env.list(path))

    @app.get("/api/sessions/{sid}/files/raw")
    async def download(sid: str, path: str, u=Depends(user)):
        data = await fs((await mgr.get(u, sid)).env.read_bytes(path))
        return Response(data, media_type="application/octet-stream")

    @app.put("/api/sessions/{sid}/files/raw")
    async def upload(sid: str, path: str, request: Request, u=Depends(user)):
        env = (await mgr.get(u, sid)).env
        limit = settings.get("files_max_bytes", 50 * 2**20)
        if int(request.headers.get("content-length") or 0) > limit:
            raise HTTPException(413, f"file larger than {limit} bytes")
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > limit:
                raise HTTPException(413, f"file larger than {limit} bytes")
        await fs(env.write_bytes(path, bytes(data)))
        return {"ok": True}

    return app


async def with_store(fn):
    settings = load_settings()
    store = load_plugin(settings["plugins"]["store"])(settings)
    await store.open()
    try:
        return await fn(store)
    finally:
        await store.close()


def ask_password() -> str:
    from getpass import getpass
    pw = getpass("password: ")
    if len(pw) < MIN_PASSWORD:
        raise SystemExit(f"password: at least {MIN_PASSWORD} characters")
    if getpass("again: ") != pw:
        raise SystemExit("passwords differ")
    return pw


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(prog="simp-server")
    sub = ap.add_subparsers(dest="mode", required=True)
    sd = sub.add_parser("seed", help="create a user, print its token once")
    sd.add_argument("--name", required=True)
    sd.add_argument("--password", action="store_true", help="also set a password (prompted) for web sign-in")
    sub.add_parser("passwd", help="set a user's password (prompted)").add_argument("--name", required=True)
    sub.add_parser("users", help="list users")
    sub.add_parser("revoke", help="disable a user's token").add_argument("--name", required=True)
    sub.add_parser("rotate", help="new token for a user, print it once").add_argument("--name", required=True)
    r = sub.add_parser("run", help="real server on settings host (default 127.0.0.1)")
    r.add_argument("--port", type=int, default=8766)
    r.add_argument("--fake-llm", action="store_true", help="deterministic scripted model (e2e)")
    b = sub.add_parser("backup", help="snapshot the data dir into a .tar.gz")
    b.add_argument("--to", required=True)
    b.add_argument("--keep", type=int, default=0, help="keep only the newest N backups in --to (0 = keep all)")
    sub.add_parser("pause", help="kill switch: refuse every LLM call until resume")
    sub.add_parser("resume", help="lift the kill switch")
    a = ap.parse_args()
    if a.mode in ("pause", "resume"):
        f = Path(load_settings()["data_dir"]) / "PAUSED"
        f.touch() if a.mode == "pause" else f.unlink(missing_ok=True)
        print(a.mode + "d")
        return
    if a.mode == "backup":
        print(ops.backup(Path(load_settings()["data_dir"]), Path(a.to), keep=a.keep))
    elif a.mode == "seed":
        pw = ask_password() if a.password else None

        async def seed(s):
            token = await s.add_user(a.name, password=pw)
            if err := check_sandbox(load_settings(), await s.count_users()):
                print(f"warning: {err} A running server keeps going; it refuses to start next time.", file=sys.stderr)
            return token
        print(asyncio.run(with_store(seed)))
    elif a.mode == "passwd":
        pw = ask_password()
        if not asyncio.run(with_store(lambda s: s.set_password(a.name, pw))):
            raise SystemExit(f"no user named {a.name}")
        print("password set")
    elif a.mode == "users":
        for u in asyncio.run(with_store(lambda s: s.list_users())):
            print(f"{u['name']}\t{'active' if u['active'] else 'revoked'}")
    elif a.mode == "revoke":
        if not asyncio.run(with_store(lambda s: s.revoke(a.name))):
            raise SystemExit(f"no active user named {a.name}")
        print("revoked")
    elif a.mode == "rotate":
        if (t := asyncio.run(with_store(lambda s: s.rotate_token(a.name)))) is None:
            raise SystemExit(f"no user named {a.name}")
        print(t)
    else:
        if a.fake_llm:
            from .fakellm import stream
        # open SSE streams never end on their own; without the timeout uvicorn waits forever and lifespan never closes sandboxes
        ops.setup_logging()
        settings = load_settings()
        uvicorn.run(create_app(settings, stream if a.fake_llm else ai.stream), host=settings["host"], port=a.port,
                    timeout_graceful_shutdown=SHUTDOWN_GRACE, log_config=None)
