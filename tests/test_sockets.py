"""Stage 0 A+C: fixes and plugin sockets."""

import asyncio
import json

from simp_agent import ai
from simp_agent.agent import Agent, AgentTool
from simp_agent.ai import AssistantMessage, Context, CustomEntry, Model, TextContent, ToolCall, UserMessage, from_dict, to_dict
from simp_agent.cli import JsonlStore
from simp_agent.plugins import PlanMode, RedactSecrets
from simp_agent.session import AgentSession

DONE = AssistantMessage([TextContent("ok")])


def fake(*replies, seen=None):
    it = iter(replies)

    async def stream(model, ctx, api_key=None):
        if seen is not None:
            seen.append(ctx)
        yield {"type": "done", "message": next(it)}

    return stream


def call(name, id="c1", **args):
    return AssistantMessage([ToolCall(id, name, args)], stop_reason="tool_use")


def tool(name, out="r", **kw):
    async def run(args, ctx):
        return out

    return AgentTool(name, "", {"type": "object"}, run, **kw)


def session(*replies, seen=None, **kw):
    return AgentSession(Model(), kw.pop("tools", []), stream_fn=fake(*replies, seen=seen), system_prompt="s", **kw)


# ---- A. fixes ----

async def test_async_store_order():
    items = []

    class AsyncStore:
        async def append(self, entry):
            await asyncio.sleep(0)
            items.append(entry)

    s = session(call("t"), DONE, tools=[tool("t")], store=AsyncStore())
    await s.prompt("hi")
    assert items == s.messages and [m.role for m in items] == ["user", "assistant", "tool_result", "assistant"]


async def test_get_api_key_none_is_error_and_env_not_read(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "envkey")
    s = AgentSession(Model(), [], get_api_key=lambda p: None, system_prompt="s", max_retries=3, retry_base_delay=0)
    await s.prompt("hi")
    last = s.messages[-1]
    assert last.stop_reason == "error" and last.error == "no API key for provider anthropic" and len(s.messages) == 2
    evs = [e async for e in ai.stream(Model(), Context("s", []))]  # no key at all: providers never read env
    assert "no API key" in evs[-1]["message"].error


async def test_fatal_error_not_retried():
    seen = []
    s = session(AssistantMessage(stop_reason="error", error="429 rate limit", error_kind="budget"), DONE, seen=seen,
                retry_base_delay=0)
    await s.prompt("hi")
    assert len(seen) == 1 and s.messages[-1].error_kind == "budget"
    assert ai.is_retryable("429") and not ai.is_retryable("429", "fatal")


# ---- C. sockets ----

async def test_tool_added_mid_session_is_seen_with_note():
    seen = []
    s = session(DONE, DONE, seen=seen, tools=[tool("a")])
    await s.prompt("one")
    s.agent.tools.append(tool("b"))
    s.agent.tools[:] = [t for t in s.agent.tools if t.name != "a"]
    await s.prompt("two")
    assert [t.name for t in seen[1].tools] == ["b"]
    assert "Tools added: b; removed: a" in seen[1].messages[-1].content
    assert "Tools" not in str(seen[0].messages)


async def test_prompt_sections_order_and_rebuild():
    seen = []
    s = session(DONE, DONE, seen=seen)
    n = iter(range(10))
    s.add_prompt_section("late", "LATE", 200)
    s.add_prompt_section("dyn", lambda ctx: f"turn{next(n)}", 50)
    await s.prompt("1")
    s.add_prompt_section("late", "LATE2", 200)  # replace keeps place
    await s.prompt("2")
    assert seen[0].system_prompt == "s\n\nturn0\n\nLATE" and seen[1].system_prompt == "s\n\nturn1\n\nLATE2"


async def test_custom_entry_persisted_replayed_not_sent(tmp_path):
    path, seen = tmp_path / "s.jsonl", []
    s = session(DONE, store=JsonlStore(path))
    await s.append_entry("note", {"x": 1})
    await s.prompt("hi")
    loaded = JsonlStore(path).load()
    assert loaded[0] == CustomEntry("note", {"x": 1}) and from_dict(json.loads(json.dumps(to_dict(loaded[0])))) == loaded[0]
    s2 = session(DONE, seen=seen, messages=loaded)
    await s2.prompt("again")
    assert all(m.role != "custom" for m in seen[0].messages) and s2.messages[0].role == "custom"


async def test_after_tool_call_and_prepare_arguments():
    got = []

    async def run(args, ctx):
        got.append(args)
        return "raw"

    t = AgentTool("t", "", {"type": "object", "required": ["n"]}, run, prepare_arguments=lambda a: {"n": a.get("num")})
    after = lambda c, r, ctx: ai.ToolResultMessage(r.tool_call_id, r.tool_name, r.content + "!")  # noqa: E731
    a = Agent("s", Model(), [t], fake(call("t", num=1), DONE), after_tool_call=after)
    new = await a.prompt("x")
    assert got == [{"n": 1}] and new[2].content == "raw!"


class Rec:
    def __init__(self, name, **hooks):
        self.name, self.log = name, []
        for k, v in hooks.items():
            setattr(self, k, v)


async def test_plugin_input_handled_and_rewrite():
    seen = []
    p1 = Rec("p1", input=lambda t: {"handled": True} if t == "/x" else {"text": t.upper()})
    p2 = Rec("p2", input=lambda t: {"text": t + "!"})
    s = session(DONE, seen=seen, plugins=[p1, p2])
    assert await s.prompt("/x") == [] and seen == []
    await s.prompt("hi")
    assert seen[0].messages[-1].content == "HI!"


async def test_plugin_context_chain_and_error_isolated():
    seen, events = [], []

    def boom(msgs):
        raise RuntimeError("bad")

    p1 = Rec("p1", context=lambda m: m + [UserMessage("A")])
    p2 = Rec("p2", context=boom)
    p3 = Rec("p3", context=lambda m: m + [UserMessage(m[-1].content + "B")])
    s = session(DONE, seen=seen, plugins=[p1, p2, p3])
    s.subscribe(events.append)
    await s.prompt("hi")
    assert [m.content for m in seen[0].messages] == ["hi", "A", "AB"]
    assert [(e["plugin"], e["hook"]) for e in events if e["type"] == "plugin_error"] == [("p2", "context")]


async def test_plugin_tool_call_first_block_exception_and_result_merge():
    def boom(c):
        raise ValueError("x")

    p1 = Rec("p1", tool_call=lambda c: {"args": {"v": 2}} if c.name == "t" else None,
             tool_result=lambda c, r: {"content": r.content + "-p1"})
    p2 = Rec("p2", tool_call=lambda c: {"block": "no"} if c.name == "u" else None,
             tool_result=lambda c, r: {"content": r.content + "-p2", "is_error": True})
    p3 = Rec("p3", tool_call=lambda c: boom(c) if c.name == "w" else {"block": "late"} if c.name == "u" else None)
    ran = []

    async def run(args, ctx):
        ran.append(args)
        return "r"

    tools = [AgentTool(n, "", {"type": "object"}, run) for n in "tuw"]
    s = session(call("t"), call("u", "c2"), call("w", "c3"), DONE, tools=tools, plugins=[p1, p2, p3])
    await s.prompt("go")
    t_res, u_res, w_res = [m for m in s.messages if m.role == "tool_result"]
    assert ran == [{"v": 2}] and t_res.content == "r-p1-p2" and t_res.is_error
    assert "p2: no" in u_res.content and "p3" in w_res.content and "ValueError" in w_res.content


async def test_plugin_setup_events_and_api():
    events = []

    class P:
        name = "p"

        async def setup(self, api, config):
            self.api, self.config = api, config
            api.register_tool(tool("extra"))

        def on_event(self, e):
            events.append(e["type"])

    p = P()
    seen = []
    s = session(DONE, seen=seen, plugins=[p], plugin_config={"p": {"k": 1}})
    await s.prompt("hi")
    assert p.config == {"k": 1} and [t.name for t in seen[0].tools] == ["extra"]
    assert "agent_start" in events and "agent_end" in events


async def test_redact_plugin_masks_key_in_tool_output():
    key = "sk-" + "a" * 30
    seen = []
    s = session(call("t"), DONE, seen=seen, tools=[tool("t", f"token={key} and MYSECRETVALUE")],
                plugins=[RedactSecrets()], plugin_config={"redact_secrets": {"secrets": ["MYSECRETVALUE"], "env": False}})
    await s.prompt(f"use {key}")
    res = s.messages[2]
    assert res.content == "token=[REDACTED] and [REDACTED]"
    assert key not in str(seen[1].messages) and s.messages[0].content == f"use {key}"  # history keeps the user text


async def test_plan_mode_blocks_write_and_survives_resume(tmp_path):
    path, seen = tmp_path / "s.jsonl", []
    plan = PlanMode()
    s = session(call("write", path="a", content="x"), DONE, seen=seen, tools=[tool("write")], store=JsonlStore(path), plugins=[plan])
    await s.start()
    await plan.set_enabled(True)
    await s.prompt("do it")
    assert "plan mode" in s.messages[3].content and s.messages[3].is_error
    assert "PLAN MODE" in seen[0].system_prompt
    plan2 = PlanMode()
    s2 = session(DONE, seen=seen, store=JsonlStore(path), messages=JsonlStore(path).load(), plugins=[plan2])
    await s2.prompt("again")
    assert plan2.enabled and "PLAN MODE" in seen[-1].system_prompt
