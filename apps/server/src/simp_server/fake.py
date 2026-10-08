"""Fake replay server: the real HTTP API (same as T2), but runs a recorded script instead of an LLM.

GET  /api/sessions                      -> [SessionInfo]
POST /api/sessions                      -> SessionInfo
POST /api/hello {protocol_version}      -> Hello | 400 HelloError
GET  /api/sessions/{id}/events          SSE; resume with Last-Event-ID header or ?after=<seq>
POST /api/sessions/{id}/commands        Command body
GET  /api/profiles                      -> [str] (web new-session picker)
GET/PUT /api/sessions/{id}/files[/raw]  in-memory workspace (flat, no dirs)
"""

from __future__ import annotations

import asyncio
import itertools
import json

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from . import protocol as p

# Recorded run. Text is streamed in small chunks to look like a model.
SCRIPT = [
    ("thinking", "The user wants the files listed. I will run ls."),
    ("text", "Let me look at the directory."),
    ("tool_call", {"id": "call_1", "name": "bash", "arguments": {"command": "ls -la"}}),
    ("tool_output", ("call_1", "total 3\ndrwxr-xr-x  README.md\ndrwxr-xr-x  src\n")),
    ("final", "There are two entries: README.md and src."),
]


class Hub:
    """One session: durable log + seq, run state, in-flight buffers, live subscribers."""

    def __init__(self, sid: str, delay: float):
        self.info = p.SessionInfo(id=sid)
        self.delay = delay
        self.log = []
        self.inflight = p.InFlight()
        self.pending: p.PendingApproval | None = None
        self.subs = set()
        self.task: asyncio.Task | None = None
        self.answer: asyncio.Future | None = None
        self.queued = []
        self.msg_ids = itertools.count(1)
        self.files = {"README.md": b"# demo workspace\n"}

    @property
    def state(self) -> str:
        return self.info.run_state

    def _send(self, ev: dict) -> None:
        p.server_event.validate_python(ev)  # never put an off-schema frame on the wire
        for q in self.subs:
            q.put_nowait(ev)

    def durable(self, cls, **kw) -> None:
        ev = cls(seq=len(self.log) + 1, **kw).model_dump()
        self.log.append(ev)
        self._send(ev)

    def live(self, ev) -> None:
        self._send(ev.model_dump())

    def set_state(self, s: str) -> None:
        p.check_transition(self.state, s)
        self.info.run_state = s
        self.durable(p.RunState, state=s)

    def snapshot(self) -> dict:
        return p.Snapshot(last_seq=len(self.log), run_state=self.state, in_flight=self.inflight,
                          pending_approval=self.pending).model_dump()

    def subscribe(self, after: int) -> tuple[list[dict], asyncio.Queue]:
        """Missed durable events, then a snapshot, then live. No await here, so nothing slips in between."""
        q = asyncio.Queue()
        self.subs.add(q)
        return [*self.log[after:], self.snapshot()], q

    async def _stream(self, kind: str, text: str, key: str) -> None:
        for off in range(0, len(text), 4):
            chunk = text[off:off + 4]
            if kind == "tool_output":
                self.inflight.tool_outputs[key] = self.inflight.tool_outputs.get(key, "") + chunk
                self.live(p.ToolOutput(call_id=key, offset=off, delta=chunk))
            else:
                setattr(self.inflight, kind, getattr(self.inflight, kind) + chunk)
                cls = p.TextDelta if kind == "text" else p.ThinkingDelta
                self.live(cls(msg_id=key, offset=off, delta=chunk))
            await asyncio.sleep(self.delay)

    def _finish_message(self, calls: list) -> None:
        f = self.inflight
        self.durable(p.AssistantMessage, msg_id=f.msg_id, thinking=f.thinking, text=f.text, tool_calls=calls,
                     usage=p.Usage(input=120, output=40), stop_reason="tool_use" if calls else "stop")
        self.inflight = p.InFlight(tool_outputs=f.tool_outputs)

    def start(self, text: str) -> None:
        """Sync on purpose: state is `running` before the next command can arrive."""
        self.durable(p.UserMessage, text=text)
        self.set_state("running")
        self.task = asyncio.create_task(self.run())

    async def run(self) -> None:
        try:
            self.inflight = p.InFlight(msg_id=f"m{next(self.msg_ids)}")
            for kind, arg in SCRIPT:
                if kind in ("thinking", "text"):
                    await self._stream(kind, arg, self.inflight.msg_id)
                elif kind == "tool_call":
                    call = p.ToolCall(**arg)
                    self._finish_message([call])
                    if not await self._approve(call):
                        self.durable(p.ToolResult, call_id=call.id, tool=call.name, content="denied by user", is_error=True)
                        break
                elif kind == "tool_output":
                    cid, out = arg
                    await self._stream("tool_output", out, cid)
                    self.durable(p.ToolResult, call_id=cid, tool="bash", content=self.inflight.tool_outputs.pop(cid))
                elif kind == "final":
                    self.inflight.msg_id = f"m{next(self.msg_ids)}"
                    await self._stream("text", arg, self.inflight.msg_id)
                    self._finish_message([])
            self.inflight = p.InFlight()
            self.set_state("idle")
        except asyncio.CancelledError:
            self.inflight = p.InFlight()
            if self.pending:
                self.durable(p.ApprovalResolved, call_id=self.pending.call_id, decision="aborted")
                self.pending = None
            self.set_state("idle")
            self.durable(p.Notice, level="warning", text="run aborted")
            return
        if self.queued:  # follow-ups queued while busy start the next run
            self.start(self.queued.pop(0))

    async def _approve(self, call: p.ToolCall) -> bool:
        self.pending = p.PendingApproval(call_id=call.id, tool=call.name, args=call.arguments)
        self.durable(p.ApprovalRequest, call_id=call.id, tool=call.name, args=call.arguments)
        self.set_state("waiting_approval")
        self.answer = asyncio.get_running_loop().create_future()
        decision = await self.answer
        self.pending = None
        self.durable(p.ApprovalResolved, call_id=call.id, decision=decision)
        self.set_state("running")
        return decision != "deny"

    def command(self, c) -> None:
        busy = self.state in ("running", "waiting_approval", "aborting")
        if isinstance(c, (p.Prompt, p.FollowUp)):
            if busy:
                self.queued.append(c.text)
            else:
                self.start(c.text)
        elif isinstance(c, p.Steer):
            self.durable(p.Notice, text=f"steer noted (fake server ignores it): {c.text}")
        elif isinstance(c, p.Abort):
            if busy and self.task and self.state != "aborting":
                self.queued.clear()
                self.set_state("aborting")
                self.task.cancel()
        elif isinstance(c, p.Approve):
            if not self.pending or self.pending.call_id != c.call_id:
                raise HTTPException(409, "no pending approval with that call_id")
            self.answer.set_result(c.decision)


def sse(ev: dict) -> str:
    head = f"id: {ev['seq']}\n" if "seq" in ev else ""
    return f"{head}event: {ev['type']}\ndata: {json.dumps(ev)}\n\n"


def create_app(delay: float = 0.05) -> FastAPI:
    app = FastAPI()
    hubs = {}
    ids = itertools.count(1)

    def hub(sid: str) -> Hub:
        if sid not in hubs:
            raise HTTPException(404, "no such session")
        return hubs[sid]

    @app.post("/api/hello")
    def hello(h: p.Hello):
        r = p.check_hello(h)
        return JSONResponse(r.model_dump(), status_code=400 if isinstance(r, p.HelloError) else 200)

    @app.get("/api/sessions")
    def list_sessions() -> list[p.SessionInfo]:
        return [h.info for h in hubs.values()]

    @app.post("/api/sessions")
    def new_session() -> p.SessionInfo:
        sid = f"s{next(ids)}"
        hubs[sid] = Hub(sid, delay)
        return hubs[sid].info

    @app.get("/api/profiles")
    def profiles() -> list[str]:
        return ["default", "luna"]

    @app.get("/api/sessions/{sid}/files")
    def list_files(sid: str, path: str = ".") -> list[dict]:
        return [{"name": n, "is_dir": False, "size": len(b)} for n, b in sorted(hub(sid).files.items())]

    @app.get("/api/sessions/{sid}/files/raw")
    def read_file(sid: str, path: str):
        if path not in hub(sid).files:
            raise HTTPException(404, "no such file")
        return Response(hub(sid).files[path], media_type="application/octet-stream")

    @app.put("/api/sessions/{sid}/files/raw")
    async def write_file(sid: str, path: str, request: Request):
        hub(sid).files[path] = await request.body()
        return {"ok": True}

    @app.post("/api/sessions/{sid}/commands")
    async def post_command(sid: str, request: Request):
        try:
            c = p.command.validate_python(await request.json())
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False)) from None
        hub(sid).command(c)
        return {"ok": True}

    @app.get("/api/sessions/{sid}/events")
    async def events(sid: str, after: int | None = None, last_event_id: str | None = Header(None)):
        h = hub(sid)
        first, q = h.subscribe(after if after is not None else int(last_event_id or 0))

        async def gen():
            try:
                for ev in first:
                    yield sse(ev)
                while True:
                    yield sse(await q.get())
            finally:
                h.subs.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(prog="simp-server")
    ap.add_argument("mode", choices=["fake"])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--delay", type=float, default=0.05, help="seconds between streamed chunks")
    a = ap.parse_args()
    uvicorn.run(create_app(a.delay), host="127.0.0.1", port=a.port)
