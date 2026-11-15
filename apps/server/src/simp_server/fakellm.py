"""Deterministic stream_fn for e2e (`simp-server run --fake-llm`). Reacts to the last message:
"slow ..." -> 40 slow chunks; "tool ..." -> a bash call (needs approval); a tool result -> "Tool said: ..."; else echo.
A title request (system prompt "Name this conversation...") -> "Fake title".
Load-test mode (only when SIMP_FAKE_TOKENS is set): any user prompt streams SIMP_FAKE_TOKENS tokens ("tok ")
after SIMP_FAKE_TTFT seconds, at SIMP_FAKE_TPS tokens/sec. See apps/server/scripts/loadtest.py."""

from __future__ import annotations

import asyncio
import itertools
import os

from simp_agent.ai import AssistantMessage, TextContent, ThinkingContent, ToolCall

DELAY = float(os.environ.get("SIMP_FAKE_DELAY", "0.05"))
ids = itertools.count(1)
LOAD_TOKENS = int(os.environ.get("SIMP_FAKE_TOKENS", "0"))
LOAD_TPS = float(os.environ.get("SIMP_FAKE_TPS", "50"))
LOAD_TTFT = float(os.environ.get("SIMP_FAKE_TTFT", "0.8"))


async def load_stream(ctx):
    """Realistic-speed answer; sleeps against a deadline so per-token sleeps don't drift under load."""
    loop = asyncio.get_running_loop()
    msg = AssistantMessage([TextContent("tok " * LOAD_TOKENS)], stop_reason="stop",
                           usage={"input": 1, "output": LOAD_TOKENS})
    yield {"type": "start", "partial": msg}
    t0 = loop.time() + LOAD_TTFT
    for i in range(LOAD_TOKENS):
        await asyncio.sleep(max(0.0, t0 + i / LOAD_TPS - loop.time()))
        yield {"type": "text_delta", "delta": "tok "}
    yield {"type": "done", "message": msg}


async def stream(model, ctx, api_key=None):
    last = ctx.messages[-1]
    if LOAD_TOKENS and last.role == "user" and not ctx.system_prompt.startswith("Name this conversation"):
        async for ev in load_stream(ctx):
            yield ev
        return
    if ctx.system_prompt.startswith("Name this conversation"):
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
