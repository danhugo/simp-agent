"""Anthropic Messages API provider."""

from __future__ import annotations

from typing import AsyncIterator

from .. import AssistantMessage, Context, Model, TextContent, ThinkingContent, ToolCall, ToolResultMessage, UserMessage

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
                elif isinstance(c, ThinkingContent):
                    if c.redacted:
                        blocks.append({"type": "redacted_thinking", "data": c.signature})
                    elif c.signature:
                        blocks.append({"type": "thinking", "thinking": c.thinking, "signature": c.signature})
                    elif c.thinking.strip():  # unsigned (e.g. aborted) cannot be replayed as thinking
                        blocks.append({"type": "text", "text": c.thinking})
                else:
                    blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif isinstance(m, ToolResultMessage):
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content, "is_error": m.is_error}
            out.append({"role": "user", "content": [block]})
    merged = list()  # consecutive same-role turns become one (Anthropic needs user/assistant alternation)
    for t in out:
        if merged and merged[-1]["role"] == t["role"]:
            merged[-1]["content"].extend(t["content"])
        else:
            merged.append(t)
    return merged


def thinking_params(model: Model) -> dict:
    """pi :1233-1257. compat.reasoning_effort -> adaptive thinking + effort; compat.thinking_budget -> budget (older models)."""
    c = model.compat
    if c.get("thinking_budget"):
        return {"thinking": {"type": "enabled", "budget_tokens": c["thinking_budget"]},
                "extra_headers": {"anthropic-beta": "interleaved-thinking-2025-05-14"}}
    if c.get("reasoning_effort") and c["reasoning_effort"] != "none":
        return {"thinking": {"type": "adaptive"}, "extra_body": {"output_config": {"effort": c["reasoning_effort"]}}}
    return {}


def _block(b):
    if b.type == "text":
        return TextContent(b.text)
    if b.type == "thinking":
        return ThinkingContent(b.thinking, b.signature)
    if b.type == "redacted_thinking":
        return ThinkingContent("", b.data, redacted=True)
    if b.type == "tool_use":
        return ToolCall(b.id, b.name, dict(b.input))


async def parse(s, msg: AssistantMessage) -> AsyncIterator[dict]:
    """SDK stream events -> our events. Partial text/thinking kept on msg (for abort)."""
    async for ev in s:
        if ev.type == "content_block_start":
            b = ev.content_block
            if b.type == "text":
                msg.content.append(TextContent(""))
            elif b.type in ("thinking", "redacted_thinking"):
                msg.content.append(_block(b) if b.type == "redacted_thinking" else ThinkingContent(""))
                yield {"type": "thinking_start"}
            elif b.type == "tool_use":
                yield {"type": "toolcall_start", "name": b.name}
        elif ev.type == "text" and msg.content and isinstance(msg.content[-1], TextContent):
            msg.content[-1].text += ev.text
            yield {"type": "text_delta", "delta": ev.text}
        elif ev.type == "thinking" and msg.content and isinstance(msg.content[-1], ThinkingContent):
            msg.content[-1].thinking += ev.thinking
            yield {"type": "thinking_delta", "delta": ev.thinking}
        elif ev.type == "signature" and msg.content and isinstance(msg.content[-1], ThinkingContent):
            msg.content[-1].signature = (msg.content[-1].signature or "") + ev.signature
        elif ev.type == "input_json":
            yield {"type": "toolcall_delta", "delta": ev.partial_json}
        elif ev.type == "content_block_stop":
            if ev.content_block.type == "tool_use":
                yield {"type": "toolcall_end"}
            elif ev.content_block.type in ("thinking", "redacted_thinking"):
                yield {"type": "thinking_end"}


async def stream(model: Model, context: Context, api_key: str | None = None) -> AsyncIterator[dict]:
    """Yield events. Never raises: errors become an 'error' event with a final message."""
    import anthropic

    msg = AssistantMessage()
    yield {"type": "start", "partial": msg}
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, base_url=model.base_url)  # None -> SDK reads env
        tools = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in context.tools]
        async with client.messages.stream(
            model=model.id,
            max_tokens=model.max_tokens,
            system=context.system_prompt,
            messages=_to_anthropic(context.messages),
            tools=tools,
            **thinking_params(model),  # no temperature is sent, so nothing to drop with thinking on
        ) as s:
            async for ev in parse(s, msg):
                yield ev
            final = await s.get_final_message()
        msg.content = [b for b in map(_block, final.content) if b]
        msg.stop_reason = _STOP.get(final.stop_reason, "stop")
        msg.usage = {"input": final.usage.input_tokens, "output": final.usage.output_tokens}
        yield {"type": "done", "message": msg}
    except Exception as e:
        msg.stop_reason, msg.error = "error", str(e)
        yield {"type": "error", "message": msg}
