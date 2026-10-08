"""OpenAI Chat Completions provider (any OpenAI-compatible server: vLLM, llama.cpp, Ollama, ...)."""

from __future__ import annotations

import json
import os
import uuid
from typing import AsyncIterator

from ..ai import AssistantMessage, Context, Model, TextContent, ToolCall, ToolResultMessage, UserMessage

_STOP = {"stop": "stop", "end": "stop", "length": "length", "tool_calls": "tool_use", "function_call": "tool_use"}


def to_openai(system_prompt: str, messages: list) -> list[dict]:
    out = [{"role": "system", "content": system_prompt}]
    for m in messages:
        if isinstance(m, UserMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, AssistantMessage):
            text, calls = m.text(), m.tool_calls()
            msg = {"role": "assistant", "content": text if text.strip() else (None if calls else "")}
            if calls:
                msg["tool_calls"] = [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                    for c in calls
                ]
            out.append(msg)
        elif isinstance(m, ToolResultMessage):  # one message per result, never merged
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
    return out


async def parse(chunks, compat: dict) -> AsyncIterator[dict]:
    """Turn ChatCompletionChunk objects into events. Last event is 'done' or 'error'."""
    msg, calls, finish = AssistantMessage(), list(), None  # calls: [{index, id, name, args}]
    yield {"type": "start", "partial": msg}
    async for chunk in chunks:
        usage = getattr(chunk, "usage", None)
        if not chunk.choices:
            if usage:
                msg.usage = {"input": usage.prompt_tokens or 0, "output": usage.completion_tokens or 0}
            continue
        choice = chunk.choices[0]
        usage = usage or getattr(choice, "usage", None)
        if usage:
            msg.usage = {"input": usage.prompt_tokens or 0, "output": usage.completion_tokens or 0}
        finish = choice.finish_reason or finish
        d = choice.delta
        if d is None:
            continue
        if d.content:
            if not msg.content:
                msg.content.append(TextContent(""))
            msg.content[0].text += d.content
            yield {"type": "text_delta", "delta": d.content}
        # ponytail: reasoning_content/reasoning ignored, see NOTES.md
        for tc in d.tool_calls or []:
            idx, tid = getattr(tc, "index", None), tc.id
            cur = next((c for c in calls if idx is not None and c["index"] == idx), None)
            cur = cur or next((c for c in calls if tid and c["id"] == tid), None)
            if cur is None:
                cur = {"index": idx, "id": tid or f"call_{uuid.uuid4().hex[:12]}", "name": "", "args": ""}
                calls.append(cur)
                yield {"type": "toolcall_start", "name": tc.function.name if tc.function else ""}
            if tc.function:
                cur["name"] = cur["name"] or tc.function.name or ""
                if tc.function.arguments:
                    cur["args"] += tc.function.arguments
                    yield {"type": "toolcall_delta", "delta": tc.function.arguments}
    for c in calls:
        try:
            args = json.loads(c["args"] or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            args = {"_raw": c["args"]}  # fails schema validation -> model gets an error result
        msg.content.append(ToolCall(c["id"], c["name"], args))
        yield {"type": "toolcall_end"}
    if finish is None:
        if compat.get("supports_finish_reason", True):
            msg.stop_reason, msg.error = "error", "Stream ended without finish_reason"
        else:
            msg.stop_reason = "tool_use" if calls else "stop"
    elif finish in _STOP:
        msg.stop_reason = _STOP[finish]
    else:
        msg.stop_reason, msg.error = "error", f"Provider finish_reason: {finish}"
    if msg.stop_reason == "stop" and calls:  # vLLM/Ollama send "stop" with tool calls
        msg.stop_reason = "tool_use"
    yield {"type": "error" if msg.stop_reason == "error" else "done", "message": msg}


async def stream(model: Model, context: Context, api_key: str | None = None) -> AsyncIterator[dict]:
    import openai

    try:
        key = api_key or os.environ.get("OPENAI_API_KEY") or (model.api_key_env and os.environ.get(model.api_key_env)) or "dummy"
        client = openai.AsyncOpenAI(base_url=model.base_url or os.environ.get("OPENAI_BASE_URL"), api_key=key)
        compat = model.compat
        kw = {
            "model": model.id,
            "messages": to_openai(context.system_prompt, context.messages),
            "stream": True,
            compat.get("max_tokens_field", "max_tokens"): model.max_tokens,
        }
        if compat.get("include_usage", True):
            kw["stream_options"] = {"include_usage": True}
        if context.tools:
            kw["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in context.tools
            ]
        chunks = await client.chat.completions.create(**kw)
        async for ev in parse(chunks, compat):
            yield ev
    except Exception as e:
        yield {"type": "error", "message": AssistantMessage(stop_reason="error", error=str(e))}
