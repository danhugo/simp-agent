"""Session layer: owns an Agent and adds auto-compaction, overflow recovery, auto-retry and persistence.
No terminal or file assumptions: IO goes through env and store (pi coding-agent/src/core/agent-session.ts)."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import itertools
import os
from typing import Any, Callable, Protocol

from .. import ai
from ..agent import Agent, _emit_all, _maybe_await, api_key_opts
from ..agent.compaction import CompactionEntry, CompactionSettings, build_view, compact, estimate_tokens, should_compact
from ..agent.env import ExecutionEnv, LocalEnv
from ..ai import CustomEntry, Model, UserMessage
from ..coding import TOOLS, load_context_file
from ..coding import system_prompt as system_prompt_for


class SessionStore(Protocol):
    # a message, CompactionEntry or CustomEntry, called right away (crash safe). May be async (awaited).
    def append(self, entry) -> Any: ...

    def load(self) -> list: ...  # used by the app: AgentSession(messages=store.load())


class PluginAPI:
    """What a plugin can do with its session (pi ExtensionAPI)."""

    def __init__(self, session: "AgentSession", name: str):
        self._s, self.name = session, name

    def register_tool(self, tool) -> None:
        self.unregister_tool(tool.name)
        self._s.agent.tools.append(tool)

    def unregister_tool(self, name: str) -> None:
        self._s.agent.tools[:] = [t for t in self._s.agent.tools if t.name != name]

    def add_prompt_section(self, id: str, value, order: int = 100) -> None:
        self._s.add_prompt_section(id, value, order)

    def remove_prompt_section(self, id: str) -> None:
        self._s.remove_prompt_section(id)

    async def append_entry(self, type: str, data: dict) -> CustomEntry:
        return await self._s.append_entry(type, data)

    def send_message(self, text: str, mode: str = "steer"):
        """mode: steer | follow_up | prompt. prompt while idle starts a run (returns its task); while busy = follow_up."""
        if mode == "prompt" and not self._s.agent.is_streaming:
            return asyncio.ensure_future(self._s.prompt(text))
        (self._s.steer if mode == "steer" else self._s.follow_up)(text)

    def set_model(self, model: Model) -> None:
        self._s.agent.model = model

    def abort(self) -> None:
        self._s.abort()

    def get_messages(self) -> list:
        return self._s.messages

    @property
    def env(self) -> ExecutionEnv:
        return self._s.agent.env

    @property
    def cwd(self) -> str:
        return self._s.agent.cwd

    async def emit(self, type: str, data: dict | None = None) -> None:
        await self._s._emit({"type": type, "plugin": self.name, **(data or {})})


def plugin_name(p) -> str:
    return getattr(p, "name", type(p).__name__)


class AgentSession:
    def __init__(self, model: Model, tools: list | None = None, store: SessionStore | None = None,
                 env: ExecutionEnv | None = None, cwd: str | None = None, get_api_key: Callable[[str], Any] | None = None,
                 system_prompt: str | None = None, stream_fn: Callable = ai.stream, auto_compact: bool = True,
                 max_retries: int = 3, retry_base_delay: float = 2.0, approve: Callable[[ai.ToolCall], Any] | None = None,
                 messages: list | None = None, plugins: list = (), plugin_config: dict | None = None):
        self.store, self.auto_compact, self.compaction = store, auto_compact, CompactionSettings()
        self.max_retries, self.retry_base_delay = max_retries, retry_base_delay
        self.agent = Agent(self._build_prompt, model, list(TOOLS if tools is None else tools), stream_fn,
                           get_api_key=get_api_key, env=env or LocalEnv(), cwd=cwd or os.getcwd(), messages=messages,
                           prepare_next_turn=self._prepare, before_tool_call=self._before_tool_call,
                           after_tool_call=self._after_tool_call)
        # approval policy: approve(call) -> "allow" | "deny" | "always" (sync or async). None = allow everything.
        self.approve, self.needs_approval, self.always_allowed = approve, {"bash", "write", "edit"}, set()
        self.agent.subscribe(self._on_agent_event)
        self._subs = list()
        self._abort = asyncio.Event()
        self._sections = dict()  # id -> (order, seq, str | fn(ctx) -> str)
        self._seq = itertools.count()
        if system_prompt is not None:
            self.add_prompt_section("base", system_prompt, 0)
        else:  # coding prompt; the context file section is added on start (needs env IO)
            self.add_prompt_section("coding", lambda ctx: system_prompt_for(ctx["tools"], ctx["cwd"]), 0)
        self._default_prompt = system_prompt is None
        self.plugins, self.plugin_config = list(plugins), plugin_config or {}
        self._started = False

    # ---- prompt sections ----

    def add_prompt_section(self, id: str, value, order: int = 100) -> None:
        """value: str or fn(ctx) -> str (sync or async), rebuilt every turn. Sorted by (order, first add): stable."""
        seq = self._sections[id][1] if id in self._sections else next(self._seq)
        self._sections[id] = (order, seq, value)

    def remove_prompt_section(self, id: str) -> None:
        self._sections.pop(id, None)

    async def _build_prompt(self) -> str:
        a = self.agent
        ctx = {"tools": a.tools, "cwd": a.cwd, "model": a.model, "messages": a.messages}
        parts = list()
        for _, _, v in sorted(self._sections.values(), key=lambda x: x[:2]):
            text = await _maybe_await(v(ctx)) if callable(v) else v
            if text:
                parts.append(text)
        return "\n\n".join(parts)

    # ---- custom entries ----

    async def append_entry(self, type: str, data: dict) -> CustomEntry:
        """Persisted + replayed on resume, never sent to the LLM."""
        entry = CustomEntry(type, data)
        self.agent.messages.append(entry)
        if self.store:
            await _maybe_await(self.store.append(entry))
        await self._emit({"type": "message_end", "message": entry})
        return entry

    # ---- plugins (pi extensions runner) ----

    async def start(self) -> None:
        """Load the context file, run plugin setup(api, config), then session_start. Called by the first prompt."""
        if self._started:
            return
        self._started = True
        if self._default_prompt and (cf := await load_context_file(self.agent.env, self.agent.cwd)):
            self.add_prompt_section("context_file", f"# Project Context\n\n## {cf[0]}\n\n{cf[1]}", 10)
        for p in self.plugins:
            await self._hook(p, "setup", PluginAPI(self, plugin_name(p)), self.plugin_config.get(plugin_name(p), {}))
        for p in self.plugins:
            await self._hook(p, "session_start")

    async def shutdown(self) -> None:
        for p in self.plugins:
            await self._hook(p, "session_shutdown")

    async def _hook(self, p, hook: str, *args, isolate: bool = True):
        fn = getattr(p, hook, None)
        if fn is None:
            return None
        try:
            return await _maybe_await(fn(*args))
        except Exception as e:
            if not isolate:
                raise
            await _emit_all(self._subs, {"type": "plugin_error", "plugin": plugin_name(p), "hook": hook,
                                         "error": f"{type(e).__name__}: {e}"})
            return None

    @property
    def messages(self) -> list:
        return self.agent.messages

    def subscribe(self, fn: Callable[[dict], Any]) -> Callable[[], None]:
        self._subs.append(fn)
        return lambda: self._subs.remove(fn)

    async def _emit(self, e: dict) -> None:
        if e["type"] == "tool_execution_update":
            for p in self.plugins:  # e.g. mask secrets before the UI and logs see them
                if (r := await self._hook(p, "tool_update", e["call"], e["text"])) is not None:
                    e = {**e, "text": r}
        await _emit_all(self._subs, e)
        for p in self.plugins:
            await self._hook(p, "on_event", e)

    async def _on_agent_event(self, e: dict) -> None:
        if e["type"] == "message_end" and self.store:
            await _maybe_await(self.store.append(e["message"]))
        await self._emit(e)

    async def _before_tool_call(self, call, ctx) -> str | None:
        for p in self.plugins:  # first block wins; a raising hook blocks (fail closed)
            try:
                r = await self._hook(p, "tool_call", call, isolate=False) or {}
            except Exception as e:
                return f"blocked by plugin {plugin_name(p)} ({type(e).__name__}: {e})"
            if "block" in r:
                return f"blocked by plugin {plugin_name(p)}: {r['block']}"
            if "args" in r:
                call.arguments = r["args"]
        if self.approve is None or call.name not in self.needs_approval or call.name in self.always_allowed:
            return None
        ask = asyncio.ensure_future(_maybe_await(self.approve(call)))
        stop = asyncio.ensure_future(ctx.cancel.wait())
        await asyncio.wait([ask, stop], return_when=asyncio.FIRST_COMPLETED)
        stop.cancel()
        if not ask.done():  # aborted: a browser approval may never answer
            ask.cancel()
            return "aborted"
        answer = ask.result()
        if answer == "always":
            self.always_allowed.add(call.name)
        elif answer != "allow" or ctx.cancel.is_set():
            return "aborted" if ctx.cancel.is_set() else "denied"
        return None

    async def _after_tool_call(self, call, result, ctx):
        for p in self.plugins:  # partial overrides, merged in order
            if r := await self._hook(p, "tool_result", call, result):
                result = dataclasses.replace(result, **r)
        return result

    def steer(self, text: str) -> None:
        self.agent.steer(text)

    def follow_up(self, text: str) -> None:
        self.agent.follow_up(text)

    def abort(self) -> None:
        self._abort.set()
        self.agent.abort()

    async def prompt(self, text: str) -> list:
        await self.start()
        for p in self.plugins:
            r = await self._hook(p, "input", text) or {}
            if r.get("handled"):
                return []
            text = r.get("text", text)
        extra = list()
        for p in self.plugins:
            r = await self._hook(p, "before_agent_start", {"prompt": text, "messages": self.messages}) or {}
            extra += [UserMessage(m) if isinstance(m, str) else m for m in r.get("messages", [])]
        return await self._run(functools.partial(self.agent.prompt, text, extra))

    async def continue_(self) -> list:
        await self.start()
        return await self._run(self.agent.continue_)

    async def compact(self) -> bool:
        """Manual compaction. Summarize old history and append a CompactionEntry. Failure keeps history as is."""
        a = self.agent
        before = estimate_tokens(a.messages)
        await self._emit({"type": "compaction_start", "tokens_before": before})
        try:
            stream_fn = functools.partial(a.stream_fn, **await api_key_opts(a.get_api_key, a.model))
            entry = await compact(a.messages, a.model, stream_fn, self.compaction, self._context)
        except Exception as e:
            await self._emit({"type": "compaction_end", "error": str(e), "tokens_before": before, "tokens_after": before})
            return False
        a.messages.append(entry)
        if self.store:
            await _maybe_await(self.store.append(entry))
        await self._emit({"type": "message_end", "message": entry})
        await self._emit({"type": "compaction_end", "error": None, "tokens_before": before, "tokens_after": estimate_tokens(a.messages)})
        return True

    async def _prepare(self, messages: list) -> list:
        if self.auto_compact and should_compact(estimate_tokens(messages), self.agent.model, self.compaction):
            await self.compact()
        return await self._context(build_view(messages))

    async def _context(self, view: list) -> list:
        for p in self.plugins:  # chained: each gets the previous output
            view = await self._hook(p, "context", list(view)) or view
        return view

    async def _run(self, start) -> list:
        a = self.agent
        self._abort = asyncio.Event()
        new = await start()
        overflowed, attempt = False, 0
        while (last := a.messages[-1]).role == "assistant" and last.stop_reason == "error":
            if self.auto_compact and not overflowed and ai.is_context_overflow(last.error):
                # overflow: compact once and continue (error stays in history; the LLM view drops it)
                overflowed = True
                if not await self.compact():
                    break
            elif ai.is_retryable(last.error, last.error_kind) and attempt < self.max_retries:
                attempt += 1
                delay = self.retry_base_delay * 2 ** (attempt - 1)
                await self._emit({"type": "auto_retry_start", "attempt": attempt, "max_attempts": self.max_retries,
                                  "delay": delay, "error": last.error})
                try:
                    await asyncio.wait_for(self._abort.wait(), delay)
                    break  # aborted during backoff
                except TimeoutError:
                    pass
            else:
                break
            new += await a.continue_()
        if attempt:
            ok = not (a.messages[-1].role == "assistant" and a.messages[-1].stop_reason == "error")
            await self._emit({"type": "auto_retry_end", "success": ok, "attempt": attempt})
        return new
