from __future__ import annotations

import argparse
import os
import time

import pytest

from simp_agent import cli
from simp_agent.agent import AgentTool, LoopConfig, agent_loop
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, UserMessage
from simp_agent.session import AgentSession

DONE = AssistantMessage([TextContent("ok")])


def fake(*replies):
    it = iter(replies)

    async def stream(model, ctx, api_key=None):
        yield {"type": "done", "message": next(it)}

    return stream


def bash_call(i="c1"):
    return AssistantMessage([ToolCall(i, "bash", {"command": "rm -rf /"})], stop_reason="tool_use")


def tools(ran):
    async def run(args, ctx):
        ran.append(args)
        return "ran"

    obj = {"type": "object", "properties": {"command": {"type": "string"}, "path": {"type": "string"}}}
    return [AgentTool("bash", "", obj, run), AgentTool("read", "", obj, run)]


async def test_before_tool_call_hook_in_loop():
    ran, seen = [], []

    def hook(call, ctx):
        seen.append(call.name)
        return "nope"

    msgs = []
    cfg = LoopConfig(Model(), tools(ran), stream_fn=fake(bash_call(), DONE), before_tool_call=hook)
    await agent_loop("s", msgs, [UserMessage("hi")], cfg)
    res = msgs[2]
    assert seen == ["bash"] and ran == [] and res.is_error and res.content == "User denied: nope"
    assert msgs[-1] is DONE  # the loop continued


def session(replies, approve, ran):
    return AgentSession(Model(), tools(ran), stream_fn=fake(*replies), system_prompt="s", approve=approve)


async def test_deny_skips_tool():
    ran = []
    s = session([bash_call(), DONE], lambda c: "deny", ran)
    await s.prompt("hi")
    assert ran == [] and s.messages[2].is_error and s.messages[2].content.startswith("User denied")


async def test_always_asks_once_and_read_never_asks():
    ran, asked = [], []
    read = AssistantMessage([ToolCall("r", "read", {"path": "x"})], stop_reason="tool_use")
    s = session([bash_call("a"), bash_call("b"), read, DONE], lambda c: asked.append(c.name) or "always", ran)
    await s.prompt("hi")
    assert asked == ["bash"] and len(ran) == 3


async def test_no_approve_allows_all():  # what --yes passes
    ran = []
    await session([bash_call(), DONE], None, ran).prompt("hi")
    assert len(ran) == 1


async def test_abort_while_asking_denies():
    ran = []

    def approve(c):
        s.abort()
        return "allow"

    s = session([bash_call(), DONE], approve, ran)
    await s.prompt("hi")
    assert ran == [] and s.messages[-1].stop_reason == "aborted"


def test_approval_answer_default_no():
    assert [cli.approval_answer(t) for t in ["", "n", "x", "y", "Y", "a"]] == ["deny"] * 3 + ["allow", "allow", "always"]


def test_route():
    assert cli.route("hi", False) == ("prompt", "hi")
    assert cli.route("hi", True) == ("steer", "hi")
    assert cli.route(">> later", True) == ("follow_up", "later")
    assert cli.route("/new", True) == ("command", "/new")
    assert cli.route("  ", True) == ("empty", "")


def test_interrupt_action():
    now = time.monotonic()
    assert cli.interrupt_action(True, None, now) == "abort"
    assert cli.interrupt_action(False, None, now) == "warn"
    assert cli.interrupt_action(False, now - 1, now) == "exit"
    assert cli.interrupt_action(False, now - 5, now) == "warn"


def args(**kw):
    base = dict(profile=None, api=None, model=None, base_url=None, context_window=None, max_tokens=None,
                max_tokens_field=None, reasoning_effort=None, no_include_usage=False)
    return argparse.Namespace(**{**base, **kw})


SETTINGS = {"default_profile": "luna", "profiles": {"luna": {
    "api": "openai-completions", "model": "openai/gpt-6-luna", "base_url": "http://x/v1", "context_window": 922000,
    "max_tokens": 32000, "compat": {"reasoning_effort": "none"}, "api_key_env": "LUNA_KEY", "api_key": "leak"}}}


def test_profile_merge_and_flag_override():
    m = cli.build_model(cli.resolve_config(SETTINGS, args()))
    assert (m.id, m.max_tokens, m.api_key_env, m.compat["reasoning_effort"]) == ("openai/gpt-6-luna", 32000, "LUNA_KEY", "none")
    assert "api_key" not in cli.resolve_config(SETTINGS, args())
    m = cli.build_model(cli.resolve_config(SETTINGS, args(max_tokens=100, model="other", reasoning_effort="low")))
    assert (m.id, m.max_tokens, m.compat["reasoning_effort"], m.base_url) == ("other", 100, "low", "http://x/v1")
    assert cli.build_model(cli.resolve_config({}, args())).api == "anthropic-messages"
    with pytest.raises(ValueError):
        cli.resolve_config(SETTINGS, args(profile="missing"))


def test_continue_is_cwd_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SESSIONS", tmp_path)
    a, b = cli.session_dir("/proj/a"), cli.session_dir("/proj/b")
    for i, (d, name) in enumerate([(a, "old"), (b, "other"), (a, "new")]):
        cli.JsonlStore(d / f"{name}.jsonl").append(UserMessage(name))
        os.utime(d / f"{name}.jsonl", (1000 + i, 1000 + i))
    assert cli.latest_session("/proj/a") == "new" and cli.latest_session("/proj/b") == "other"
    assert cli.latest_session("/proj/c") is None
