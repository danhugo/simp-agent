from __future__ import annotations

import asyncio
import shlex

from simp_agent.agent import AgentTool, ToolContext, run_tool
from simp_agent.agent.env import LocalEnv
from simp_agent.ai import AssistantMessage, Model, TextContent, ThinkingContent, ToolCall, UserMessage
from simp_agent.coding import make_tools
from simp_agent.coding.truncate import head
from simp_agent.plugins import RedactSecrets
from simp_agent.session import AgentSession

KEY = "sk-" + "b" * 30
DONE = AssistantMessage([TextContent("ok")])


class Rec(LocalEnv):
    def __init__(self):
        self.cmds = []

    async def exec(self, command, cwd, timeout, cancel, on_output=None):
        self.cmds.append(shlex.split(command))
        return 127, ""  # "missing": also exercise the fallback argv


async def tool(tmp_path, name, env=None, **args):
    async def upd(text):
        pass

    return await run_tool(make_tools(), ToolCall("c", name, args), ToolContext(asyncio.Event(), env or LocalEnv(), str(tmp_path), upd))


async def test_grep_find_option_injection(tmp_path):
    (tmp_path / "f.txt").write_text("hello\n")
    for name, args in [("grep", {"pattern": "x", "path": f"--pre=/usr/bin/touch"}), ("find", {"pattern": "*", "path": "-delete"})]:
        r = await tool(tmp_path, name, **args)
        assert r.is_error and "must not start with '-'" in r.content
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]
    env = Rec()
    await tool(tmp_path, "find", env, pattern="--exec=touch")
    await tool(tmp_path, "grep", env, pattern="--pre=touch")
    fd, find, rg, gr = env.cmds
    assert fd[fd.index("--") + 1] == "--exec=touch" and find[1] == "."
    assert rg[-2:] == ["--", "."] and gr[-2:] == ["--", "."]


async def test_prepare_arguments_error_is_tool_result(tmp_path):
    def bad(a):
        raise KeyError("x")

    t = AgentTool("t", "", {"type": "object"}, lambda a, c: "r", prepare_arguments=bad)
    r = await run_tool([t], ToolCall("c", "t", {}), ToolContext(asyncio.Event(), LocalEnv(), str(tmp_path), None))
    assert r.is_error and r.content.startswith("prepare_arguments failed")


def test_truncate_single_huge_line():
    assert "head -c" in head("x" * 60_000)


def redactor():
    p = RedactSecrets()
    p.setup(None, {"env": False})
    return p


def test_redact_context_all_fields():
    msgs = [AssistantMessage([ThinkingContent(f"t {KEY}", "sig"), ToolCall("id", "bash", {"command": f"curl -H 'Bearer {KEY}'"})]),
            UserMessage(f"u {KEY}")]
    out = redactor().context(msgs)
    assert KEY not in str(out) and KEY in str(msgs) and out[0].content[0].signature == "sig"


def fake(*replies, seen):
    it = iter(replies)

    async def stream(model, ctx, api_key=None):
        seen.append(ctx)
        yield {"type": "done", "message": next(it)}

    return stream


async def test_compaction_input_goes_through_context_hook():
    seen = []
    s = AgentSession(Model(), [], stream_fn=fake(DONE, seen=seen), system_prompt="s", plugins=[redactor()],
                     messages=[UserMessage(f"key {KEY} " + "x" * 4000), DONE, UserMessage("y" * 4000), DONE])
    s.compaction.keep_recent_tokens = 10
    await s.start()
    assert await s.compact()
    assert seen and KEY not in str(seen[0].messages)


async def test_tool_update_is_masked():
    async def run(args, ctx):
        await ctx.on_update(f"progress {KEY}")
        return "done"

    texts, seen = [], []
    call = AssistantMessage([ToolCall("c", "t", {})], stop_reason="tool_use")
    s = AgentSession(Model(), [AgentTool("t", "", {"type": "object"}, run)], stream_fn=fake(call, DONE, seen=seen),
                     system_prompt="s", plugins=[redactor()])
    s.subscribe(lambda e: e["type"] == "tool_execution_update" and texts.append(e["text"]))
    await s.prompt("go")
    assert texts == ["progress [REDACTED]"]


async def test_abort_while_waiting_for_approval():
    async def never(call):
        await asyncio.Event().wait()

    s = AgentSession(Model(), [AgentTool("bash", "", {"type": "object"}, lambda a, c: "r")], approve=never,
                     stream_fn=fake(AssistantMessage([ToolCall("c", "bash", {})], stop_reason="tool_use"), DONE, seen=[]),
                     system_prompt="s")
    task = asyncio.create_task(s.prompt("go"))
    await asyncio.sleep(0.05)
    s.abort()
    await asyncio.wait_for(task, 2)
