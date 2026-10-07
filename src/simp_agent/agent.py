"""Agent layer: the generic loop + a thin stateful Agent. Knows nothing about coding."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import jsonschema

from . import ai
from .ai import AssistantMessage, Context, Model, ToolResultMessage, UserMessage


@dataclass
class AgentTool(ai.Tool):
    execute: Callable[[dict, asyncio.Event], Awaitable[str]] | None = None  # (args, cancel) -> text


@dataclass
class LoopConfig:
    model: Model
    tools: list = field(default_factory=list)
    convert_to_llm: Callable[[list], list] = lambda m: m
    transform_context: Callable[[list], list] = lambda m: m  # compaction plugs in here later
    stream_fn: Callable = ai.stream  # swap for a fake in tests


async def run_tool(tools: list, call: ai.ToolCall, cancel: asyncio.Event) -> ToolResultMessage:
    def err(text):
        return ToolResultMessage(call.id, call.name, text, is_error=True)

    tool = next((t for t in tools if t.name == call.name), None)
    if tool is None:
        return err(f"Tool {call.name} not found")
    try:
        jsonschema.validate(call.arguments, tool.parameters)
    except jsonschema.ValidationError as e:
        return err(f"Invalid arguments for {call.name}: {e.message}")
    try:
        return ToolResultMessage(call.id, call.name, await tool.execute(call.arguments, cancel))
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")


def _aborted() -> AssistantMessage:
    return AssistantMessage(stop_reason="aborted", error="aborted")


async def agent_loop(
    system_prompt: str,
    messages: list,
    prompts: list,
    config: LoopConfig,
    emit: Callable[[dict], Any] = lambda e: None,
    cancel: asyncio.Event | None = None,
) -> list:
    """Run until the assistant stops calling tools. Mutates `messages`, returns the new ones."""
    cancel = cancel or asyncio.Event()
    new = list()

    def add(m):
        messages.append(m)
        new.append(m)
        emit({"type": "message_start", "message": m})
        emit({"type": "message_end", "message": m})

    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    for p in prompts:
        add(p)

    while True:
        llm_msgs = config.convert_to_llm(config.transform_context(messages))
        msg = _aborted()
        async for ev in config.stream_fn(config.model, Context(system_prompt, llm_msgs, config.tools)):
            if cancel.is_set():
                break
            emit({"type": "message_update", "event": ev})
            if ev["type"] in ("done", "error"):
                msg = ev["message"]
        add(msg)

        calls = msg.tool_calls()
        if msg.stop_reason in ("error", "aborted") or not calls:
            break
        for call in calls:
            if cancel.is_set():
                break
            emit({"type": "tool_execution_start", "call": call})
            result = await run_tool(config.tools, call, cancel)
            emit({"type": "tool_execution_end", "call": call, "result": result})
            add(result)
        if cancel.is_set():
            msg = _aborted()
            add(msg)
            break
        emit({"type": "turn_end", "message": msg})
        emit({"type": "turn_start"})

    emit({"type": "turn_end", "message": msg})
    emit({"type": "agent_end", "messages": new})
    return new


class Agent:
    def __init__(self, system_prompt: str, model: Model, tools: list, stream_fn: Callable = ai.stream):
        self.system_prompt, self.model, self.tools, self.stream_fn = system_prompt, model, tools, stream_fn
        self.messages = list()
        self.is_streaming = False
        self._subs = list()
        self._cancel = asyncio.Event()

    def subscribe(self, fn: Callable[[dict], Any]) -> Callable[[], None]:
        self._subs.append(fn)
        return lambda: self._subs.remove(fn)

    def abort(self) -> None:
        self._cancel.set()

    async def prompt(self, text: str) -> list:
        self._cancel = asyncio.Event()
        self.is_streaming = True
        try:
            cfg = LoopConfig(self.model, self.tools, stream_fn=self.stream_fn)
            emit = lambda e: [f(e) for f in self._subs]  # noqa: E731
            return await agent_loop(self.system_prompt, self.messages, [UserMessage(text)], cfg, emit, self._cancel)
        finally:
            self.is_streaming = False
