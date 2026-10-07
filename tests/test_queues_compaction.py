from __future__ import annotations

from simp_agent.agent import Agent, AgentTool
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, ToolResultMessage, UserMessage
from simp_agent.compaction import find_cut

DONE = AssistantMessage([TextContent("ok")])
OVERFLOW = AssistantMessage(stop_reason="error", error="prompt is too long: 210000 tokens > 200000 maximum")


def fake(*replies):
    """Fake provider: records every call's messages. A reply can be a callable (ctx) -> message."""
    it, seen = iter(replies), []

    async def stream(model, ctx):
        seen.append(list(ctx.messages))
        msg = next(it)
        msg = msg(ctx) if callable(msg) else msg
        yield {"type": "start", "partial": msg}
        yield {"type": "error" if msg.stop_reason == "error" else "done", "message": msg}

    return stream, seen


def call(i):
    return AssistantMessage([ToolCall(f"c{i}", "t", {})], stop_reason="tool_use")


def texts(msgs):
    return [m.content for m in msgs if isinstance(m, UserMessage)]


async def test_steer_delivered_after_tool_batch():
    agent = None

    async def t(args, cancel):
        agent.steer("change plan")  # typed while the tool runs
        return "r"

    stream, seen = fake(call(1), DONE)
    agent = Agent("s", Model(), [AgentTool("t", "", {"type": "object"}, t)], stream, auto_compact=False)
    await agent.prompt("go")
    assert "change plan" not in texts(seen[0])
    assert texts(seen[1])[-1] == "change plan" and isinstance(seen[1][-2], ToolResultMessage)
    assert not agent.has_queued()


async def test_follow_up_one_at_a_time_and_all():
    for mode, calls in (("one-at-a-time", 3), ("all", 2)):
        stream, seen = fake(DONE, DONE, DONE)
        a = Agent("s", Model(), [], stream, auto_compact=False)
        a.follow_up_mode = mode
        a.follow_up("f1")
        a.follow_up("f2")
        await a.prompt("go")
        assert len(seen) == calls
        assert texts(seen[-1])[-2:] == ["f1", "f2"] and not a.has_queued()


def big(text, n):
    return UserMessage(text + "x" * n)


def history():
    # user, assistant tool_use, tool_result, user, assistant  (~4000 tokens each)
    return [
        big("old", 16000),
        AssistantMessage([ToolCall("c1", "t", {})], stop_reason="tool_use"),
        ToolResultMessage("c1", "t", "y" * 16000),
        big("new", 16000),
        AssistantMessage([TextContent("z" * 16000)], usage={"input": 9000, "output": 100}),
    ]


def small_model():
    return Model(context_window=10000)


def compact_agent(stream):
    a = Agent("s", small_model(), [], stream)
    a.compaction.reserve_tokens, a.compaction.keep_recent_tokens = 1000, 5000
    return a


async def test_compaction_replaces_history():
    stream, seen = fake(AssistantMessage([TextContent("SUM")]), DONE)
    a = compact_agent(stream)
    a.messages = history()
    events = []
    a.subscribe(lambda e: events.append(e["type"]))
    await a.prompt("next")
    assert "compaction_start" in events and "compaction_end" in events
    summary_call = seen[0]
    assert summary_call[0].content.startswith("old") and isinstance(summary_call[2], ToolResultMessage)
    assert a.messages[0].content == "<summary>SUM</summary>"
    assert a.messages[1].content.startswith("new")  # cut on a user message: tool pair stayed together
    assert seen[1][0].content == "<summary>SUM</summary>"


def test_cut_never_splits_tool_pair():
    msgs = history()
    for keep in range(0, 20000, 500):
        cut = find_cut(msgs, keep)
        assert cut is None or isinstance(msgs[cut], UserMessage)


async def test_below_threshold_no_compaction():
    stream, seen = fake(DONE)
    a = Agent("s", Model(), [], stream)
    a.messages = history()
    await a.prompt("next")
    assert len(seen) == 1 and a.messages[0].content.startswith("old")


async def test_summary_error_keeps_history():
    stream, seen = fake(AssistantMessage(stop_reason="error", error="boom"), DONE)
    a = compact_agent(stream)
    a.messages = history()
    ends = []
    a.subscribe(lambda e: e["type"] == "compaction_end" and ends.append(e))
    await a.prompt("next")
    assert ends[0]["error"] and a.messages[0].content.startswith("old")
    assert a.messages[-1] is DONE


async def test_overflow_compacts_and_retries_once():
    stream, seen = fake(OVERFLOW, AssistantMessage([TextContent("SUM")]), DONE)
    a = Agent("s", Model(), [], stream)  # big window: only the overflow forces compaction
    a.compaction.keep_recent_tokens = 5000
    a.messages = history()
    await a.prompt("next")
    assert len(seen) == 3 and a.messages[-1] is DONE
    assert a.messages[0].content == "<summary>SUM</summary>" and OVERFLOW not in a.messages


async def test_second_overflow_stops():
    stream, seen = fake(OVERFLOW, AssistantMessage([TextContent("SUM")]), OVERFLOW)
    a = Agent("s", Model(), [], stream)
    a.compaction.keep_recent_tokens = 5000
    a.messages = history()
    await a.prompt("next")
    assert len(seen) == 3 and a.messages[-1].stop_reason == "error"


async def test_existing_summary_is_updated():
    stream, seen = fake(AssistantMessage([TextContent("SUM2")]), DONE)
    a = compact_agent(stream)
    a.messages = [UserMessage("<summary>SUM1</summary>")] + history()
    await a.prompt("next")
    assert "<previous-summary>\nSUM1\n" in seen[0][-1].content
    assert not any(m.content.startswith("<summary>") for m in seen[0][:-1] if isinstance(m, UserMessage))
    assert a.messages[0].content == "<summary>SUM2</summary>"
