from __future__ import annotations

import pytest

from simp_agent.agent import AgentTool, LoopConfig, agent_loop
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, UserMessage
from simp_agent.agent import ToolContext
from simp_agent.agent.env import LocalEnv
from simp_agent.coding.tools import TOOLS, edit


def fake_stream(*replies: AssistantMessage):
    """Fake provider: returns scripted assistant messages in order."""
    it = iter(replies)

    async def stream(model, ctx):
        msg = next(it)
        yield {"type": "start", "partial": msg}
        yield {"type": "error" if msg.stop_reason == "error" else "done", "message": msg}

    return stream


def call(name, **args):
    return AssistantMessage([ToolCall("c1", name, args)], stop_reason="tool_use")


async def boom(args, cancel):
    raise RuntimeError("kaboom")


async def echo(args, cancel):
    return f"echo {args['x']}"


ECHO = AgentTool("echo", "", {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}, echo)
BOOM = AgentTool("boom", "", {"type": "object"}, boom)
DONE = AssistantMessage([TextContent("ok")])


async def run(*replies, tools=(ECHO, BOOM)):
    events = []
    cfg = LoopConfig(Model(), list(tools), stream_fn=fake_stream(*replies))
    new = await agent_loop("sys", [], [UserMessage("hi")], cfg, events.append)
    return new, [e["type"] for e in events]


async def test_no_tool_call_one_turn():
    new, ev = await run(DONE)
    assert [m.role for m in new] == ["user", "assistant"]
    assert ev.count("turn_end") == 1 and ev[-1] == "agent_end"


async def test_tool_call_then_second_turn():
    new, ev = await run(call("echo", x="a"), DONE)
    assert [m.role for m in new] == ["user", "assistant", "tool_result", "assistant"]
    assert new[2].content == "echo a" and not new[2].is_error
    assert ev.count("turn_end") == 2 and "tool_execution_end" in ev


async def test_unknown_tool_and_invalid_args():
    new, _ = await run(call("nope"), call("echo", y=1), DONE)
    assert new[2].is_error and new[2].content == "Tool nope not found"
    assert new[4].is_error and "'x' is a required property" in new[4].content
    assert new[-1].text() == "ok"


async def test_tool_exception():
    new, _ = await run(call("boom"), DONE)
    assert new[2].is_error and "kaboom" in new[2].content


async def test_provider_error():
    new, ev = await run(AssistantMessage(stop_reason="error", error="bad key"))
    assert new[-1].stop_reason == "error" and ev[-1] == "agent_end"


@pytest.mark.parametrize("text,n", [("a b", 0), ("x a b", 1), ("x x", 2)])
async def test_edit_matches(tmp_path, text, n):
    f = tmp_path / "f.txt"
    f.write_text(text)
    args = {"path": str(f), "old_text": "x", "new_text": "y"}
    if n == 1:
        await edit(args, ToolContext(None, LocalEnv(), str(tmp_path), None))
        assert f.read_text() == "y a b"
    else:
        with pytest.raises(ValueError, match=f"found {n} matches"):
            await edit(args, ToolContext(None, LocalEnv(), str(tmp_path), None))


async def test_real_tools_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    new, _ = await run(call("write", path="d/h.txt", content="hi"), call("read", path="d/h.txt"),
                       call("bash", command="cat d/h.txt; exit 3"), DONE, tools=TOOLS)
    assert new[4].content == "1\thi"
    assert "hi" in new[6].content and "[exit code: 3]" in new[6].content
