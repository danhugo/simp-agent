from __future__ import annotations

import json
from types import SimpleNamespace as NS

from openai._models import construct_type
from openai.types.responses import ResponseStreamEvent

from simp_agent import ai
from simp_agent.agent import compaction
from simp_agent.ai import AssistantMessage, Model, TextContent, ThinkingContent, ToolCall, ToolResultMessage, UserMessage
from simp_agent.ai.providers import anthropic as an
from simp_agent.ai.providers import openai_completions as oc
from simp_agent.ai.providers import openai_responses as orr

LUNA = Model(id="luna", provider="openai", api="openai-responses", compat={"reasoning_effort": "low"})


async def agen(items):
    for i in items:
        yield i


def rev(**d):
    return construct_type(type_=ResponseStreamEvent, value=d)


RS = {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "think"}], "encrypted_content": "ENC"}
FC = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read", "arguments": '{"path": "a"}'}
MSG = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "phase": "commentary",
       "content": [{"type": "output_text", "text": "Hi", "annotations": []}]}


def completed(status="completed", reason=None):
    return rev(type=f"response.{status}", response={
        "status": status, "incomplete_details": {"reason": reason} if reason else None,
        "usage": {"input_tokens": 10, "output_tokens": 7, "output_tokens_details": {"reasoning_tokens": 5}}})


async def test_responses_stream_thinking_text_toolcall():
    evs = [e async for e in orr.parse(agen([
        rev(type="response.output_item.added", item={**RS, "summary": []}),
        rev(type="response.reasoning_summary_text.delta", delta="thi"),
        rev(type="response.reasoning_summary_text.delta", delta="nk"),
        rev(type="response.reasoning_summary_part.done"),
        rev(type="response.output_item.done", item=RS),
        rev(type="response.output_item.added", item={**MSG, "content": []}),
        rev(type="response.output_text.delta", delta="Hi"),
        rev(type="response.output_item.done", item=MSG),
        rev(type="response.output_item.added", item={**FC, "arguments": ""}),
        rev(type="response.function_call_arguments.delta", delta='{"path": "a"}'),
        rev(type="response.output_item.done", item=FC),
        completed(),
    ]))]
    assert [e["delta"] for e in evs if e["type"] == "thinking_delta"] == ["thi", "nk", "\n\n"]
    m = evs[-1]["message"]
    th, tx, tc = m.content
    assert th.thinking == "think" and json.loads(th.signature)["encrypted_content"] == "ENC"
    assert tx.text == "Hi" and json.loads(tx.signature) == {"v": 1, "id": "msg_1", "phase": "commentary"}
    assert tc == ToolCall("call_1|fc_1", "read", {"path": "a"})
    assert m.stop_reason == "tool_use" and m.usage == {"input": 10, "output": 7, "reasoning": 5}


async def test_responses_incomplete_max_tokens_is_length():
    evs = [e async for e in orr.parse(agen([completed("incomplete", "max_output_tokens")]))]
    assert evs[-1]["type"] == "done" and evs[-1]["message"].stop_reason == "length"
    evs = [e async for e in orr.parse(agen([completed("incomplete", "content_filter")]))]
    assert evs[-1]["type"] == "error"


def asst(content, model="luna", provider="openai", api="openai-responses"):
    return AssistantMessage(content, "tool_use", api=api, provider=provider, model=model)


def test_responses_replay_order_and_ids():
    sig = json.dumps(RS)
    tid = "call.1|fc_" + "x" * 80 + "_"
    msgs = [UserMessage("hi"), asst([ThinkingContent("", sig), TextContent("ok"), ToolCall(tid, "read", {})]),
            ToolResultMessage(tid, "read", "data")]
    items = orr.to_input(LUNA, "sys", ai.transform_messages(msgs, LUNA))
    assert [i.get("type", i.get("role")) for i in items] == ["developer", "user", "reasoning", "message", "function_call",
                                                             "function_call_output"]
    fc = items[4]
    assert fc["call_id"] == "call_1" and fc["id"] == "fc_" + "x" * 61 and items[3]["id"] == "msg_pi_1"
    assert items[5]["call_id"] == "call_1"
    other = orr.to_input(LUNA, "sys", ai.transform_messages([asst([ToolCall("c|fc_1", "read", {})], model="old")], LUNA))
    assert "id" not in other[1]
    foreign = orr.to_input(LUNA, "sys", [asst([ToolCall("c|item", "read", {})], provider="x", api="y")])
    assert foreign[1]["id"].startswith("fc_")
    plain = orr.request(Model(id="m", api="openai-responses"), ai.Context("s", []))
    assert plain["input"][0]["role"] == "system" and "reasoning" not in plain and "include" not in plain


def test_transform_thinking_same_vs_other_model():
    m = asst([ThinkingContent("", "SIG"), ThinkingContent("visible"), ThinkingContent("", "R", redacted=True), TextContent("t")])
    same = ai.transform_messages([m], LUNA)[0].content
    assert [type(c).__name__ for c in same] == ["ThinkingContent", "ThinkingContent", "ThinkingContent", "TextContent"]
    other = ai.transform_messages([m], Model(id="claude"))[0].content
    assert other == [TextContent("visible"), TextContent("t")]


async def test_completions_reasoning_content_to_thinking():
    def ch(**d):
        delta = NS(content=None, tool_calls=None, **d)
        return NS(choices=[NS(delta=delta, finish_reason=None)], usage=None)

    end = NS(choices=[NS(delta=NS(content="Hi", tool_calls=None), finish_reason="stop")], usage=None)
    evs = [e async for e in oc.parse(agen([ch(reasoning_content="hm"), ch(reasoning="m"), end]), {})]
    m = evs[-1]["message"]
    assert m.content == [ThinkingContent("hmm"), TextContent("Hi")]


async def test_anthropic_thinking_and_signature_delta():
    def blk(t, **k):
        return NS(type=t, **k)

    evs = [blk("content_block_start", content_block=blk("thinking")), blk("thinking", thinking="hm"),
           blk("signature", signature="SIG"), blk("content_block_stop", content_block=blk("thinking")),
           blk("content_block_start", content_block=blk("redacted_thinking", data="RD")),
           blk("content_block_stop", content_block=blk("redacted_thinking"))]
    msg = AssistantMessage()
    out = [e async for e in an.parse(agen(evs), msg)]
    assert [e["type"] for e in out] == ["thinking_start", "thinking_delta", "thinking_end", "thinking_start", "thinking_end"]
    assert msg.content == [ThinkingContent("hm", "SIG"), ThinkingContent("", "RD", redacted=True)]
    assert an._to_anthropic([msg])[0]["content"] == [{"type": "thinking", "thinking": "hm", "signature": "SIG"},
                                                     {"type": "redacted_thinking", "data": "RD"}]
    assert an.thinking_params(Model(compat={"thinking_budget": 2048}))["thinking"]["budget_tokens"] == 2048


def test_from_dict_old_and_new():
    old = {"role": "assistant", "content": [{"type": "text", "text": "x"}], "stop_reason": "stop",
           "usage": {"input": 1, "output": 2}, "error": None}
    assert ai.from_dict(old).content == [TextContent("x")]
    new = asst([ThinkingContent("t", "s"), TextContent("x", '{"id": "m"}')])
    assert ai.from_dict(json.loads(json.dumps(ai.to_dict(new)))) == new


def test_compaction_with_thinking():
    m = asst([ThinkingContent("a" * 400), TextContent("bb")])
    assert compaction.estimate(m) == 100
    assert "aaa" not in compaction.serialize_conversation([UserMessage("q"), m])
