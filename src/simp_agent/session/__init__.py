"""Session layer: owns an Agent and adds auto-compaction, overflow recovery, auto-retry and persistence.
No terminal or file assumptions: IO goes through env and store (pi coding-agent/src/core/agent-session.ts)."""

from __future__ import annotations

import asyncio
import functools
import os
from typing import Any, Callable, Protocol

from .. import ai
from ..agent import Agent, _emit_all, api_key_opts
from ..agent.compaction import CompactionEntry, CompactionSettings, build_view, compact, estimate_tokens, should_compact
from ..agent.env import ExecutionEnv, LocalEnv
from ..ai import Model
from ..coding import TOOLS, load_context_file, system_prompt


class SessionStore(Protocol):
    def append(self, entry) -> None: ...  # a message or CompactionEntry, called right away (crash safe)

    def load(self) -> list: ...


class AgentSession:
    def __init__(self, model: Model, tools: list | None = None, store: SessionStore | None = None,
                 env: ExecutionEnv | None = None, cwd: str | None = None, get_api_key: Callable[[str], Any] | None = None,
                 system_prompt: str | None = None, stream_fn: Callable = ai.stream, auto_compact: bool = True,
                 max_retries: int = 3, retry_base_delay: float = 2.0):
        self.store, self.auto_compact, self.compaction = store, auto_compact, CompactionSettings()
        self.max_retries, self.retry_base_delay = max_retries, retry_base_delay
        self._system_prompt = system_prompt  # None = built from tools + context file on first run
        self.agent = Agent("", model, TOOLS if tools is None else tools, stream_fn, get_api_key=get_api_key,
                           env=env or LocalEnv(), cwd=cwd or os.getcwd(), messages=store.load() if store else [],
                           prepare_next_turn=self._prepare)
        self.agent.subscribe(self._on_agent_event)
        self._subs = list()
        self._abort = asyncio.Event()

    @property
    def messages(self) -> list:
        return self.agent.messages

    def subscribe(self, fn: Callable[[dict], Any]) -> Callable[[], None]:
        self._subs.append(fn)
        return lambda: self._subs.remove(fn)

    async def _emit(self, e: dict) -> None:
        await _emit_all(self._subs, e)

    async def _on_agent_event(self, e: dict) -> None:
        if e["type"] == "message_end" and self.store:
            self.store.append(e["message"])
        await self._emit(e)

    def steer(self, text: str) -> None:
        self.agent.steer(text)

    def follow_up(self, text: str) -> None:
        self.agent.follow_up(text)

    def abort(self) -> None:
        self._abort.set()
        self.agent.abort()

    async def prompt(self, text: str) -> list:
        return await self._run(functools.partial(self.agent.prompt, text))

    async def continue_(self) -> list:
        return await self._run(self.agent.continue_)

    async def compact(self) -> bool:
        """Manual compaction. Summarize old history and append a CompactionEntry. Failure keeps history as is."""
        a = self.agent
        before = estimate_tokens(a.messages)
        await self._emit({"type": "compaction_start", "tokens_before": before})
        try:
            stream_fn = functools.partial(a.stream_fn, **await api_key_opts(a.get_api_key, a.model))
            summary, first_kept = await compact(a.messages, a.model, stream_fn, self.compaction)
        except Exception as e:
            await self._emit({"type": "compaction_end", "error": str(e), "tokens_before": before, "tokens_after": before})
            return False
        entry = CompactionEntry(summary, first_kept)
        a.messages.append(entry)
        if self.store:
            self.store.append(entry)
        await self._emit({"type": "message_end", "message": entry})
        await self._emit({"type": "compaction_end", "error": None, "tokens_before": before, "tokens_after": estimate_tokens(a.messages)})
        return True

    async def _prepare(self, messages: list) -> list:
        if self.auto_compact and should_compact(estimate_tokens(messages), self.agent.model, self.compaction):
            await self.compact()
        return build_view(messages)

    async def _run(self, start) -> list:
        a = self.agent
        if self._system_prompt is None:
            self._system_prompt = system_prompt(a.tools, a.cwd, await load_context_file(a.env, a.cwd))
        a.system_prompt = self._system_prompt
        self._abort = asyncio.Event()
        new = await start()
        overflowed, attempt = False, 0
        while (last := a.messages[-1]).role == "assistant" and last.stop_reason == "error":
            if self.auto_compact and not overflowed and ai.is_context_overflow(last.error):
                # overflow: compact once and continue (error stays in history; the LLM view drops it)
                overflowed = True
                if not await self.compact():
                    break
            elif ai.is_retryable(last.error) and attempt < self.max_retries:
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
