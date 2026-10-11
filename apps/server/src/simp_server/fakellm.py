"""Deterministic stream_fn for e2e (`simp-server run --fake-llm`). Reacts to the last message:
"slow ..." -> 40 slow chunks; "tool ..." -> a bash call (needs approval); a tool result -> "Tool said: ..."; else echo.
A title request (system prompt "Name this coding session...") -> "Fake title"."""

from __future__ import annotations

import asyncio
import itertools
import os

from simp_agent.ai import AssistantMessage, TextContent, ThinkingContent, ToolCall

DELAY = float(os.environ.get("SIMP_FAKE_DELAY", "0.05"))
ids = itertools.count(1)


async def stream(model, ctx, api_key=None):
    last = ctx.messages[-1]
    if ctx.system_prompt.startswith("Name this coding session"):
        chunks, calls = ["Fake title"], []
    elif last.role == "tool_result":
        chunks, calls = [f"Tool said: {last.content.strip()}"], []
    elif last.content.startswith("tool"):
        chunks, calls = ["Running a command."], [ToolCall(f"call{next(ids)}", "bash", {"command": "echo hi-from-tool"})]
    elif last.content.startswith("slow"):
        chunks, calls = [f"w{i} " for i in range(40)], []
    else:
        chunks, calls = ["Echo: ", last.content], []
    text = "".join(chunks)
    msg = AssistantMessage([ThinkingContent("thinking..."), TextContent(text), *calls],
                           stop_reason="tool_use" if calls else "stop", usage={"input": 1, "output": 1})
    yield {"type": "start", "partial": msg}
    yield {"type": "thinking_delta", "delta": "thinking..."}
    for c in chunks:
        await asyncio.sleep(DELAY * (3 if last.role == "user" and last.content.startswith("slow") else 1))
        yield {"type": "text_delta", "delta": c}
    yield {"type": "done", "message": msg}
