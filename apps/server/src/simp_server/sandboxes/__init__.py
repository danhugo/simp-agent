import re
import shutil
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
        self.kind, self.db = kind, None
        self.price_vcpu_s = s.get("price_vcpu_s", 0.000014 if cloud else 0.0)
        self.price_gib_s = s.get("price_gib_s", 0.0000045 if cloud else 0.0)
        self.max_running = s.get("max_running", 10)  # E2B Hobby: 20 concurrent; keep headroom
        self.day_minutes = s.get("day_minutes", 240 if cloud else 0)  # 0 = no budget

    async def check(self, user_id: str, running: int) -> None:
        if running >= self.max_running:
            raise SandboxLimit(f"sandbox: {running} sandboxes are running, the server limit is {self.max_running}. "
                               "Try again in a few minutes.")
        if self.day_minutes and self.db is not None:
            from simp_server.budget import day_start
            used = await self.db.sandbox_seconds(user_id, day_start())
            if used >= self.day_minutes * 60:
                raise SandboxLimit(f"sandbox: daily compute budget of {self.day_minutes:g} minutes used up "
                                   f"({used / 60:.0f} min today). Commands and file tools are off until tomorrow; chat still works.")

    async def record(self, user_id: str, seconds: float, cpus: float, mem_gib: float) -> None:
        if self.db is None or seconds <= 0:
            return
        cost = seconds * (cpus * self.price_vcpu_s + mem_gib * self.price_gib_s)
        await self.db.add_usage(user_id, "", f"sandbox:{self.kind}", round(seconds), 0, cost=cost)
