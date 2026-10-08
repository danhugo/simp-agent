from types import SimpleNamespace as NS

import openai

from simp_agent import ai
from simp_agent.agent import AgentTool, run_tool
from simp_agent.ai import AssistantMessage, Context, Model, TextContent, ToolCall, ToolResultMessage, UserMessage
from simp_agent.ai.providers import openai_completions as oc


def tc(index=None, id=None, name=None, args=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=args))


def ch(content=None, tool_calls=None, finish=None, usage=None):
    return NS(choices=[NS(delta=NS(content=content, tool_calls=tool_calls), finish_reason=finish)], usage=usage)


async def run(chunks, compat=None):
    async def gen():
        for c in chunks:
            yield c

    return [e async for e in oc.parse(gen(), compat or {})]


async def test_text_only():
    evs = await run([ch("Hel"), ch("lo", finish="stop")])
    assert [e["delta"] for e in evs if e["type"] == "text_delta"] == ["Hel", "lo"]
    m = evs[-1]["message"]
    assert evs[-1]["type"] == "done" and m.text() == "Hello" and m.stop_reason == "stop"


async def test_tool_call_split_and_usage_chunk():
    evs = await run([
        ch(tool_calls=[tc(0, "c1", "read", '{"pa')]),
        ch(tool_calls=[tc(0, None, None, 'th": ')]),
        ch(tool_calls=[tc(0, None, None, '"a"}')], finish="tool_calls"),
        NS(choices=[], usage=NS(prompt_tokens=7, completion_tokens=3)),
    ])
    m = evs[-1]["message"]
    assert m.tool_calls() == [ToolCall("c1", "read", {"path": "a"})] and m.stop_reason == "tool_use"
    assert m.usage == {"input": 7, "output": 3}


async def test_parallel_by_index_and_by_id():
    m = (await run([ch(tool_calls=[tc(0, "a", "x", "{}"), tc(1, "b", "y", '{"k"')]), ch(tool_calls=[tc(1, None, None, ":1}")], finish="tool_calls")]))[-1]["message"]
    assert [(c.id, c.arguments) for c in m.tool_calls()] == [("a", {}), ("b", {"k": 1})]
    m = (await run([ch(tool_calls=[tc(None, "a", "x", '{"k"')]), ch(tool_calls=[tc(None, "a", None, ":2}")]), ch(tool_calls=[tc(None, None, "z", "{}")], finish="tool_calls")]))[-1]["message"]
    calls = m.tool_calls()
    assert calls[0].arguments == {"k": 2} and calls[1].name == "z" and calls[1].id.startswith("call_")


async def test_finish_reasons():
    assert (await run([ch(tool_calls=[tc(0, "a", "x", "{}")], finish="stop")]))[-1]["message"].stop_reason == "tool_use"
    assert (await run([ch("x", finish="length")]))[-1]["message"].stop_reason == "length"
    e = (await run([ch("x", finish="content_filter")]))[-1]
    assert e["type"] == "error" and e["message"].error == "Provider finish_reason: content_filter"
    e = (await run([ch("x")]))[-1]
    assert e["type"] == "error" and e["message"].error == "Stream ended without finish_reason"
    assert (await run([ch("x")], {"supports_finish_reason": False}))[-1]["message"].stop_reason == "stop"
    assert (await run([ch(tool_calls=[tc(0, "a", "x", "{}")])], {"supports_finish_reason": False}))[-1]["message"].stop_reason == "tool_use"


async def test_bad_json_gives_validation_error():
    m = (await run([ch(tool_calls=[tc(0, "a", "t", '{"path": ')], finish="tool_calls")]))[-1]["message"]
    call = m.tool_calls()[0]
    assert call.arguments == {"_raw": '{"path": '}

    async def ex(args, cancel):
        return "ok"

    tool = AgentTool("t", "", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, ex)
    r = await run_tool([tool], call, None)
    assert r.is_error and "Invalid arguments" in r.content


def test_message_conversion():
    msgs = [
        UserMessage("hi"),
        AssistantMessage([TextContent("  "), ToolCall("a", "x", {"k": 1}), ToolCall("b", "y", {})], "tool_use"),
        ToolResultMessage("a", "x", "r1"),
        ToolResultMessage("b", "y", "r2"),
        AssistantMessage([TextContent("")]),
    ]
    out = oc.to_openai("sys", msgs)
    assert out[0] == {"role": "system", "content": "sys"} and out[1] == {"role": "user", "content": "hi"}
    assert out[2]["content"] is None and out[2]["tool_calls"][0]["function"] == {"name": "x", "arguments": '{"k": 1}'}
    assert [m["role"] for m in out[3:5]] == ["tool", "tool"] and out[4]["tool_call_id"] == "b"
    assert out[5] == {"role": "assistant", "content": ""}


async def test_dispatch_by_api(monkeypatch):
    seen = []

    async def fake(model, ctx):
        seen.append((model.api, ctx.messages))
        yield {"type": "done", "message": AssistantMessage()}

    monkeypatch.setattr(oc, "stream", fake)
    calls = AssistantMessage([ToolCall("a", "x", {})], "tool_use")
    [e async for e in ai.stream(Model(id="m", api="openai-completions"), Context("s", [UserMessage("u"), calls]))]
    assert seen[0][0] == "openai-completions"
    assert seen[0][1][-1].content == "No result provided"  # transform_messages ran before the provider


async def test_http_error_is_event(monkeypatch):
    class Boom:
        def __init__(self, **kw):
            self.chat = NS(completions=NS(create=self.create))

        async def create(self, **kw):
            raise openai.APIConnectionError(request=None)

    monkeypatch.setattr(openai, "AsyncOpenAI", Boom)
    evs = [e async for e in ai.stream(Model(id="m", api="openai-completions"), Context("s", [UserMessage("u")]))]
    assert evs[-1]["type"] == "error" and ai.is_retryable(evs[-1]["message"].error)
    assert ai.is_context_overflow("This model's maximum context length is 8192 tokens")
    assert ai.is_retryable("Rate limit reached") and ai.is_retryable("Error code: 502")


async def test_compat_params(monkeypatch):
    seen = []

    class Fake:
        def __init__(self, **kw):
            self.chat = NS(completions=NS(create=self.create))

        async def create(self, **kw):
            seen.append(kw)
            raise openai.APIConnectionError(request=None)

    monkeypatch.setattr(openai, "AsyncOpenAI", Fake)
    for compat in [{}, {"max_tokens_field": "max_completion_tokens", "reasoning_effort": "none", "include_usage": False}]:
        m = Model(id="m", api="openai-completions", compat=compat)
        [e async for e in ai.stream(m, Context("s", [UserMessage("u")]))]
    a, b = seen
    assert "max_tokens" in a and "stream_options" in a and "reasoning_effort" not in a
    assert b["max_completion_tokens"] == m.max_tokens and "max_tokens" not in b
    assert b["reasoning_effort"] == "none" and "stream_options" not in b


def test_cli_max_tokens(monkeypatch):
    import sys

    import pytest

    from simp_agent import cli

    seen = []

    async def fake_run(task, model, resume):
        seen.append(model)
        return 0

    monkeypatch.setattr(cli, "run", fake_run)
    for argv in (["x", "--max-tokens", "32000", "--api", "openai-completions", "--model", "m", "--context-window", "1000", "t"],
                 ["x", "--max-tokens", "32000", "t"], ["x", "t"]):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit):
            cli.main()
    assert [m.max_tokens for m in seen] == [32000, 32000, 8192]
