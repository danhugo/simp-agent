"""Agent layer: the generic loop + a thin stateful Agent. Knows nothing about coding."""

from __future__ import annotations

import asyncio
import inspect
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


async def _emit_all(subs: list, e: dict) -> None:
    for f in subs:
        r = f(e)
        if inspect.isawaitable(r):
            await r


async def _stream(stream_fn, model, ctx, cancel: asyncio.Event):
    """Yield provider events; on cancel, close the provider stream (ends the HTTP request) and stop."""
    it = stream_fn(model, ctx).__aiter__()
    stop = asyncio.ensure_future(cancel.wait())
    try:
        while True:
            nxt = asyncio.ensure_future(it.__anext__())
            await asyncio.wait({nxt, stop}, return_when=asyncio.FIRST_COMPLETED)
            if not nxt.done():
                nxt.cancel()  # raises CancelledError inside the generator -> its `async with` closes the stream
                await asyncio.gather(nxt, return_exceptions=True)
                return
            try:
                yield nxt.result()
            except StopAsyncIteration:
                return
    finally:
        stop.cancel()
        await it.aclose()


async def agent_loop(
    system_prompt: str,
    messages: list,
    prompts: list,
    config: LoopConfig,
    emit: Callable[[dict], Any] = lambda e: None,  # sync or async
    cancel: asyncio.Event | None = None,
) -> list:
    """Run until the assistant stops calling tools. Mutates `messages`, returns the new ones."""
    cancel = cancel or asyncio.Event()
    new = list()

    async def send(e):
        await _emit_all([emit], e)

    async def add(m):
        messages.append(m)
        new.append(m)
        await send({"type": "message_start", "message": m})
        await send({"type": "message_end", "message": m})

    await send({"type": "agent_start"})
    await send({"type": "turn_start"})
    for p in prompts:
        await add(p)

    while True:
        llm_msgs = ai.transform_messages(config.convert_to_llm(config.transform_context(messages)))
        msg = partial = None
        async for ev in _stream(config.stream_fn, config.model, Context(system_prompt, llm_msgs, config.tools), cancel):
            await send({"type": "message_update", "event": ev})
            partial = ev.get("partial", partial)
            if ev["type"] in ("done", "error"):
                msg = ev["message"]
        if msg is None:  # aborted mid-stream: keep partial content
            msg = partial or _aborted()
            msg.stop_reason, msg.error = "aborted", "aborted"
        await add(msg)

        calls = msg.tool_calls()
        if msg.stop_reason in ("error", "aborted") or not calls:
            break
        for call in calls:
            if cancel.is_set():
                break
            if msg.stop_reason == "length":  # args may be cut off: never run them
                result = ToolResultMessage(call.id, call.name, "Tool call was truncated (max tokens); not executed", True)
            else:
                await send({"type": "tool_execution_start", "call": call})
                result = await run_tool(config.tools, call, cancel)
                await send({"type": "tool_execution_end", "call": call, "result": result})
            await add(result)
        if cancel.is_set():
            msg = _aborted()
            await add(msg)
            break
        await send({"type": "turn_end", "message": msg})
        await send({"type": "turn_start"})

    await send({"type": "turn_end", "message": msg})
    await send({"type": "agent_end", "messages": new})
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
        if self.is_streaming:
            raise RuntimeError("Agent is already processing a prompt; wait for it or call abort() first")
        self._cancel = asyncio.Event()
        self.is_streaming = True
        start = len(self.messages)
        try:
            cfg = LoopConfig(self.model, self.tools, stream_fn=self.stream_fn)
            emit = lambda e: _emit_all(self._subs, e)  # noqa: E731
            return await agent_loop(self.system_prompt, self.messages, [UserMessage(text)], cfg, emit, self._cancel)
        except Exception as e:  # e.g. a subscriber raised: end the run cleanly with an error message
            self.messages.append(AssistantMessage(stop_reason="error", error=f"{type(e).__name__}: {e}"))
            return self.messages[start:]
        finally:
            self.is_streaming = False
