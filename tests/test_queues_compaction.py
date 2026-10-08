from __future__ import annotations

from simp_agent.agent import Agent, AgentTool
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, ToolResultMessage, UserMessage
from simp_agent.agent.compaction import CompactionEntry, find_cut
from simp_agent.session import AgentSession

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
    agent = Agent("s", Model(), [AgentTool("t", "", {"type": "object"}, t)], stream)
    await agent.prompt("go")
    assert "change plan" not in texts(seen[0])
    assert texts(seen[1])[-1] == "change plan" and isinstance(seen[1][-2], ToolResultMessage)
    assert not agent.has_queued()


async def test_follow_up_one_at_a_time_and_all():
    for mode, calls in (("one-at-a-time", 3), ("all", 2)):
        stream, seen = fake(DONE, DONE, DONE)
        a = Agent("s", Model(), [], stream)
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
    a = AgentSession(small_model(), [], stream_fn=stream, system_prompt="s")
    a.compaction.reserve_tokens, a.compaction.keep_recent_tokens = 1000, 5000
    return a


SUM_HEAD = "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"


async def test_compaction_appends_marker_and_view():
    stream, seen = fake(AssistantMessage([TextContent("SUM")]), DONE)
    a = compact_agent(stream)
    a.agent.messages = history()
    events = []
    a.subscribe(lambda e: events.append(e["type"]))
    await a.prompt("next")
    assert "compaction_start" in events and "compaction_end" in events
    summary_call = seen[0]
    assert len(summary_call) == 1 and summary_call[0].content.startswith("<conversation>\n[User]: old")
    assert "[Tool result]: yyy" in summary_call[0].content
    assert a.messages[0].content.startswith("old")  # full history still has the old messages
    entry = next(m for m in a.messages if isinstance(m, CompactionEntry))
    assert entry.summary == "SUM" and a.messages[entry.first_kept_index].content.startswith("new")
    assert seen[1][0].content == SUM_HEAD + "SUM\n</summary>" and seen[1][1].content.startswith("new")


def test_cut_never_on_tool_result():
    msgs = history()
    for keep in range(0, 20000, 500):
        cut = find_cut(msgs, 0, keep)
        assert cut is None or not isinstance(msgs[cut], ToolResultMessage)


async def test_steer_during_compaction_same_turn():
    a = None

    def summary(ctx):
        a.steer("late")  # typed while the slow summary call runs
        return AssistantMessage([TextContent("SUM")])

    stream, seen = fake(summary, DONE)
    a = compact_agent(stream)
    a.agent.messages = history()
    await a.prompt("next")
    assert len(seen) == 2 and texts(seen[1])[-1] == "late"


async def test_below_threshold_no_compaction():
    stream, seen = fake(DONE)
    a = AgentSession(Model(), [], stream_fn=stream, system_prompt="s")
    a.agent.messages = history()
    await a.prompt("next")
    assert len(seen) == 1 and not any(isinstance(m, CompactionEntry) for m in a.messages)


async def test_summary_error_keeps_history():
    stream, seen = fake(AssistantMessage(stop_reason="error", error="boom"), DONE)
    a = compact_agent(stream)
    a.agent.messages = history()
    ends = []
    a.subscribe(lambda e: e["type"] == "compaction_end" and ends.append(e))
    await a.prompt("next")
    assert ends[0]["error"] and not any(isinstance(m, CompactionEntry) for m in a.messages)
    assert a.messages[-1] is DONE


async def test_overflow_compacts_and_retries_once():
    stream, seen = fake(OVERFLOW, AssistantMessage([TextContent("SUM")]), DONE)
    a = AgentSession(Model(), [], stream_fn=stream, system_prompt="s")  # big window: only the overflow forces compaction
    a.compaction.keep_recent_tokens = 5000
    a.agent.messages = history()
    await a.prompt("next")
    assert len(seen) == 3 and a.messages[-1] is DONE
    assert seen[2][0].content.startswith(SUM_HEAD) and OVERFLOW not in seen[2]


async def test_second_overflow_stops():
    stream, seen = fake(OVERFLOW, AssistantMessage([TextContent("SUM")]), OVERFLOW)
    a = AgentSession(Model(), [], stream_fn=stream, system_prompt="s")
    a.compaction.keep_recent_tokens = 5000
    a.agent.messages = history()
    await a.prompt("next")
    assert len(seen) == 3 and a.messages[-1].stop_reason == "error"


async def test_existing_summary_is_updated():
    stream, seen = fake(AssistantMessage([TextContent("SUM1")]), DONE, AssistantMessage([TextContent("SUM2")]), DONE)
    a = compact_agent(stream)
    a.agent.messages = history()
    await a.prompt("next")
    a.agent.messages += history()[1:]  # grow again past the threshold
    await a.prompt("more")
    assert "<previous-summary>\nSUM1\n" in seen[2][-1].content
    assert "[User]: old" not in seen[2][0].content  # already summarized part is not resent
    assert seen[3][0].content == SUM_HEAD + "SUM2\n</summary>"


async def test_stale_usage_does_not_compact_twice():
    # after compaction the only usage is from before the marker; next turn (tool call, no usage) must not compact again
    async def t(args, cancel):
        return "r"

    SUM = lambda: AssistantMessage([TextContent("SUM")])  # noqa: E731
    stream, seen = fake(SUM(), call(1), SUM(), DONE, DONE)
    a = compact_agent(stream)
    a.agent.tools = [AgentTool("t", "", {"type": "object"}, t)]
    a.agent.messages = history()
    ends = []
    a.subscribe(lambda e: e["type"] == "compaction_end" and ends.append(e))
    await a.prompt("next")
    assert sum("summary" in str(c[-1].content) for c in seen) == 1
    assert len([m for m in a.messages if isinstance(m, CompactionEntry)]) == 1
    assert ends[0]["tokens_after"] < ends[0]["tokens_before"]
