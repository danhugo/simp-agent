"""Tool calls of one message: read-only ones next to each other run at once; others run alone, in order."""
import asyncio
import time

from simp_agent.agent import AgentTool, LoopConfig, agent_loop
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, UserMessage
from simp_agent.testing import FakeProvider

log = list()


def tool(name, parallel):
    async def run(args, ctx):
        log.append((name, "start", time.monotonic()))
        await asyncio.sleep(0.2)
        log.append((name, "end", time.monotonic()))
        return name
    return AgentTool(name, name, {"type": "object"}, run, parallel=parallel)


async def test_read_only_calls_run_together_others_alone_results_in_order():
    log.clear()
    tools = [tool("r1", True), tool("r2", True), tool("w", False), tool("r3", True)]
    calls = [ToolCall(f"c{i}", n, {}) for i, n in enumerate(["r1", "r2", "w", "r3"])]
    fake = FakeProvider(AssistantMessage(calls, stop_reason="tool_use"), AssistantMessage([TextContent("ok")]))
    history = list()
    t = time.monotonic()
    await agent_loop("sys", history, [UserMessage("go")], LoopConfig(Model(), tools, stream_fn=fake))
    took = time.monotonic() - t
    assert [m.content for m in history if m.role == "tool_result"] == ["r1", "r2", "w", "r3"]
    at = {(n, e): x for n, e, x in log}
    assert at["r2", "start"] < at["r1", "end"]  # r1 and r2 together
    assert at["w", "start"] >= at["r2", "end"] and at["r3", "start"] >= at["w", "end"]  # w alone, r3 after it
    assert took < 0.75  # 3 rounds of 0.2s, not 4
