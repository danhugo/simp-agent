"""Chat components (pi interactive-mode model). render(width) -> ANSI lines; pure, so tests can call render(80).
Chat turns events (live) and stored messages (resume replay) into components through the SAME on_message path."""

from __future__ import annotations

from io import StringIO
from typing import Callable

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from simp_agent.ai import AssistantMessage, CompactionEntry, ToolCall as Call, ToolResultMessage, UserMessage
from . import describe_call

TOOL_LINES = 12  # tool output lines shown per call
COMPACTED = "— earlier history compacted —"


def _render(width: int, *items) -> list[str]:
    c = Console(file=StringIO(), width=width, force_terminal=True, color_system="256", highlight=False)
    for it in items:
        c.print(it)
    return c.file.getvalue().splitlines()


class UserMsg:
    def __init__(self, text: str):
        self.text = text

    def render(self, width: int) -> list[str]:
        return _render(width, Text("> " + self.text, style="bold"))


class AssistantMsg:
    def __init__(self, show_thinking: bool = True):
        self.thinking = self.text = ""
        self.error, self.done, self.show_thinking = None, False, show_thinking

    @classmethod
    def from_message(cls, m: AssistantMessage, show_thinking: bool = True) -> AssistantMsg:
        c = cls(show_thinking)
        c.thinking = "\n".join(b.thinking for b in m.content if getattr(b, "type", "") == "thinking" and b.thinking)
        c.text, c.done = m.text(), True
        if m.stop_reason in ("error", "aborted"):
            c.error = m.error or m.stop_reason
        return c

    def render(self, width: int) -> list[str]:
        items = list()
        if self.show_thinking and self.thinking.strip():
            items.append(Text(self.thinking.strip(), style="dim italic"))
        if self.text.strip():  # markdown only when finished: half-done markdown jumps around
            items.append(Markdown(self.text.replace("\n", "  \n")) if self.done else Text(self.text))  # keep line breaks
        if self.error:
            items.append(Text(self.error, style="red"))
        return _render(width, *items) if items else list()


class ToolCall:
    def __init__(self, call: Call):
        self.call, self.output, self.result = call, "", None  # result: ToolResultMessage when finished

    def render(self, width: int) -> list[str]:
        items = [Text("> " + describe_call(self.call)[:300], style="cyan")]
        r = self.result
        if r and r.is_error:
            items.append(Text("  ! " + r.content[:300], style="red"))
        else:
            lines = (r.content if r else self.output).splitlines()
            items += [Text("  " + ln[:200], style="dim") for ln in lines[:TOOL_LINES]]
            if len(lines) > TOOL_LINES:
                items.append(Text(f"  … ({len(lines) - TOOL_LINES} more lines)", style="dim"))
        return _render(width, *items)


class Notice:
    def __init__(self, text: str, style: str = "dim"):
        self.text, self.style = text, style

    def render(self, width: int) -> list[str]:
        return _render(width, Text(self.text, style=self.style))


class Chat:
    """live = components still changing (shown above the input). commit(component) = finished, goes to scrollback."""

    def __init__(self, commit: Callable, show_thinking: bool = True):
        self.commit, self.show_thinking = commit, show_thinking
        self.live = list()
        self.streaming: AssistantMsg | None = None
        self.tools = dict()  # call id -> ToolCall waiting for its result

    def _done(self, c) -> None:
        if c in self.live:
            self.live.remove(c)
        self.commit(c)

    def on_message(self, m) -> None:
        """One finished message. Used by live message_end AND by resume replay."""
        if isinstance(m, UserMessage):
            self._done(UserMsg(m.content))
        elif isinstance(m, AssistantMessage):
            if self.streaming in self.live:
                self.live.remove(self.streaming)
            self.streaming = None
            c = AssistantMsg.from_message(m, self.show_thinking)
            if c.render(80):
                self._done(c)
            for call in m.tool_calls():  # wait in the live region for their result
                self.tools[call.id] = ToolCall(call)
                self.live.append(self.tools[call.id])
        elif isinstance(m, ToolResultMessage):
            c = self.tools.pop(m.tool_call_id, None) or ToolCall(Call(m.tool_call_id, m.tool_name, {}))
            c.result = m
            self._done(c)
        elif isinstance(m, CompactionEntry):
            self._done(Notice(COMPACTED))

    def on_event(self, e: dict) -> None:
        t = e["type"]
        if t == "message_end":
            self.on_message(e["message"])
        elif t == "message_update" and e["event"]["type"] in ("text_delta", "thinking_delta"):
            if self.streaming is None:
                self.streaming = AssistantMsg(self.show_thinking)
                self.live.append(self.streaming)
            kind = "text" if e["event"]["type"] == "text_delta" else "thinking"
            setattr(self.streaming, kind, getattr(self.streaming, kind) + e["event"]["delta"])
        elif t == "tool_execution_update" and e["call"].id in self.tools:
            self.tools[e["call"].id].output += e["text"]
        elif t == "compaction_start":
            self.commit(Notice("compacting…"))
        elif t == "compaction_end":
            self.commit(Notice(f"compacted: {e['tokens_before']} -> {e['tokens_after']} tokens {e['error'] or ''}"))
        elif t == "auto_retry_start":
            self.commit(Notice(f"retry {e['attempt']}/{e['max_attempts']} in {e['delay']}s: {e['error'][:150]}", "yellow"))

    def replay(self, messages: list) -> None:
        for m in messages:
            self.on_message(m)
        self.live.clear()  # unanswered tool calls of an old run: nothing more will come
        self.tools.clear()
