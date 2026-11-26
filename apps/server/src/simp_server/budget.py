"""Money budgets. Cost comes from per-profile prices (USD per 1M tokens); the check runs before every LLM call."""

from __future__ import annotations

import time
import dataclasses
from dataclasses import dataclass
from datetime import datetime

from simp_agent.ai import AssistantMessage


@dataclass
class Limits:
    run_usd: float = 0.5  # per run; there is no daily cap (points, when billing is on, are the per-user limit)
    run_turns: int = 0  # LLM calls of the agent per run, 0 = no limit (run_usd still caps a run); side calls
    # (title, image look, web extract) don't count


def limits(settings: dict) -> Limits:
    keys = {f.name for f in dataclasses.fields(Limits)}  # old settings may still carry user_day_usd: ignored
    return Limits(**{k: v for k, v in settings.get("budget", dict()).items() if k in keys})


OUT_OF_POINTS = "budget: out of points. Ask the admin for more."


def billing(settings: dict) -> tuple[bool, float]:
    """[billing] enabled (default off: local / self-host, no points), points_per_usd."""
    b = settings.get("billing", dict())
    return bool(b.get("enabled", False)), float(b.get("points_per_usd", 1000))


# Soft limit: points are checked before an LLM call or sandbox start and charged after, so concurrent sessions
# (or a call in flight) can overdraw a little below 0. Accepted; the next call is refused.
async def out_of_points(settings: dict, store, user_id: str) -> str | None:
    on, rate = billing(settings)
    if on and (await store.credits(user_id, rate))["balance"] <= 0:
        return OUT_OF_POINTS
    return None


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
