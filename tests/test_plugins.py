import asyncio
import json

import pytest

from simp_agent import ai
from simp_agent.agent import Agent, AgentTool
from simp_agent.ai import AssistantMessage, Context, Model, TextContent, ToolCall, ToolResultMessage, UserMessage, from_dict, to_dict
from simp_agent.agent.compaction import CompactionEntry, build_view
from simp_agent.cli import JsonlStore
from simp_agent.coding.tools import TOOLS
from simp_agent.session import AgentSession

DONE = AssistantMessage([TextContent("ok")])


def fake(*replies, seen=None):
    it = iter(replies)

    async def stream(model, ctx, api_key=None):
        if seen is not None:
            seen.append((api_key, list(ctx.messages)))
        yield {"type": "done", "message": next(it)}

    return stream


def call(name, **args):
    return AssistantMessage([ToolCall(f"c_{name}", name, args)], stop_reason="tool_use")


async def test_get_api_key_per_call_and_per_agent():
    keys = iter(["k1", "k2"])
    calls, seen_a, seen_b = [], [], []

    def get_key(provider):
        calls.append(provider)
        return next(keys)

    async def get_b(provider):
        return "other"

    tool = AgentTool("t", "", {"type": "object"}, lambda a, c: asyncio.sleep(0, "r"))
    a = Agent("s", Model(), [tool], fake(call("t"), DONE, seen=seen_a), get_api_key=get_key)
    b = Agent("s", Model(), [], fake(DONE, seen=seen_b), get_api_key=get_b)
    await a.prompt("x")
    await b.prompt("x")
    assert calls == ["anthropic", "anthropic"]
    assert [k for k, _ in seen_a] == ["k1", "k2"] and seen_b[0][0] == "other"


class MemEnv:
    def __init__(self):
        self.files, self.cmds = {}, []

    async def read_file(self, path):
        return self.files[path]

    async def write_file(self, path, text):
        self.files[path] = text

    async def exec(self, command, cwd, timeout, cancel, on_output=None):
        self.cmds.append((command, cwd))
        await on_output("part1")
        return 0, "out"


async def test_fake_env_and_on_update(tmp_path):
    env, events = MemEnv(), []
    agent = Agent("s", Model(), TOOLS, fake(call("write", path="a.txt", content="hi"), call("read", path="a.txt"),
                                            call("bash", command="ls"), DONE), env=env, cwd="/virt")
    agent.subscribe(events.append)
    new = await agent.prompt("x")
    assert env.files == {"/virt/a.txt": "hi"} and env.cmds == [("ls", "/virt")]
    assert new[4].content == "1\thi" and "out" in new[6].content
    assert [e["text"] for e in events if e["type"] == "tool_execution_update"] == ["part1"]
    assert not (tmp_path / "a.txt").exists()


def _saved():
    return [UserMessage("old"), AssistantMessage([TextContent("a"), ToolCall("c1", "t", {"x": 1})], "tool_use", {"input": 5, "output": 1}),
            ToolResultMessage("c1", "t", "r"), CompactionEntry("SUM", 2)]


async def test_restore_roundtrip_then_prompt():
    msgs = [from_dict(json.loads(json.dumps(to_dict(m)))) for m in _saved()]
    assert msgs == _saved()
    seen = []
    agent = Agent("s", Model(), [], fake(DONE, seen=seen), messages=msgs)
    await agent.prompt("new")
    sent = seen[0][1]
    assert "SUM" in sent[0].content and [m.role for m in sent[1:]] == ["tool_result", "user"]
    assert build_view(agent.messages)[0].content == sent[0].content


async def test_continue():
    seen = []
    agent = Agent("s", Model(), [], fake(DONE, seen=seen), messages=_saved()[:3])
    new = await agent.continue_()
    assert len(seen) == 1 and new == [DONE]
    with pytest.raises(ValueError, match="last message"):
        await agent.continue_()


async def test_register_provider():
    async def mine(model, ctx, api_key=None):
        yield {"type": "done", "message": AssistantMessage([TextContent(f"mine:{api_key}")])}

    ai.register_provider("my-api", mine)
    evs = [e async for e in ai.stream(Model(api="my-api"), Context("s", []), api_key="K")]
    assert evs[-1]["message"].text() == "mine:K"


async def test_jsonl_store_roundtrip(tmp_path):
    path = tmp_path / "s.jsonl"
    session = AgentSession(Model(), TOOLS, JsonlStore(path), cwd=str(tmp_path), stream_fn=fake(call("bash", command="echo hi"), DONE))
    await session.prompt("x")
    assert JsonlStore(path).load() == session.messages
