"""OpenAI Responses API provider (pi openai-responses.ts + openai-responses-shared.ts). store=false: reasoning is
replayed from the encrypted item kept in ThinkingContent.signature, never via previous_response_id."""

from __future__ import annotations

import hashlib
import json
import re
from typing import AsyncIterator

from .. import AssistantMessage, Context, Model, TextContent, ThinkingContent, ToolCall, ToolResultMessage, UserMessage


def _reasoning(model: Model) -> str | None:
    e = model.compat.get("reasoning_effort")
    return e if e and e != "none" else None


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _id_part(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)[:64].rstrip("_")


def to_input(model: Model, system_prompt: str, messages: list) -> list[dict]:
    out = [{"role": "developer" if _reasoning(model) else "system", "content": system_prompt}]
    for i, m in enumerate(messages):
        if isinstance(m, UserMessage):
            out.append({"role": "user", "content": [{"type": "input_text", "text": m.content}]})
        elif isinstance(m, AssistantMessage):
            same_api = (m.provider, m.api) == (model.provider, model.api)
            other_model = same_api and m.model != model.id
            n_text = 0
            for c in m.content:
                if isinstance(c, ThinkingContent):
                    if c.signature:
                        out.append(json.loads(c.signature))
                elif isinstance(c, TextContent):
                    sig = json.loads(c.signature) if c.signature else {}
                    mid = sig.get("id") or (f"msg_pi_{i}" if n_text == 0 else f"msg_pi_{i}_{n_text}")
                    n_text += 1
                    if len(mid) > 64:
                        mid = f"msg_{_hash(mid)}"
                    item = {"type": "message", "role": "assistant", "status": "completed", "id": mid,
                            "content": [{"type": "output_text", "text": c.text, "annotations": []}]}
                    if sig.get("phase"):
                        item["phase"] = sig["phase"]
                    out.append(item)
                elif isinstance(c, ToolCall):
                    call_id, _, item_id = c.id.partition("|")
                    item = {"type": "function_call", "call_id": _id_part(call_id), "name": c.name,
                            "arguments": json.dumps(c.arguments)}
                    if item_id and not other_model:
                        item_id = _id_part(item_id) if same_api else f"fc_{_hash(item_id)}"
                        item["id"] = item_id if item_id.startswith("fc_") else _id_part(f"fc_{item_id}")
                    out.append(item)
        elif isinstance(m, ToolResultMessage):
            out.append({"type": "function_call_output", "call_id": _id_part(m.tool_call_id.partition("|")[0]),
                        "output": m.content})
    return out


def _args(s: str) -> dict:
    try:
        a = json.loads(s or "{}")
        return a if isinstance(a, dict) else {"_raw": s}
    except ValueError:
        return {"_raw": s}  # fails schema validation -> model gets an error result


async def parse(events) -> AsyncIterator[dict]:
    """Responses stream events -> our events. Last event is 'done' or 'error'."""
    msg, cur, buf, done = AssistantMessage(), None, "", False  # cur: block being streamed, buf: its tool args
    yield {"type": "start", "partial": msg}
    async for ev in events:
        t = ev.type
        if t == "response.output_item.added":
            it = ev.item
            if it.type == "reasoning":
                cur = ThinkingContent("")
                yield {"type": "thinking_start"}
            elif it.type == "message":
                cur = TextContent("")
            elif it.type == "function_call":
                cur, buf = ToolCall(f"{it.call_id}|{it.id}", it.name, {}), ""
                yield {"type": "toolcall_start", "name": it.name}
            else:
                cur = None
                continue
            msg.content.append(cur)
        elif t in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            if isinstance(cur, ThinkingContent):
                cur.thinking += ev.delta
                yield {"type": "thinking_delta", "delta": ev.delta}
        elif t == "response.reasoning_summary_part.done":
            if isinstance(cur, ThinkingContent):
                cur.thinking += "\n\n"
                yield {"type": "thinking_delta", "delta": "\n\n"}
        elif t in ("response.output_text.delta", "response.refusal.delta"):
            if isinstance(cur, TextContent):
                cur.text += ev.delta
                yield {"type": "text_delta", "delta": ev.delta}
        elif t == "response.function_call_arguments.delta":
            if isinstance(cur, ToolCall):
                buf += ev.delta
                yield {"type": "toolcall_delta", "delta": ev.delta}
        elif t == "response.output_item.done":
            it = ev.item
            if it.type == "reasoning" and isinstance(cur, ThinkingContent):
                summary = it.summary or []
                cur.thinking = "\n\n".join(s.text for s in summary) if summary else cur.thinking
                cur.signature = json.dumps(it.model_dump(exclude_none=True))
                yield {"type": "thinking_end"}
            elif it.type == "message" and isinstance(cur, TextContent):
                cur.text = "".join(getattr(p, "text", None) or getattr(p, "refusal", "") for p in it.content)
                cur.signature = json.dumps({"v": 1, "id": it.id, **({"phase": p} if (p := getattr(it, "phase", None)) else {})})
            elif it.type == "function_call" and isinstance(cur, ToolCall):
                cur.arguments = _args(it.arguments or buf)
                yield {"type": "toolcall_end"}
            cur = None
        elif t in ("response.completed", "response.incomplete", "response.failed"):
            done, r = True, ev.response
            if r.usage:
                details = getattr(r.usage, "output_tokens_details", None)  # output_tokens already include reasoning
                msg.usage = {"input": r.usage.input_tokens or 0, "output": r.usage.output_tokens or 0,
                             "reasoning": getattr(details, "reasoning_tokens", None) or 0}
            reason = getattr(r.incomplete_details, "reason", None) if r.incomplete_details else None
            if r.status == "completed":
                msg.stop_reason = "tool_use" if any(isinstance(c, ToolCall) for c in msg.content) else "stop"
            elif r.status == "incomplete" and reason == "max_output_tokens":
                msg.stop_reason = "length"
            else:
                err = getattr(r, "error", None)
                msg.stop_reason, msg.error = "error", (err.message if err else None) or f"Response {r.status}: {reason}"
        elif t == "error":
            done, msg.stop_reason, msg.error = True, "error", f"{getattr(ev, 'code', '')}: {ev.message}"
    if not done:
        msg.stop_reason, msg.error = "error", "Stream ended without response.completed"
    yield {"type": "error" if msg.stop_reason == "error" else "done", "message": msg}


def request(model: Model, context: Context) -> dict:
    kw = {"model": model.id, "input": to_input(model, context.system_prompt, context.messages), "stream": True,
          "store": False, "max_output_tokens": max(16, model.max_tokens)}
    if effort := _reasoning(model):
        kw["reasoning"] = {"effort": effort, "summary": "auto"}
        kw["include"] = ["reasoning.encrypted_content"]
    if context.tools:
        kw["tools"] = [{"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters}
                       for t in context.tools]
    return kw


async def stream(model: Model, context: Context, api_key: str | None = None) -> AsyncIterator[dict]:
    import openai

    try:
        client = openai.AsyncOpenAI(base_url=model.base_url, api_key=api_key)
        events = await client.responses.create(**request(model, context))
        async for ev in parse(events):
            yield ev
    except Exception as e:
        yield {"type": "error", "message": AssistantMessage(stop_reason="error", error=str(e))}
