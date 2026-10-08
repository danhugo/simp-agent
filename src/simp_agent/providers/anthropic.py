"""Anthropic Messages API provider."""

from __future__ import annotations

from typing import AsyncIterator

from ..ai import AssistantMessage, Context, Model, TextContent, ToolCall, ToolResultMessage, UserMessage

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
            out.append({"role": "user", "content": [block]})
    merged = list()  # consecutive same-role turns become one (Anthropic needs user/assistant alternation)
    for t in out:
        if merged and merged[-1]["role"] == t["role"]:
            merged[-1]["content"].extend(t["content"])
        else:
            merged.append(t)
    return merged


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
                    if not msg.content:
                        msg.content.append(TextContent(""))
                    msg.content[-1].text += ev.text  # partial text, kept if aborted
                    yield {"type": "text_delta", "delta": ev.text}
                elif ev.type == "content_block_start" and ev.content_block.type == "tool_use":
                    yield {"type": "toolcall_start", "name": ev.content_block.name}
                elif ev.type == "input_json":
                    yield {"type": "toolcall_delta", "delta": ev.partial_json}
                elif ev.type == "content_block_stop" and ev.content_block.type == "tool_use":
                    yield {"type": "toolcall_end"}
            final = await s.get_final_message()
        msg.content = list()
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
