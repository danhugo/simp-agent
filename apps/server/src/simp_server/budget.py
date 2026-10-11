"""Money budgets. Cost comes from per-profile prices (USD per 1M tokens); the check runs before every LLM call."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from simp_agent.ai import AssistantMessage


@dataclass
class Limits:
    user_day_usd: float = 2.0
    run_usd: float = 0.5


def limits(settings: dict) -> Limits:
    return Limits(**settings.get("budget", dict()))


def cost(profile: dict, usage: dict) -> float:
    return (usage.get("input", 0) * profile.get("price_in", 0) + usage.get("output", 0) * profile.get("price_out", 0)) / 1e6


def day_start(now: float | None = None) -> float:
    d = datetime.fromtimestamp(now if now is not None else time.time())
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def guard(stream_fn, check):
    async def fn(model, ctx, **kw):
        if msg := await check():
            yield {"type": "error", "message": AssistantMessage(stop_reason="error", error=msg, error_kind="budget")}
            return
        async for ev in stream_fn(model, ctx, **kw):
            yield ev

    return fn
