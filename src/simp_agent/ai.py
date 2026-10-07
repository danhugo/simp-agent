"""AI layer: provider-neutral messages + stream(). One provider: Anthropic Messages API."""

from __future__ import annotations

from dataclasses import dataclass, field
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


# --- Anthropic provider -------------------------------------------------------

_STOP = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_use", "max_tokens": "length"}


def _to_anthropic(messages: list) -> list[dict]:
    out = list()
    for m in messages:
        if isinstance(m, UserMessage):
            out.append({"role": "user", "content": [{"type": "text", "text": m.content}]})
        elif isinstance(m, AssistantMessage):
            blocks = list()
            for c in m.content:
                if isinstance(c, TextContent):
                    if c.text:
                        blocks.append({"type": "text", "text": c.text})
                else:
                    blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif isinstance(m, ToolResultMessage):
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content, "is_error": m.is_error}
            # consecutive tool results must share one user message
            if out and out[-1]["role"] == "user" and out[-1]["content"][0]["type"] == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


async def stream(model: Model, context: Context) -> AsyncIterator[dict]:
    """Yield events. Never raises: errors become an 'error' event with a final message."""
    import anthropic

    msg = AssistantMessage()
    yield {"type": "start", "partial": msg}
    try:
        client = anthropic.AsyncAnthropic()
        tools = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in context.tools]
        async with client.messages.stream(
            model=model.id,
            max_tokens=model.max_tokens,
            system=context.system_prompt,
            messages=_to_anthropic(context.messages),
            tools=tools,
        ) as s:
            async for ev in s:
                if ev.type == "text":
                    yield {"type": "text_delta", "delta": ev.text}
                elif ev.type == "content_block_start" and ev.content_block.type == "tool_use":
                    yield {"type": "toolcall_start", "name": ev.content_block.name}
                elif ev.type == "input_json":
                    yield {"type": "toolcall_delta", "delta": ev.partial_json}
                elif ev.type == "content_block_stop" and ev.content_block.type == "tool_use":
                    yield {"type": "toolcall_end"}
            final = await s.get_final_message()
        for b in final.content:
            if b.type == "text":
                msg.content.append(TextContent(b.text))
            elif b.type == "tool_use":
                msg.content.append(ToolCall(b.id, b.name, dict(b.input)))
        msg.stop_reason = _STOP.get(final.stop_reason, "stop")
        msg.usage = {"input": final.usage.input_tokens, "output": final.usage.output_tokens}
        yield {"type": "done", "message": msg}
    except Exception as e:
        msg.stop_reason, msg.error = "error", str(e)
        yield {"type": "error", "message": msg}
