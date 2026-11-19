"""Workspace storage quota (design 2026-11-20). `[workspace] quota_mb` per user (default 10 GB, 0 = off; the admin can override it per
user), warn at `quota_warn` (0.8), block writes at `quota_block` (0.95) of it.

Used bytes live in the db (workspace_usage), so a sandbox start knows them without listing the bucket:
- server-side writes (Files panel upload/delete) update the row at once;
- sandbox writes go straight from s3fs to the bucket, so after a tool call the server recounts the user's prefix in the
  background, at most every `quota_recount_s` (a recount also fixes any drift).
Blocking means the E2B sandbox remounts /work read-only with a read-only credential (sandboxes/e2b.py) and uploads are
refused. Soft limit: one long command can still write past it before the recount; the 5% gap is for that."""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("simp_server")
MB = 2**20


class Quota:
    def __init__(self, settings: dict, files, db):
        self.settings, self.files, self.db = settings, files, db
        self.tasks: dict[str, asyncio.Task] = dict()  # user_id -> running recount
        self.last: dict[str, float] = dict()  # user_id -> monotonic time of the last recount start

    @property
    def _w(self) -> dict:  # read per call: workspace.quota_mb is a runtime setting
        return self.settings.get("workspace", dict())

    async def limit(self, user_id: str, row: dict | None = None) -> int:
        """Quota in bytes for this user, 0 = no quota."""
        row = row if row is not None else await self.db.ws_usage(user_id)
        mb = row["quota_mb"] if row and row["quota_mb"] is not None else self._w.get("quota_mb", 10240)
        return int(float(mb) * MB)

    async def usage(self, user_id: str) -> dict:
        """{used, quota, state}: state is off | ok | warn | full. Counts the store once if the db has no number yet."""
        row = await self.db.ws_usage(user_id)
        if row is None or row["counted"] is None:
            await self.recount(user_id)
            row = await self.db.ws_usage(user_id)
        used, quota = row["bytes"], await self.limit(user_id, row)
        return {"used": used, "quota": quota, "state": self.state(used, quota)}

    def state(self, used: int, quota: int) -> str:
        if not quota:
            return "off"
        if used >= quota * float(self._w.get("quota_block", 0.95)):
            return "full"
        return "warn" if used >= quota * float(self._w.get("quota_warn", 0.8)) else "ok"

    async def full(self, user_id: str) -> bool:
        return (await self.usage(user_id))["state"] == "full"

    async def fits(self, user_id: str, nbytes: int) -> bool:
        """Can a server-side write of `nbytes` go in without crossing the block line?"""
        u = await self.usage(user_id)
        return not u["quota"] or u["used"] + nbytes < u["quota"] * float(self._w.get("quota_block", 0.95))

    async def added(self, user_id: str, nbytes: int) -> None:
        await self.db.ws_add(user_id, nbytes)  # an overwrite counts twice until the next recount: errs on the safe side

    async def recount(self, user_id: str) -> int:
        self.last[user_id] = time.monotonic()
        n = await self.files.size(user_id)
        await self.db.ws_counted(user_id, n)
        return n

    def touch(self, user_id: str) -> None:
        """After a sandbox tool call: recount in the background, throttled per user. Never raises."""
        if time.monotonic() - self.last.get(user_id, -1e9) < float(self._w.get("quota_recount_s", 60)):
            return
        if (t := self.tasks.get(user_id)) and not t.done():
            return
        self.last[user_id] = time.monotonic()

        async def run():
            try:
                await self.recount(user_id)
            except Exception as e:
                log.warning("workspace recount failed: %s", e, extra={"user": user_id})
        self.tasks[user_id] = asyncio.create_task(run())

    def note(self, u: dict) -> str:
        """A line for the agent (appended to command output) when the workspace is nearly full or full."""
        gb = lambda n: f"{n / 2**30:.2f} GB"  # noqa: E731
        if u["state"] == "full":
            return (f"[workspace full: {gb(u['used'])} of {gb(u['quota'])} used. /work is read-only now. Tell the user "
                    "to delete files in the Files panel; writing will work again once there is room.]")
        if u["state"] == "warn":
            return (f"[workspace nearly full: {gb(u['used'])} of {gb(u['quota'])} used. Avoid writing large files to "
                    "/work; at 95% it becomes read-only.]")
        return ""
