"""Interactive REPL (pi tui model): a non-full-screen prompt_toolkit Application = [live region, input, toolbar].
Components still changing (the streaming answer, running tools) render in the live region and update in place.
Finished components are printed once into normal terminal scrollback (copy/paste and scrolling keep working)."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime

from prompt_toolkit.application import Application, run_in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import BufferControl, ConditionalContainer, FormattedTextControl, HSplit, Layout, Window
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.filters import Condition

from .. import ai
from ..agent.compaction import estimate_tokens
from ..coding import make_tools
from ..session import AgentSession
from . import JsonlStore, approval_answer, describe_call, interrupt_action, latest_session, list_sessions, route, session_dir
from .components import Chat, Notice

HELP = """Enter = send (while running: steer). ">> text" while running = follow-up.
Ctrl-C = abort run; Ctrl-C twice or Ctrl-D when idle = exit.
/new  new session   /sessions  pick a session   /history  show all messages
/compact  compact history   /exit  quit   /help  this text"""
REPLAY = 20  # messages shown on resume


class Repl:
    def __init__(self, model, args, stream_fn=None):
        self.model, self.args, self.cwd, self.stream_fn = model, args, os.getcwd(), stream_fn or ai.stream
        self.state, self.task, self.pending, self.picking = "idle", None, None, None  # pending = approval future
        self.tool = None  # (name, start time) of the running tool, for the toolbar
        self.app = None
        self.new_session(args.resume or (latest_session(self.cwd) if args.cont else None))

    def new_session(self, sid: str | None = None) -> None:
        self.sid = sid or uuid.uuid4().hex[:8]
        store = JsonlStore(session_dir(self.cwd) / f"{self.sid}.jsonl")
        self.session = AgentSession(self.model, make_tools(self.args.bash_max_timeout_s), store, stream_fn=self.stream_fn,
                                    approve=None if self.args.yes else self.approve)
        self.session.subscribe(self.on_event)
        self.chat = Chat(self.commit, self.args.thinking)

    def width(self) -> int:
        return self.app.output.get_size().columns if self.app else 80

    def commit(self, c) -> None:
        """Finished component -> scrollback, above the app (run_in_terminal keeps the order)."""
        lines = c.render(self.width())
        if not lines:
            return
        text = "\n".join(lines) + "\n"
        if self.app and self.app.is_running:
            run_in_terminal(lambda: (sys.stdout.write(text), sys.stdout.flush()), render_cli_done=False)
        else:
            sys.stdout.write(text)
            sys.stdout.flush()

    def say(self, text: str, style: str = "dim") -> None:
        self.commit(Notice(text, style))

    def live_text(self):
        lines = [ln for c in self.chat.live for ln in c.render(self.width())]
        if self.pending:
            lines += Notice(f"? {describe_call(self.pending.call)}", "bold yellow").render(self.width())
        rows = self.app.output.get_size().rows - 4 if self.app else 20
        return ANSI("\n".join(lines[-max(rows, 1):]))

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def toolbar(self) -> str:
        state = f"{self.state} ({self.tool[0]} {time.monotonic() - self.tool[1]:.0f}s)" if self.tool else self.state
        return f" {self.model.id} | session {self.sid} | ~{estimate_tokens(self.session.messages)} tokens | {state}"

    def message(self) -> str:
        return "Allow? [y/N/a] " if self.pending else ("… " if self.running else "> ")

    async def approve(self, call) -> str:
        self.pending = asyncio.get_running_loop().create_future()
        self.pending.call = call
        self.invalidate()
        try:
            return await self.pending
        finally:
            self.pending = None
            self.invalidate()

    def invalidate(self) -> None:
        if self.app:
            self.app.invalidate()

    def on_event(self, e: dict) -> None:
        t = e["type"]
        if t in ("agent_start", "turn_start"):
            self.state = "running"
        elif t == "agent_end":
            self.state = "idle"
        elif t == "compaction_start":
            self.state = "compacting"
        elif t == "compaction_end":
            self.state = "running" if self.running else "idle"
        elif t == "auto_retry_start":
            self.state = "retrying"
        elif t == "tool_execution_start":
            self.tool = (e["call"].name, time.monotonic())
        elif t == "tool_execution_end":
            self.tool = None
        self.chat.on_event(e)
        self.invalidate()

    def replay(self, everything: bool = False) -> None:
        msgs = self.session.messages
        if not everything and len(msgs) > REPLAY:
            self.say(f"({len(msgs) - REPLAY} earlier messages, /history to show all)")
            msgs = msgs[-REPLAY:]
        Chat(self.commit, self.args.thinking).replay(msgs)

    def show_sessions(self) -> None:
        self.picking = list_sessions(self.cwd)
        if not self.picking:
            self.picking = None
            return self.say("no sessions for this directory")
        for i, s in enumerate(self.picking, 1):
            when = datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
            self.say(f"{i:>3}. {when}  {s['first']!r}  ({s['count']} msgs)  {s['id']}", "")
        self.say("type a number to open (Enter = cancel)")

    def pick(self, line: str) -> None:
        choices, self.picking = self.picking, None
        if line.strip().isdigit() and 1 <= int(line) <= len(choices):
            self.new_session(choices[int(line) - 1]["id"])
            self.say(f"session {self.sid}")
            self.replay()

    def start(self, coro) -> None:
        self.task = asyncio.ensure_future(coro)

    def command(self, cmd: str) -> bool:
        """Return False to exit."""
        if cmd in ("/exit", "/quit"):
            return False
        if cmd == "/help":
            self.say(HELP)
        elif cmd == "/history":
            Chat(self.commit, self.args.thinking).replay(self.session.messages)
        elif self.running:
            self.say("busy: Ctrl-C to abort first", "yellow")
        elif cmd == "/new":
            self.new_session()
            self.say(f"new session {self.sid}")
        elif cmd == "/sessions":
            self.show_sessions()
        elif cmd == "/compact":
            self.start(self.session.compact())
        else:
            self.say(f"unknown command {cmd}; /help", "yellow")
        return True

    def submit(self, line: str) -> None:
        if self.pending:
            self.pending.set_result(approval_answer(line))
            return
        if self.picking is not None:
            return self.pick(line)
        kind, text = route(line, self.running)
        if kind == "command" and not self.command(text):
            self.app.exit()
        elif kind == "prompt":
            self.start(self.session.prompt(text))
        elif kind == "steer":
            self.session.steer(text)
            self.say("queued (steer)")
        elif kind == "follow_up":
            self.session.follow_up(text)
            self.say("queued (follow-up)")

    def ctrl_c(self) -> None:
        if self.pending:  # Ctrl-C while asking = deny + abort
            self.pending.set_result("deny")
        act = interrupt_action(self.running, self.last_ctrl_c, time.monotonic())
        if act == "abort":
            self.session.abort()
            self.say("aborting…", "yellow")
        elif act == "exit":
            self.app.exit()
        else:
            self.last_ctrl_c = time.monotonic()
            self.say("Ctrl-C again to exit")

    def build_app(self) -> Application:
        kb = KeyBindings()
        buf = Buffer(multiline=False)

        @kb.add("enter")
        def _(event):
            line, buf.text = buf.text, ""
            self.submit(line)

        @kb.add("c-c")
        def _(event):
            buf.text = ""
            self.ctrl_c()

        @kb.add("c-d")
        def _(event):
            if not buf.text:
                event.app.exit()

        live = ConditionalContainer(Window(FormattedTextControl(self.live_text), dont_extend_height=True),
                                    Condition(lambda: bool(self.chat.live or self.pending)))
        prompt = Window(BufferControl(buf, input_processors=[BeforeInput(self.message)]), height=1)
        bar = Window(FormattedTextControl(lambda: [("reverse", self.toolbar())]), height=1)
        return Application(Layout(HSplit([live, prompt, bar]), focused_element=prompt), key_bindings=kb,
                           refresh_interval=0.5, erase_when_done=True)

    async def run(self) -> int:
        self.last_ctrl_c = None
        self.say(f"simp-agent | session {self.sid} | /help")
        self.replay()
        if self.args.pick:
            self.show_sessions()
        self.app = self.build_app()
        await self.app.run_async()
        if self.running:
            self.session.abort()
            await asyncio.gather(self.task, return_exceptions=True)
        return 0


async def repl(model, args) -> int:
    return await Repl(model, args).run()
