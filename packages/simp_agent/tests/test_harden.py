from __future__ import annotations

import asyncio

import pytest

from simp_agent import ai
from simp_agent.agent import Agent, AgentTool, LoopConfig, agent_loop
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, ToolResultMessage, UserMessage

DONE = AssistantMessage([TextContent("ok")])


def recording_stream(*replies):
    """Fake provider that records the messages it was sent."""
    it, seen = iter(replies), []

    async def stream(model, ctx):
        seen.append(list(ctx.messages))
        msg = next(it)
        yield {"type": "start", "partial": msg}
        yield {"type": "error" if msg.stop_reason == "error" else "done", "message": msg}

    return stream, seen


def check_pairs(msgs):
    ids = {c.id for m in msgs if isinstance(m, AssistantMessage) for c in m.tool_calls()}
    res = {m.tool_call_id for m in msgs if isinstance(m, ToolResultMessage)}
    assert ids == res


async def test_abort_mid_batch_repairs_history():
    cancel = asyncio.Event()

    async def slow(args, c):
        if args["n"] == 2:
            cancel.set()
        return "r"

    tool = AgentTool("t", "", {"type": "object"}, slow)
    batch = AssistantMessage([ToolCall(f"c{i}", "t", {"n": i}) for i in (1, 2, 3)], stop_reason="tool_use")
    stream, seen = recording_stream(batch, DONE)
    msgs = []
    cfg = LoopConfig(Model(), [tool], stream_fn=stream)
    await agent_loop("s", msgs, [UserMessage("a")], cfg, cancel=cancel)
    assert msgs[-1].stop_reason == "aborted"
    await agent_loop("s", msgs, [UserMessage("b")], cfg)
    sent = seen[-1]
    check_pairs(sent)
    assert not any(isinstance(m, AssistantMessage) and m.stop_reason == "aborted" for m in sent)
    assert next(m for m in sent if getattr(m, "tool_call_id", "") == "c3").content == "No result provided"


async def test_stream_error_message_excluded():
    bad = AssistantMessage([ToolCall("x", "t", {})], stop_reason="error", error="boom")
    stream, seen = recording_stream(bad, DONE)
    msgs = []
    cfg = LoopConfig(Model(), [], stream_fn=stream)
    await agent_loop("s", msgs, [UserMessage("a")], cfg)
    await agent_loop("s", msgs, [UserMessage("b")], cfg)
    assert bad in msgs and bad not in seen[-1]
    check_pairs(seen[-1])


async def test_length_tool_calls_not_run():
    ran = []

    async def t(args, c):
        ran.append(1)
        return "r"

    cut = AssistantMessage([ToolCall("c1", "t", {})], stop_reason="length")
    stream, _ = recording_stream(cut, DONE)
    new = await agent_loop("s", [], [UserMessage("a")], LoopConfig(Model(), [AgentTool("t", "", {"type": "object"}, t)], stream_fn=stream))
    assert not ran
    assert new[2].is_error and new[2].tool_call_id == "c1"


async def test_abort_during_stream_closes():
    closed, cancel = [], asyncio.Event()

    async def stream(model, ctx):
        msg = AssistantMessage([TextContent("par")])
        try:
            yield {"type": "start", "partial": msg}
            cancel.set()
            await asyncio.sleep(10)
            yield {"type": "done", "message": msg}
        finally:
            closed.append(1)

    new = await asyncio.wait_for(agent_loop("s", [], [UserMessage("a")], LoopConfig(Model(), stream_fn=stream), cancel=cancel), 2)
    assert new[-1].stop_reason == "aborted" and new[-1].text() == "par"
    assert closed


async def test_async_subscriber_awaited():
    got = []

    async def sub(e):
        await asyncio.sleep(0)
        got.append(e["type"])

    stream, _ = recording_stream(DONE)
    a = Agent("s", Model(), [], stream)
    a.subscribe(sub)
    await a.prompt("hi")
    assert got[0] == "agent_start" and got[-1] == "agent_end"


async def test_raising_subscriber_ends_with_error():
    def sub(e):
        if e["type"] == "message_end":
            raise ValueError("sub broke")

    stream, _ = recording_stream(DONE)
    a = Agent("s", Model(), [], stream)
    a.subscribe(sub)
    await a.prompt("hi")
    assert a.messages[-1].stop_reason == "error" and "sub broke" in a.messages[-1].error
    assert not a.is_streaming


async def test_prompt_while_streaming():
    gate = asyncio.Event()

    async def stream(model, ctx):
        await gate.wait()
        yield {"type": "done", "message": DONE}

    a = Agent("s", Model(), [], stream)
    task = asyncio.create_task(a.prompt("one"))
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="already"):
        await a.prompt("two")
    gate.set()
    await task


def test_classify():
    assert ai.is_retryable("Error code: 429 rate_limit_error")
    assert ai.is_retryable("529 overloaded_error: Overloaded")
    assert ai.is_retryable("Connection error.")
    assert ai.is_retryable("Error code: 503 service unavailable")
    assert not ai.is_retryable("Error code: 400 invalid_request_error")
    assert ai.is_context_overflow("prompt is too long: 210000 tokens > 200000 maximum")
    assert ai.is_context_overflow("request_too_large")
    assert not ai.is_context_overflow("Error code: 429 rate limit")
