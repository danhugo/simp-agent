"""Real server: same HTTP API as fake.py, backed by AgentSession + SQLite. Plugin slots come from settings.toml.

GET/POST /api/sessions, GET /api/sessions/{id}/events (SSE), POST /api/sessions/{id}/commands,
GET /api/sessions/{id}/files?path=, GET|PUT /api/sessions/{id}/files/raw?path=   (all need Authorization: Bearer)
"""

from __future__ import annotations

import asyncio
import os
import tomllib
import uuid
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from typing import Protocol

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from simp_agent import ai
from simp_agent.agent.env import ExecutionEnv, LocalEnv
from simp_agent.ai import Model, ThinkingContent, from_dict, to_dict
from simp_agent.plugins.redact_secrets import RedactSecrets
from simp_agent.session import AgentSession

from . import protocol as p
from .fake import sse

HOME = Path(os.environ.get("SIMP_SERVER_HOME", Path.home() / ".simp-server"))
DEFAULT_PLUGINS = {"sandbox": "simp_server.server:LocalSandbox", "store": "simp_server.store:SqliteStore",
                   "auth": "simp_server.server:StaticTokenAuth"}
ALLOWED_HOSTS = {"localhost", "127.0.0.1"}


# ---- plugin slots ---------------------------------------------------------------------------------------------------

class Sandbox(Protocol):
    async def open(self, session_id: str) -> ExecutionEnv: ...

    async def close(self, session_id: str) -> None: ...


class Store(Protocol):  # see store.SqliteStore for the full method list
    async def open(self) -> None: ...


class Auth(Protocol):
    async def authenticate(self, request: Request) -> dict | None: ...  # user {id, name} or None


class LocalSandbox:
    """A per-session dir under the data dir; LocalEnv rooted there. Not isolation: DockerSandbox replaces it."""

    def __init__(self, settings: dict):
        self.root = Path(settings["data_dir"]) / "sandboxes"

    async def open(self, session_id: str) -> LocalEnv:
        d = self.root / session_id
        d.mkdir(parents=True, exist_ok=True)
        return LocalEnv(str(d.resolve()))

    async def close(self, session_id: str) -> None:
        pass


class StaticTokenAuth:
    def __init__(self, store):
        self.store = store

    async def authenticate(self, request: Request) -> dict | None:
        h = request.headers.get("authorization", "")
        return await self.store.user_by_token(h[7:]) if h.startswith("Bearer ") else None


def load_plugin(path: str):
    mod, _, name = path.partition(":")
    return getattr(import_module(mod), name)


# ---- settings + keys ------------------------------------------------------------------------------------------------

def load_settings(home: Path = HOME) -> dict:
    f = home / "settings.toml"
    s = tomllib.loads(f.read_text()) if f.exists() else dict()
    s.setdefault("data_dir", str(home))
    s["data_dir"] = str(Path(s["data_dir"]).expanduser())
    docker = {"sandbox": "simp_server.sandboxes.docker:DockerSandbox"} if os.environ.get("SIMP_SANDBOX") == "docker" else {}
    s["plugins"] = {**DEFAULT_PLUGINS, **docker, **s.get("plugins", dict())}
    s.setdefault("profiles", dict())
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
    return keys


def build_model(pr: dict) -> Model:
    api = pr.get("api", "anthropic-messages")
    kw = {"id": pr["model"], "api": api, "provider": "openai" if api.startswith("openai") else "anthropic",
          "base_url": pr.get("base_url"), "api_key_env": pr.get("api_key_env"), "compat": dict(pr.get("compat", dict()))}
    kw.update({k: pr[k] for k in ("max_tokens", "context_window") if k in pr})
    if api.startswith("openai"):
        kw["compat"].setdefault("include_usage", True)
    return Model(**kw)


# ---- one conversation -----------------------------------------------------------------------------------------------

class Run:
    """AgentSession + durable protocol log + in-flight buffers. Subscribers only get per-connection queues."""

    def __init__(self, mgr: "SessionManager", row: dict, env: ExecutionEnv, entries: list[dict]):
        self.mgr, self.sid, self.user_id, self.env = mgr, row["id"], row["user_id"], env
        self.info = p.SessionInfo(id=row["id"], title=row["title"] or "")
        self.log = [e["data"] for e in entries if e["type"] != "msg"]  # ponytail: whole log in memory
        self.seq = entries[-1]["seq"] if entries else 0
        self.inflight, self.pending, self.answer = p.InFlight(), None, None
        self.subs, self.task = set(), None
        self.model = build_model(mgr.settings["profiles"][row["profile"]])
        self.session = AgentSession(
            self.model, store=self, env=env, cwd=getattr(env, "root", None) or "/", stream_fn=mgr.stream_fn,
            get_api_key=mgr.api_key_for(self.model), approve=self.approve,
            messages=[from_dict(e["data"]) for e in entries if e["type"] == "msg"],
            plugins=[RedactSecrets()], plugin_config={"redact_secrets": {"secrets": list(mgr.keys.values())}})
        self.session.subscribe(self.on_event)

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
        for q in self.subs:
            q.put_nowait(ev)

    async def durable(self, cls, **kw) -> None:
        self.seq += 1
        ev = cls(seq=self.seq, **kw).model_dump()
        self.log.append(ev)
        self._send(ev)
        await self.mgr.store.add_entry(self.user_id, self.sid, ev["seq"], ev["type"], ev)

    async def set_state(self, s: str) -> None:
        p.check_transition(self.state, s)
        self.info.run_state = s
        await self.durable(p.RunState, state=s)

    def subscribe(self, after: int) -> tuple[list[dict], asyncio.Queue]:
        """Missed durable events, then a snapshot, then live. No await here, so nothing slips in between."""
        q = asyncio.Queue()
        self.subs.add(q)
        snap = p.Snapshot(last_seq=self.seq, run_state=self.state, in_flight=self.inflight, pending_approval=self.pending)
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
                await self.mgr.store.add_usage(self.user_id, self.sid, self.model.id, **u)
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
        await self.durable(p.ApprovalRequest, call_id=call.id, tool=call.name, args=call.arguments)
        await self.set_state("waiting_approval")
        try:
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

    async def start(self, text: str) -> None:
        await self.set_state("running")
        self.task = asyncio.create_task(self._run(text))

    async def _run(self, text: str) -> None:
        try:
            await self.session.prompt(text)
        except Exception as e:  # never leave the session stuck in running
            await self.durable(p.Notice, level="error", text=f"{type(e).__name__}: {e}")
        self.inflight = p.InFlight()
        agent = self.session.agent
        if self.state == "aborting":
            agent.clear_queues()
            await self.set_state("idle")
            await self.durable(p.Notice, level="warning", text="run aborted")
            return
        last = agent.messages[-1] if agent.messages else None
        await self.set_state("error" if last and last.role == "assistant" and last.stop_reason == "error" else "idle")
        if agent.follow_ups:  # came in after the loop decided to stop
            await self.start(agent.follow_ups.pop(0).content)

    async def command(self, c) -> None:
        if isinstance(c, (p.Prompt, p.FollowUp, p.Steer)):
            if not self.busy:
                await self.start(c.text)
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


class SessionManager:
    def __init__(self, settings: dict, store, sandbox, stream_fn):
        self.settings, self.store, self.sandbox, self.stream_fn = settings, store, sandbox, stream_fn
        self.keys = take_keys(settings)
        self.runs: dict[str, Run] = dict()
        self.lock = asyncio.Lock()  # ponytail: one lock for loading runs; per-session locks if it ever matters

    def api_key_for(self, model: Model):
        name = model.api_key_env or ("OPENAI_API_KEY" if model.api.startswith("openai") else "ANTHROPIC_API_KEY")
        return lambda provider: self.keys.get(name)

    async def get(self, user: dict, sid: str) -> Run:
        row = await self.store.get_session(user["id"], sid)
        if row is None:
            raise HTTPException(404, "no such session")
        async with self.lock:
            if sid not in self.runs:
                env = await self.sandbox.open(row["sandbox_ref"])
                self.runs[sid] = Run(self, row, env, await self.store.entries(user["id"], sid))
        return self.runs[sid]

    def info(self, row: dict) -> p.SessionInfo:
        r = self.runs.get(row["id"])
        return p.SessionInfo(id=row["id"], title=row["title"] or "", run_state=r.state if r else "idle")


# ---- app ------------------------------------------------------------------------------------------------------------

def create_app(settings: dict, stream_fn=ai.stream) -> FastAPI:
    pl = settings["plugins"]
    store = load_plugin(pl["store"])(settings)
    sandbox = load_plugin(pl["sandbox"])(settings)
    auth = load_plugin(pl["auth"])(store)
    mgr = SessionManager(settings, store, sandbox, stream_fn)

    @asynccontextmanager
    async def lifespan(app):
        await store.open()
        yield
        for sid in list(mgr.runs):
            await sandbox.close(sid)
        await store.close()

    app = FastAPI(lifespan=lifespan)
    app.state.mgr = mgr

    @app.middleware("http")
    async def host_guard(request: Request, call_next):  # DNS rebinding: only our own host names
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "bad host"}, status_code=403)
        return await call_next(request)

    async def user(request: Request) -> dict:
        u = await auth.authenticate(request)
        if u is None:
            raise HTTPException(401, "bad token")
        return u

    @app.post("/api/hello")
    def hello(h: p.Hello):
        r = p.check_hello(h)
        return JSONResponse(r.model_dump(), status_code=400 if isinstance(r, p.HelloError) else 200)

    @app.get("/api/profiles")
    async def profiles(u=Depends(user)) -> list[str]:
        return list(settings["profiles"])

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
                while True:
                    yield sse(await q.get())
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
        await fs((await mgr.get(u, sid)).env.write_bytes(path, await request.body()))
        return {"ok": True}

    return app


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(prog="simp-server")
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("seed", help="create a user, print its token once").add_argument("--name", required=True)
    r = sub.add_parser("run", help="real server on 127.0.0.1")
    r.add_argument("--port", type=int, default=8766)
    r.add_argument("--fake-llm", action="store_true", help="deterministic scripted model (e2e)")
    a = ap.parse_args()
    if a.mode == "seed":
        async def seed():
            settings = load_settings()
            store = load_plugin(settings["plugins"]["store"])(settings)
            await store.open()
            print(await store.add_user(a.name))
            await store.close()
        asyncio.run(seed())
    else:
        if a.fake_llm:
            from .fakellm import stream
        uvicorn.run(create_app(load_settings(), stream if a.fake_llm else ai.stream), host="127.0.0.1", port=a.port)
