import asyncio
import re
import shutil
import time
from pathlib import Path


def valid_id(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError(f"bad id: {name!r}")
    return name


def user_root(workspaces: Path, legacy: Path, user_id: str, sid: str) -> Path:
    """The user's workspace dir, shared by all their sessions. One-time migration of old per-session dirs:
    sandboxes/<sid> (Stage 2) or workspaces/<sid> -> workspaces/<user_id>/<sid>/ (skipped once moved)."""
    valid_id(user_id), valid_id(sid)
    root = workspaces / user_id
    root.mkdir(parents=True, exist_ok=True)
    for old in (legacy / sid, workspaces / sid):
        if old.exists() and not (root / sid).exists():
            shutil.move(old, root / sid)
    return root


class SandboxLimit(RuntimeError):
    """A sandbox may not start now (concurrency limit or the user's daily compute budget). The message is for the
    agent and the UI as is."""


def gib(size: str | int | float) -> float:
    """Docker-style size ("1g", "512m", 2) -> GiB."""
    s = str(size).strip().lower()
    mult = {"k": 2**-20, "m": 2**-10, "g": 1, "t": 2**10}.get(s[-1:])
    return float(s[:-1]) * mult if mult else float(s) / 2**30


class Compute:
    """Design step 4: sandbox running seconds as usage rows with cost, a daily compute budget per user (minutes) and a
    limit on running sandboxes, checked before a sandbox starts or resumes. `db` (the server's SqliteStore) is set by
    create_app; without it nothing is recorded or checked except the concurrency limit."""

    def __init__(self, settings: dict, kind: str):
        s = settings.get("sandbox", dict())
        cloud = kind == "e2b"
        self.kind, self.db, self.billing = kind, None, (False, 1000.0)  # billing (enabled, points_per_usd): create_app
        self.price_vcpu_s = s.get("price_vcpu_s", 0.000014 if cloud else 0.0)
        self.price_gib_s = s.get("price_gib_s", 0.0000045 if cloud else 0.0)
        self.max_running = s.get("max_running", 10)  # E2B Hobby: 20 concurrent; keep headroom
        self.day_minutes = s.get("day_minutes", 240 if cloud else 0)  # 0 = no budget
        self.paused_ratio = float(s.get("paused_price_ratio", 0.1))  # paused time at this share of the running price; 0 = free
        self.start_lock = asyncio.Lock()  # one start decision at a time: the running count includes reserved slots

    @property
    def over_msg(self) -> str:
        return (f"sandbox: daily compute budget of {self.day_minutes:g} minutes used up. Commands and file tools are off "
                "until tomorrow; chat still works.")

    async def out_of_points(self, user_id: str) -> bool:
        return bool(self.billing[0] and self.db is not None
                    and (await self.db.credits(user_id, self.billing[1]))["balance"] <= 0)

    async def over_reason(self, user_id: str) -> str | None:
        """Why a running box must stop taking calls (paused on the next idle tick), or None."""
        if await self.out_of_points(user_id):
            from simp_server.budget import OUT_OF_POINTS
            return OUT_OF_POINTS
        if not self.day_minutes or self.db is None:
            return None
        from simp_server.budget import day_start
        if await self.db.sandbox_seconds(user_id, day_start()) >= self.day_minutes * 60:
            return self.over_msg
        return None

    async def over(self, user_id: str) -> bool:
        return await self.over_reason(user_id) is not None

    async def reserve(self, box, running) -> None:
        """Check the limits and take a running slot (box.starting = True; the caller clears it once the box runs or
        fails) under a global lock, so concurrent starts cannot pass max_running together. running() counts
        starting boxes."""
        async with self.start_lock:
            await self.check(box.user_id, running())
            box.starting = True

    async def check(self, user_id: str, running: int) -> None:
        if await self.out_of_points(user_id):
            from simp_server.budget import OUT_OF_POINTS
            raise SandboxLimit(OUT_OF_POINTS)
        if running >= self.max_running:
            raise SandboxLimit(f"sandbox: {running} sandboxes are running, the server limit is {self.max_running}. "
                               "Try again in a few minutes.")
        if self.day_minutes and self.db is not None:
            from simp_server.budget import day_start
            used = await self.db.sandbox_seconds(user_id, day_start())
            if used >= self.day_minutes * 60:
                raise SandboxLimit(f"sandbox: daily compute budget of {self.day_minutes:g} minutes used up "
                                   f"({used / 60:.0f} min today). Commands and file tools are off until tomorrow; chat still works.")

    async def paused(self, user_id: str, sbx_id: str, cpus: float, mem_gib: float) -> None:
        """A box was paused: remember when (persisted; a second call for the same box keeps the first time)."""
        if self.db is not None and self.paused_ratio > 0 and sbx_id:
            await self.db.add_pause(user_id, sbx_id, cpus, mem_gib)

    async def unpaused(self, sbx_id: str | None) -> None:
        """A paused box was resumed, killed or found gone: charge its paused time once (the row is popped)."""
        if self.db is None or self.paused_ratio <= 0 or not sbx_id or not (r := await self.db.pop_pause(sbx_id)):
            return
        seconds = max(0.0, time.time() - r["paused_at"])
        cost = self.paused_ratio * seconds * (r["cpus"] * self.price_vcpu_s + r["mem_gib"] * self.price_gib_s)
        if seconds > 0:
            await self.db.add_usage(r["user_id"], "", f"sandbox-paused:{self.kind}", round(seconds), 0, cost=cost)

    async def record(self, user_id: str, seconds: float, cpus: float, mem_gib: float) -> None:
        if self.db is None or seconds <= 0:
            return
        cost = seconds * (cpus * self.price_vcpu_s + mem_gib * self.price_gib_s)
        await self.db.add_usage(user_id, "", f"sandbox:{self.kind}", round(seconds), 0, cost=cost)
