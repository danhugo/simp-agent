"""Interactive REPL: prompt_toolkit input line at the bottom, output streams above it (rich for colors)."""

from __future__ import annotations

import asyncio
import os
import time
import uuid

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markup import escape

from ..agent.compaction import estimate_tokens
from ..session import AgentSession
from . import JsonlStore, approval_answer, describe_call, interrupt_action, latest_session, route, session_dir

HELP = """Enter = send (while running: steer). ">> text" while running = follow-up.
Ctrl-C = abort run; Ctrl-C twice or Ctrl-D when idle = exit.
/new  new session   /compact  compact history   /exit  quit   /help  this text"""
TOOL_LINES = 12  # tool output lines shown per call


class Repl:
    def __init__(self, model, args):
        self.model, self.args, self.cwd = model, args, os.getcwd()
        self.console = Console(highlight=False)
        self.state, self.task, self.pending = "idle", None, None  # pending = approval future
        self.shown = {}  # tool call id -> lines shown
        sid = args.resume or (latest_session(self.cwd) if args.cont else None)
        self.new_session(sid)

    def new_session(self, sid: str | None = None) -> None:
        self.sid = sid or uuid.uuid4().hex[:8]
        self.session = AgentSession(self.model, store=JsonlStore(session_dir(self.cwd) / f"{self.sid}.jsonl"),
                                    approve=None if self.args.yes else self.approve)
        self.session.subscribe(self.on_event)

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def toolbar(self) -> str:
        return f" {self.model.id} | session {self.sid} | ~{estimate_tokens(self.session.messages)} tokens | {self.state}"

    def message(self) -> str:
        return "Allow? [y/N/a] " if self.pending else ("… " if self.running else "> ")

    async def approve(self, call) -> str:
        self.console.print(f"[bold yellow]? {escape(describe_call(call))}[/]")
        self.pending = asyncio.get_running_loop().create_future()
        self.ps.app.invalidate()
        try:
            return await self.pending
        finally:
            self.pending = None
            self.ps.app.invalidate()

    def on_event(self, e: dict) -> None:
        t, out = e["type"], self.console
        if t in ("agent_start", "turn_start"):
            self.state = "running"
        elif t == "agent_end":
            self.state = "idle"
        elif t == "compaction_start":
            self.state = "compacting"
            out.print("[dim]compacting…[/]")
        elif t == "compaction_end":
            self.state = "running" if self.running else "idle"
            out.print(f"[dim]compacted: {e['tokens_before']} -> {e['tokens_after']} tokens {e['error'] or ''}[/]")
        elif t == "auto_retry_start":
            self.state = "retrying"
            out.print(f"[yellow]retry {e['attempt']}/{e['max_attempts']} in {e['delay']}s: {escape(e['error'][:150])}[/]")
        elif t == "message_update" and e["event"]["type"] == "text_delta":
            out.print(e["event"]["delta"], end="", markup=False)
        elif t == "message_end" and e["message"].role == "assistant":
            m = e["message"]
            if m.text():
                out.print()
            if m.stop_reason in ("error", "aborted"):
                out.print(f"[red]{escape(m.error or m.stop_reason)}[/]")
        elif t == "tool_execution_start":
            out.print(f"[cyan]> {escape(describe_call(e['call'])[:300])}[/]")
        elif t == "tool_execution_update":
            self.show_output(e["call"].id, e["text"])
        elif t == "tool_execution_end":
            r = e["result"]
            if r.is_error:
                out.print(f"[red]  ! {escape(r.content[:300])}[/]")
            elif e["call"].id not in self.shown:
                self.show_output(e["call"].id, r.content)
            self.shown.pop(e["call"].id, None)
        self.ps.app.invalidate()

    def show_output(self, call_id: str, text: str) -> None:
        n = self.shown.get(call_id, 0)
        for line in text.splitlines():
            n += 1
            if n <= TOOL_LINES:
                self.console.print(f"[dim]  {escape(line[:200])}[/]")
            elif n == TOOL_LINES + 1:
                self.console.print("[dim]  …[/]")
        self.shown[call_id] = n

    def start(self, coro) -> None:
        self.task = asyncio.ensure_future(coro)

    async def command(self, cmd: str) -> bool:
        """Return False to exit."""
        if cmd in ("/exit", "/quit"):
            return False
        if self.running:
            self.console.print("[yellow]busy: Ctrl-C to abort first[/]")
        elif cmd == "/new":
            self.new_session()
            self.console.print(f"[dim]new session {self.sid}[/]")
        elif cmd == "/compact":
            self.start(self.session.compact())
        elif cmd == "/help":
            self.console.print(HELP, markup=False)
        else:
            self.console.print(f"[yellow]unknown command {escape(cmd)}; /help[/]")
        return True

    async def run(self) -> int:
        self.ps = PromptSession(bottom_toolbar=self.toolbar, refresh_interval=0.5)
        last_ctrl_c = None
        with patch_stdout(raw=True):
            self.console = Console(highlight=False, force_terminal=True)  # writes through patch_stdout
            self.console.print(f"[dim]simp-agent | session {self.sid} | /help[/]")
            while True:
                try:
                    line = await self.ps.prompt_async(self.message)
                except KeyboardInterrupt:
                    if self.pending:  # Ctrl-C while asking = deny + abort
                        self.pending.set_result("deny")
                    act = interrupt_action(self.running, last_ctrl_c, time.monotonic())
                    if act == "abort":
                        self.session.abort()
                        self.console.print("[yellow]aborting…[/]")
                    elif act == "exit":
                        break
                    else:
                        last_ctrl_c = time.monotonic()
                        self.console.print("[dim]Ctrl-C again to exit[/]")
                    continue
                except EOFError:
                    break
                if self.pending:
                    self.pending.set_result(approval_answer(line))
                    continue
                kind, text = route(line, self.running)
                if kind == "command" and not await self.command(text):
                    break
                elif kind == "prompt":
                    self.start(self.session.prompt(text))
                elif kind == "steer":
                    self.session.steer(text)
                    self.console.print("[dim]queued (steer)[/]")
                elif kind == "follow_up":
                    self.session.follow_up(text)
                    self.console.print("[dim]queued (follow-up)[/]")
            if self.running:
                self.session.abort()
                await asyncio.gather(self.task, return_exceptions=True)
        return 0


async def repl(model, args) -> int:
    return await Repl(model, args).run()
