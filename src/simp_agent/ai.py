"""AI layer: provider-neutral messages + stream(), which dispatches by model.api to providers/."""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from importlib import import_module
from typing import AsyncIterator, Literal


@dataclass
class TextContent:
    text: str
    type: Literal["text"] = "text"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    type: Literal["tool_call"] = "tool_call"


@dataclass
class UserMessage:
    content: str
    role: Literal["user"] = "user"


@dataclass
class AssistantMessage:
    content: list = field(default_factory=list)  # TextContent | ToolCall
    stop_reason: str = "stop"  # stop | tool_use | length | error | aborted
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0})
    error: str | None = None
    role: Literal["assistant"] = "assistant"

    def text(self) -> str:
        return "".join(c.text for c in self.content if isinstance(c, TextContent))

    def tool_calls(self) -> list[ToolCall]:
        return [c for c in self.content if isinstance(c, ToolCall)]


@dataclass
class ToolResultMessage:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
    role: Literal["tool_result"] = "tool_result"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema


@dataclass
class Context:
    system_prompt: str
    messages: list
    tools: list = field(default_factory=list)


@dataclass
class Model:
    id: str = "claude-sonnet-5-5"
    provider: str = "anthropic"
    max_tokens: int = 8192
    context_window: int = 200000
    api: str = "anthropic-messages"  # anthropic-messages | openai-completions
    base_url: str | None = None
    api_key_env: str | None = None  # env var holding the key
    compat: dict = field(default_factory=dict)  # openai: include_usage, max_tokens_field, supports_finish_reason


def transform_messages(messages: list) -> list:
    """One pass before sending: drop error/aborted assistant turns, add a result for every orphan tool call."""
    out, pending = list(), dict()  # tool_call_id -> name, waiting for a result

    def flush():
        out.extend(ToolResultMessage(i, n, "No result provided", is_error=True) for i, n in pending.items())
        pending.clear()

    for m in messages:
        if m.role == "compaction":  # history marker, never sent
            continue
        if isinstance(m, ToolResultMessage):
            pending.pop(m.tool_call_id, None)
            out.append(m)
            continue
        flush()
        if isinstance(m, AssistantMessage):
            if m.stop_reason in ("error", "aborted"):
                continue
            pending = {c.id: c.name for c in m.tool_calls()}
        out.append(m)
    flush()
    return out


_RETRYABLE = re.compile(
    r"\b(429|5\d\d)\b|overloaded|rate.?limit|bad gateway|too many requests|service unavailable|internal server error"
    r"|connection|network|timed? ?out|econnreset|stream ended",
    re.I,
)
_OVERFLOW = re.compile(
    r"prompt (is )?too long|request_too_large|exceeds the context window|maximum context length"
    r"|context[_ ]length[_ ]exceeded|too many tokens|token limit exceeded",
    re.I,
)


def is_context_overflow(error: str) -> bool:
    return bool(_OVERFLOW.search(error or ""))


def is_retryable(error: str) -> bool:
    return not is_context_overflow(error) and bool(_RETRYABLE.search(error or ""))


def to_dict(m) -> dict:
    """Any message or CompactionEntry -> JSON-safe dict."""
    return dataclasses.asdict(m)


def from_dict(d: dict):
    from .compaction import CompactionEntry

    d = dict(d)
    cls = {"user": UserMessage, "assistant": AssistantMessage, "tool_result": ToolResultMessage, "compaction": CompactionEntry}[d["role"]]
    if cls is AssistantMessage:
        d["content"] = [TextContent(**c) if c["type"] == "text" else ToolCall(**c) for c in d["content"]]
    return cls(**d)


def _builtin(module: str):
    async def fn(model, context, **opts):  # lazy import: providers import this module
        async for ev in import_module(f".providers.{module}", __package__).stream(model, context, **opts):
            yield ev

    return fn


_PROVIDERS = {"anthropic-messages": _builtin("anthropic"), "openai-completions": _builtin("openai_completions")}


def register_provider(api: str, stream_fn) -> None:
    """stream_fn(model, context, api_key=None) -> async iterator of events. Must not raise."""
    _PROVIDERS[api] = stream_fn


async def stream(model: Model, context: Context, **opts) -> AsyncIterator[dict]:
    """Yield events. Never raises: errors become an 'error' event with a final message. opts: api_key."""
    fn = _PROVIDERS.get(model.api)
    if fn is None:
        yield {"type": "error", "message": AssistantMessage(stop_reason="error", error=f"Unknown api: {model.api}")}
        return
    ctx = Context(context.system_prompt, transform_messages(context.messages), context.tools)
    async for ev in fn(model, ctx, **opts):
        yield ev
