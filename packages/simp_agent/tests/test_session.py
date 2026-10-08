import asyncio

from simp_agent.agent.compaction import CompactionEntry
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, UserMessage
from simp_agent.session import AgentSession

DONE = AssistantMessage([TextContent("ok")])


def err429():
    return AssistantMessage(stop_reason="error", error="Error code: 429 rate_limit_error")


def fake(*replies):
    it, seen = iter(replies), []

    async def stream(model, ctx, api_key=None):
        seen.append(list(ctx.messages))
        msg = next(it)
        yield {"type": "error" if msg.stop_reason == "error" else "done", "message": msg}

    return stream, seen


class ListStore:
    def __init__(self, items=()):
        self.items = list(items)

    def append(self, entry):
        self.items.append(entry)

    def load(self):
        return list(self.items)


def session(stream, **kw):
    return AgentSession(Model(), [], stream_fn=stream, system_prompt="s", **kw)


async def test_retry_429_twice_then_ok():
    stream, seen = fake(err429(), err429(), DONE)
    s = session(stream, retry_base_delay=0.001)
    events = []
    s.subscribe(lambda e: e["type"].startswith("auto_retry") and events.append(e))
    await s.prompt("hi")
    assert len(seen) == 3 and s.messages[-1] is DONE
    assert [e["type"] for e in events] == ["auto_retry_start", "auto_retry_start", "auto_retry_end"]
    assert events[1]["delay"] == 0.002 and events[-1]["success"]
    assert all(m.role != "assistant" or m.stop_reason != "error" for m in seen[2])  # LLM view drops the errors


async def test_abort_during_backoff_stops():
    stream, seen = fake(err429(), DONE)
    s = session(stream, retry_base_delay=60)
    s.subscribe(lambda e: e["type"] == "auto_retry_start" and asyncio.get_running_loop().call_soon(s.abort))
    await asyncio.wait_for(s.prompt("hi"), 5)
    assert len(seen) == 1 and s.messages[-1].stop_reason == "error"


async def test_store_gets_every_message_in_order():
    stream, _ = fake(AssistantMessage([ToolCall("c1", "nope", {})], stop_reason="tool_use"), DONE)
    store = ListStore()
    s = session(stream, store=store)
    await s.prompt("hi")
    assert store.items == s.messages and [m.role for m in store.items] == ["user", "assistant", "tool_result", "assistant"]
    assert AgentSession(Model(), [], store=store, messages=store.load()).messages == store.items  # app restores


async def test_session_triggers_compaction_and_stores_entry():
    stream, seen = fake(AssistantMessage([TextContent("SUM")]), DONE)
    old = [UserMessage("a" * 40000), AssistantMessage([TextContent("b" * 40000)]), UserMessage("c" * 40000),
           AssistantMessage([TextContent("d")], usage={"input": 9500, "output": 10})]
    store = ListStore(old)
    s = AgentSession(Model(context_window=10000), [], store=store, messages=store.load(), stream_fn=stream, system_prompt="s")
    s.compaction.reserve_tokens, s.compaction.keep_recent_tokens = 1000, 5000
    await s.prompt("next")
    assert len(seen) == 2 and any(isinstance(m, CompactionEntry) for m in store.items)
    assert store.items == s.messages


async def test_context_file_in_system_prompt(tmp_path):
    (tmp_path / "AGENTS.md").write_text("use tabs")
    prompts = []

    async def stream(model, ctx, api_key=None):
        prompts.append(ctx.system_prompt)
        yield {"type": "done", "message": DONE}

    await AgentSession(Model(), [], cwd=str(tmp_path), stream_fn=stream).prompt("hi")
    assert "use tabs" in prompts[0] and "AGENTS.md" in prompts[0]
