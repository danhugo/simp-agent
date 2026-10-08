"""Agent layer: the generic loop + a thin stateful Agent. Knows nothing about coding."""

from __future__ import annotations

import asyncio
import functools
import inspect
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import jsonschema

from .. import ai
from ..ai import AssistantMessage, CompactionEntry, Context, Model, ToolResultMessage, UserMessage
from .compaction import build_view
from .env import ExecutionEnv, LocalEnv


@dataclass
class AgentTool(ai.Tool):
    execute: Callable[[dict, "ToolContext"], Awaitable[str]] | None = None  # (args, ctx) -> text


@dataclass
class ToolContext:
    cancel: asyncio.Event
    env: ExecutionEnv
    cwd: str
    on_update: Callable[[str], Awaitable[None]]  # emits tool_execution_update (progress for the UI)


async def _maybe_await(r):
    return await r if inspect.isawaitable(r) else r


async def _no_prepare(messages):
    return None


async def _view(messages):  # Agent default: honor CompactionEntry markers in history, never compact
    return build_view(messages)


@dataclass
class LoopConfig:
    model: Model
    tools: list = field(default_factory=list)
    convert_to_llm: Callable[[list], list] = lambda m: m
    transform_context: Callable[[list], list] = lambda m: m
    stream_fn: Callable = ai.stream  # swap for a fake in tests
    get_steering: Callable[[], list] = lambda: []  # messages typed while working; read after each tool batch
    get_follow_up: Callable[[], list] = lambda: []  # read only when the loop would otherwise stop
    # history -> LLM view (or None = use history). Called before every LLM call; must not mutate history.
    prepare_next_turn: Callable[[list], Awaitable[list | None]] = _no_prepare
    # provider -> key (sync or async), called before EVERY LLM call so OAuth tokens can refresh. None = provider env vars.
    get_api_key: Callable[[str], Any] | None = None
    env: ExecutionEnv = field(default_factory=LocalEnv)
    cwd: str = field(default_factory=os.getcwd)
    # (call, ctx) -> None to run the tool, or a deny reason string (pi beforeToolCall). Sync or async.
    before_tool_call: Callable[[ai.ToolCall, "ToolContext"], Any] | None = None


async def api_key_opts(get_api_key, model) -> dict:
    key = await _maybe_await(get_api_key(model.provider)) if get_api_key else None
    return {"api_key": key} if key else {}


async def run_tool(tools: list, call: ai.ToolCall, ctx: ToolContext) -> ToolResultMessage:
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
        return ToolResultMessage(call.id, call.name, await tool.execute(call.arguments, ctx))
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")


def _aborted() -> AssistantMessage:
    return AssistantMessage(stop_reason="aborted", error="aborted")


async def _emit_all(subs: list, e: dict) -> None:
    for f in subs:
        r = f(e)
        if inspect.isawaitable(r):
            await r


async def _stream(stream_fn, model, ctx, cancel: asyncio.Event, opts: dict):
    """Yield provider events; on cancel, close the provider stream (ends the HTTP request) and stop."""
    it = stream_fn(model, ctx, **opts).__aiter__()
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
    for p in prompts:
        await add(p)
    pending, has_calls, msg = config.get_steering(), True, None
    while True:
        while has_calls or pending:
            await send({"type": "turn_start"})
            for p in pending:
                await add(p)
            pending = []
            msg = await _llm_turn(system_prompt, messages, config, cancel, send, add)
            await add(msg)
            calls = msg.tool_calls()
            if msg.stop_reason in ("error", "aborted"):
                return await _end(send, msg, new)
            for call in calls:
                if cancel.is_set():
                    break
                if msg.stop_reason == "length":  # args may be cut off: never run them
                    result = ToolResultMessage(call.id, call.name, "Tool call was truncated (max tokens); not executed", True)
                else:
                    await send({"type": "tool_execution_start", "call": call})
                    on_update = functools.partial(lambda c, text: send({"type": "tool_execution_update", "call": c, "text": text}), call)
                    ctx = ToolContext(cancel, config.env, config.cwd, on_update)
                    deny = await _maybe_await(config.before_tool_call(call, ctx)) if config.before_tool_call else None
                    if deny is not None:
                        result = ToolResultMessage(call.id, call.name, f"User denied: {deny}", is_error=True)
                    else:
                        result = await run_tool(config.tools, call, ctx)
                    await send({"type": "tool_execution_end", "call": call, "result": result})
                await add(result)
            if cancel.is_set():
                msg = _aborted()
                await add(msg)
                return await _end(send, msg, new)
            await send({"type": "turn_end", "message": msg})
            has_calls, pending = bool(calls), config.get_steering()
        pending = config.get_follow_up()
        if not pending:
            break
    await send({"type": "agent_end", "messages": new})
    return new


async def _end(send, msg, new) -> list:
    await send({"type": "turn_end", "message": msg})
    await send({"type": "agent_end", "messages": new})
    return new


async def _llm_turn(system_prompt, messages, config, cancel, send, add) -> AssistantMessage:
    """prepare_next_turn hook -> steering poll (the hook may be slow) -> one LLM call."""
    view = await config.prepare_next_turn(messages)
    view = list(messages if view is None else view)
    for p in config.get_steering():
        await add(p)
        view.append(p)
    llm_msgs = ai.transform_messages(config.convert_to_llm(config.transform_context(view)))
    msg = partial = None
    opts = await api_key_opts(config.get_api_key, config.model)
    async for ev in _stream(config.stream_fn, config.model, Context(system_prompt, llm_msgs, config.tools), cancel, opts):
        await send({"type": "message_update", "event": ev})
        partial = ev.get("partial", partial)
        if ev["type"] in ("done", "error"):
            msg = ev["message"]
    if msg is None:  # aborted mid-stream: keep partial content
        msg = partial or _aborted()
        msg.stop_reason, msg.error = "aborted", "aborted"
    return msg


class Agent:
    """prompt() raises while a run is active: a UI should call steer() or follow_up() then.
    Queued messages survive abort(); they wait for the next prompt() or clear_queues()."""

    def __init__(self, system_prompt: str, model: Model, tools: list, stream_fn: Callable = ai.stream,
                 get_api_key: Callable[[str], Any] | None = None, env: ExecutionEnv | None = None, cwd: str | None = None,
                 messages: list | None = None, prepare_next_turn: Callable[[list], Awaitable[list | None]] = _view,
                 before_tool_call: Callable | None = None):
        self.system_prompt, self.model, self.tools, self.stream_fn = system_prompt, model, tools, stream_fn
        self.get_api_key, self.env, self.cwd = get_api_key, env or LocalEnv(), cwd or os.getcwd()
        self.prepare_next_turn, self.before_tool_call = prepare_next_turn, before_tool_call
        self.steering, self.follow_ups = list(), list()
        self.steering_mode = self.follow_up_mode = "one-at-a-time"  # or "all"
        self.messages = list(messages or [])  # saved history (CompactionEntry markers included)
        self.is_streaming = False
        self._subs = list()
        self._cancel = asyncio.Event()

    def subscribe(self, fn: Callable[[dict], Any]) -> Callable[[], None]:
        self._subs.append(fn)
        return lambda: self._subs.remove(fn)

    def steer(self, text: str) -> None:
        self.steering.append(UserMessage(text))

    def follow_up(self, text: str) -> None:
        self.follow_ups.append(UserMessage(text))

    def clear_queues(self) -> None:
        self.steering.clear()
        self.follow_ups.clear()

    def has_queued(self) -> bool:
        return bool(self.steering or self.follow_ups)

    @staticmethod
    def _take(queue: list, mode: str) -> list:
        n = len(queue) if mode == "all" else min(1, len(queue))
        out = queue[:n]
        del queue[:n]
        return out

    def abort(self) -> None:
        self._cancel.set()

    async def prompt(self, text: str) -> list:
        return await self._run([UserMessage(text)])

    async def continue_(self) -> list:
        """Run from the existing history with no new message (pi agentLoopContinue). A trailing error turn is
        skipped (the LLM view drops it), so a host can retry after an error."""
        skip = lambda m: isinstance(m, CompactionEntry) or (m.role == "assistant" and m.stop_reason == "error")  # noqa: E731
        last = next((m for m in reversed(self.messages) if not skip(m)), None)
        if last is None or last.role not in ("user", "tool_result"):
            raise ValueError(f"Cannot continue: last message must be user or tool_result, got {last and last.role}")
        return await self._run([])

    async def _run(self, prompts: list) -> list:
        if self.is_streaming:
            raise RuntimeError("Agent is already processing a prompt; wait for it or call abort() first")
        self._cancel = asyncio.Event()
        self.is_streaming = True
        start = len(self.messages)
        try:
            cfg = LoopConfig(
                self.model,
                self.tools,
                stream_fn=self.stream_fn,
                get_steering=lambda: self._take(self.steering, self.steering_mode),
                get_follow_up=lambda: self._take(self.follow_ups, self.follow_up_mode),
                prepare_next_turn=self.prepare_next_turn,
                get_api_key=self.get_api_key,
                env=self.env,
                cwd=self.cwd,
                before_tool_call=self.before_tool_call,
            )
            emit = lambda e: _emit_all(self._subs, e)  # noqa: E731
            return await agent_loop(self.system_prompt, self.messages, prompts, cfg, emit, self._cancel)
        except Exception as e:  # e.g. a subscriber raised: end the run cleanly with an error message
            self.messages.append(AssistantMessage(stop_reason="error", error=f"{type(e).__name__}: {e}"))
            return self.messages[start:]
        finally:
            self.is_streaming = False
