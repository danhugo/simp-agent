"""E2BSandbox (design 2026-11-16 step 3): one E2B sandbox per USER, created lazily on the first tool call that needs it,
shared by the user's sessions. `[sandbox] kind = "e2b"`, needs `[workspace] store = "s3"`.

- /work is an s3fs mount of the user's bucket prefix (scoped credential from the store); every file op and command
  runs in the sandbox (one writer). The Files panel goes to the store, never here.
- /home/user (repos, libraries) is the sandbox's disk: packed to /work/.simp/home.tar.zst at pause, every
  `snapshot_every_s` and before kill, unpacked at create. Repos are also mirrored after each tool call (repos.py).
- Lifecycle: create (mount, restore home, restore repos) -> running -> idle `idle_pause_s` -> snapshot, pause ->
  next tool call -> resume, check mount, remount if dead. At `max_life_s` from create (Hobby: 1 h continuous cap) a
  sandbox with no foreground call running is snapshotted, synced, unmounted and killed; the next call creates a fresh
  one. Background processes do not keep it alive.
- Safety net: created with a provider-side timeout whose action is pause (lifecycle on_timeout="pause"), refreshed on
  use, so a dead server stops the bill. On server start, sandboxes tagged with our metadata are adopted (paused) or
  killed (duplicates).
- The template is built by apps/server/sandboxes/e2b_template.py."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shlex
import time
from datetime import datetime, timezone

from simp_agent.coding import SANDBOX_HINT
from simp_server import workspace
from simp_server.sandboxes import Compute, valid_id
from simp_server.sandboxes.docker import S3FS
from simp_server.sandboxes.repos import mirror_repos, restore_repos

log = logging.getLogger("simp_server")

REPOS, MIRRORS, SNAPSHOT = "/home/user/repos", "/work/.simp/repos", "/work/.simp/home.tar.zst"
SANDBOX_DIRS = ("/work", "/home/user", "/tmp")
HOME_DIRS = "repos .local .npm-global .venvs"

# $1 cap in bytes. Libraries are skipped when the archive is over the cap (they reinstall from manifests).
SNAPSHOT_SH = f"""cd /home/user || exit 0; d=$(ls -d {HOME_DIRS} 2>/dev/null); [ -n "$d" ] || exit 0
mkdir -p /work/.simp && tar -cf - $d 2>/dev/null | zstd -q -f -o /tmp/home.tar.zst || exit 1
if [ "$(stat -c %s /tmp/home.tar.zst)" -gt "$1" ]; then tar -cf - repos 2>/dev/null | zstd -q -f -o /tmp/home.tar.zst; fi
cp /tmp/home.tar.zst {SNAPSHOT} && rm -f /tmp/home.tar.zst && sync"""
RESTORE_SH = f"[ -f {SNAPSHOT} ] || exit 0; zstd -dc {SNAPSHOT} | tar -C /home/user -xf -"
MOUNT_SH = 'printf "%s\\n%s\\n%s\\n" "$K" "$S" "$T" | sh -c ' + shlex.quote(S3FS) + ' sh "$B" "$U" "$R"'


def _sdk():
    from e2b import AsyncSandbox
    return AsyncSandbox


def _gone(e: Exception) -> bool:
    from e2b.exceptions import SandboxNotFoundException, SandboxNotRunningException
    return isinstance(e, (SandboxNotFoundException, SandboxNotRunningException))


async def _run(sbx, command: str, cwd: str, timeout, cancel, on_output=None, user: str = "user", envs=None):
    """A command in its own process group (setsid; first output line is its pid, so a timeout/cancel kills the tree).
    -> (exit code or None when killed, output with stderr merged)."""
    chunks, head = list(), list()

    async def out(text: str):
        if not head:
            pid, _, text = text.partition("\n")
            head.append(pid.strip())
            if not text:
                return
        chunks.append(text)
        if on_output:
            await on_output(text)

    wrapped = "setsid -w sh -c 'echo $$; exec sh -c \"$0\" 2>&1' " + shlex.quote(command)
    h = await sbx.commands.run(wrapped, background=True, cwd=cwd, user=user, envs=envs, on_stdout=out, on_stderr=out,
                               timeout=0)
    wait = asyncio.ensure_future(h.wait())
    stop = asyncio.ensure_future(cancel.wait())
    done, _ = await asyncio.wait({wait, stop}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    stop.cancel()
    if wait not in done:
        with contextlib.suppress(Exception):
            if head and head[0].isdigit():
                await sbx.commands.run(f"kill -9 -- -{head[0]}", user=user, timeout=10)
            await h.kill()
        wait.cancel()
        await asyncio.gather(wait, return_exceptions=True)
        return None, "".join(chunks)
    try:
        return wait.result().exit_code, "".join(chunks)
    except Exception as e:  # CommandExitException: a non-zero exit
        if (code := getattr(e, "exit_code", None)) is None:
            raise
        return code, "".join(chunks)


class _Box:
    """A user's E2B sandbox state, shared by their sessions' envs. state: none | running | paused."""

    def __init__(self, user_id: str):
        self.user_id, self.sbx, self.sbx_id, self.state = user_id, None, None, "none"
        self.active, self.last = 0, time.monotonic()
        self.started = self.metered = self.snap_at = self.timeout_at = 0.0
        self.sessions: set[str] = set()
        self.lock = asyncio.Lock()

    async def exec(self, command, cwd, timeout, cancel, on_output=None, user="user"):  # raw: no start, no busy count
        return await _run(self.sbx, command, cwd, timeout, cancel, on_output, user=user)


class E2BEnv:
    """One per session (the session id names its WIP ref). Paths: relative or /work/... (the mount), /home/user/...,
    /tmp/...; nothing else."""

    root = "/work"

    def __init__(self, sandbox: "E2BSandbox", box: _Box, session_id: str):
        self.sandbox, self.box, self.session_id = sandbox, box, session_id
        self.used = False

    @contextlib.asynccontextmanager
    async def _use(self):
        self.box.active += 1  # before any await: stop_idle sees it even while we wait for the start lock
        try:
            await self.sandbox.ensure(self.box)
            self.used = True
            yield self.box.sbx
        finally:
            self.box.active -= 1
            self.box.last = time.monotonic()

    async def _call(self, fn):
        """fn(sbx) in the running sandbox; once more on a fresh/resumed one if it was paused or killed behind our back."""
        for attempt in (1, 2):
            try:
                async with self._use() as sbx:
                    return await fn(sbx)
            except Exception as e:
                if attempt == 2 or not _gone(e):
                    raise
                self.box.state = "paused" if self.box.sbx_id else "none"

    def _path(self, path: str) -> str:
        path = str(path)
        if not path.startswith("/") or path == "/work" or path.startswith("/work/"):
            return "/work/" + workspace.rel(path) if workspace.rel(path) else "/work"
        if "/../" in path + "/" or not any(path == d or path.startswith(d + "/") for d in SANDBOX_DIRS):
            raise PermissionError(f"path escapes root: {path}")
        return path

    async def read_bytes(self, path: str) -> bytes:
        p = self._path(path)

        async def read(sbx):
            from e2b.exceptions import NotFoundException
            try:
                return bytes(await sbx.files.read(p, format="bytes"))
            except NotFoundException as e:
                if _gone(e):
                    raise
                raise FileNotFoundError(path) from None
        return await self._call(read)

    async def read_file(self, path: str) -> str:
        return (await self.read_bytes(path)).decode()

    async def write_bytes(self, path: str, data: bytes) -> None:
        p = self._path(path)
        await self._call(lambda sbx: sbx.files.write(p, data))

    async def write_file(self, path: str, text: str) -> None:
        await self.write_bytes(path, text.encode())

    async def list(self, path: str) -> list[dict]:
        p = self._path(path)

        async def ls(sbx):
            from e2b.exceptions import NotFoundException
            try:
                entries = await sbx.files.list(p, depth=1)
            except NotFoundException as e:
                if _gone(e):
                    raise
                raise FileNotFoundError(path) from None
            out = [{"name": e.name, "is_dir": getattr(e.type, "value", e.type) == "dir",
                    "size": 0 if getattr(e.type, "value", e.type) == "dir" else e.size} for e in entries]
            return sorted(out, key=lambda e: e["name"])
        return await self._call(ls)

    async def exec(self, command, cwd, timeout, cancel, on_output=None) -> tuple[int | None, str]:
        cwd = self._path(cwd or ".")
        return await self._call(lambda sbx: _run(sbx, command, cwd, timeout, cancel, on_output))

    async def after_tool(self) -> None:
        """After each tool call that used the sandbox: sync (s3fs uploads closed files), mirror changed repos."""
        if not self.used:
            return
        try:
            await self.exec("sync", "/work", 60, asyncio.Event())
            await mirror_repos(self, REPOS, MIRRORS, self.session_id, cwd="/work")
        except Exception as e:
            log.warning("after-tool sync failed: %s", e, extra={"session": self.session_id})
        finally:
            self.used = False


class E2BSandbox:
    """Server Sandbox slot, same surface as DockerSandbox: open/close/stop_idle/close_all, plus start() (orphans) and
    the admin calls used by `simp-server sandboxes`. `store`, `keys` and `compute.db` are set by create_app."""

    kind = "e2b"
    prompt_hint = SANDBOX_HINT

    def __init__(self, settings: dict):
        s = settings.get("sandbox", dict())
        self.template = s.get("template", "simp-sandbox")
        self.tag = s.get("tag", "simp")  # metadata app=<tag>: which sandboxes this server owns
        self.idle_pause_s, self.max_life_s = s.get("idle_pause_s", 600), s.get("max_life_s", 3300)
        self.snapshot_every_s = s.get("snapshot_every_s", 900)
        self.snapshot_max_bytes = int(s.get("snapshot_max_mb", 2048)) * 2**20
        self.provider_timeout_s = s.get("provider_timeout_s", self.idle_pause_s + 300)
        self.cpus, self.memory_gib = float(s.get("cpus", 2)), float(s.get("memory_mb", 2048)) / 1024  # for cost
        self.store, self.keys, self.compute = None, dict(), Compute(settings, "e2b")
        self.sdk = None  # e2b.AsyncSandbox (tests put a fake here)
        self.envs: dict[str, E2BEnv] = dict()
        self.boxes: dict[str, _Box] = dict()

    def _api(self) -> dict:
        key = self.keys.get("E2B_API_KEY") or os.environ.get("E2B_API_KEY")
        return {"api_key": key} if key else dict()

    @property
    def _sdk(self):
        if self.sdk is None:
            self.sdk = _sdk()
        return self.sdk

    async def open(self, session_id: str, user_id: str) -> E2BEnv:
        valid_id(user_id), valid_id(session_id)
        if session_id in self.envs:
            return self.envs[session_id]
        box = self.boxes.setdefault(user_id, _Box(user_id))
        box.sessions.add(session_id)
        env = self.envs[session_id] = E2BEnv(self, box, session_id)
        return env

    def running(self) -> int:
        return sum(b.state == "running" for b in self.boxes.values())

    async def ensure(self, box: _Box) -> None:
        if box.state == "running":
            if time.monotonic() - box.timeout_at > 60:  # keep the provider-side pause timer ahead of us
                box.timeout_at = time.monotonic()
                with contextlib.suppress(Exception):
                    await box.sbx.set_timeout(self.provider_timeout_s)
            return
        async with box.lock:
            if box.state == "running":
                return
            await self.compute.check(box.user_id, self.running())
            resumed = False
            if box.state == "paused" and box.sbx_id:
                try:
                    box.sbx = await self._sdk.connect(box.sbx_id, timeout=self.provider_timeout_s, **self._api())
                    resumed = True
                except Exception as e:
                    log.warning("sandbox resume failed, creating a new one: %s", e, extra={"user": box.user_id})
                    with contextlib.suppress(Exception):
                        await self._sdk.kill(box.sbx_id, **self._api())
            if not resumed:
                box.sbx = await self._sdk.create(
                    template=self.template, timeout=self.provider_timeout_s, **self._api(),
                    metadata={"app": self.tag, "user_id": box.user_id},
                    lifecycle={"on_timeout": "pause", "auto_resume": False})
                box.started = time.monotonic()
            box.sbx_id, box.state = box.sbx.sandbox_id, "running"
            box.last = box.metered = box.snap_at = box.timeout_at = time.monotonic()
            try:
                if not resumed or not await self._mounted(box):
                    await self._mount(box)
                if not resumed:
                    await box.exec(RESTORE_SH, "/home/user", 600, asyncio.Event())
                    await restore_repos(box, REPOS, MIRRORS, cwd="/work")
            except Exception:
                await self._kill(box, snapshot=False)
                raise

    async def _mounted(self, box: _Box) -> bool:
        code, _ = await box.exec("mountpoint -q /work && ls /work >/dev/null", "/", 20, asyncio.Event())
        return code == 0

    async def _mount(self, box: _Box) -> None:
        """(Re)mount the user's prefix at /work with a fresh scoped credential (as root; the files belong to `user`)."""
        c = await self.store.mount_creds(box.user_id)
        envs = {"K": c["access_key"], "S": c["secret_key"], "T": c["session_token"] or "",
                "B": f"{c['bucket']}:/{c['prefix'].rstrip('/')}", "U": c["endpoint"], "R": c["region"]}
        await box.exec("umount -l /work 2>/dev/null; mkdir -p /work", "/", 30, asyncio.Event(), user="root")
        code, out = await _run(box.sbx, MOUNT_SH, "/", 60, asyncio.Event(), user="root", envs=envs)
        if code != 0 or not await self._mounted(box):
            raise RuntimeError(f"workspace mount failed: {out.strip()}")

    async def snapshot(self, box: _Box) -> None:
        """Home (repos, libraries) -> /work/.simp/home.tar.zst. Never raises."""
        try:
            code, out = await box.exec(f"sh -c {shlex.quote(SNAPSHOT_SH)} sh {self.snapshot_max_bytes}", "/home/user",
                                       900, asyncio.Event())
            if code:
                log.warning("home snapshot failed: %s", out.strip()[-500:], extra={"user": box.user_id})
        except Exception as e:
            log.warning("home snapshot failed: %s", e, extra={"user": box.user_id})
        box.snap_at = time.monotonic()

    async def meter(self, box: _Box, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if box.metered:
            await self.compute.record(box.user_id, max(0.0, now - box.metered), self.cpus, self.memory_gib)
        box.metered = now if box.state == "running" else 0.0

    async def _pause(self, box: _Box, snapshot: bool = True) -> None:
        async with box.lock:
            if box.state != "running":
                return
            if snapshot:
                await self.snapshot(box)
            try:
                await box.sbx.pause()
                box.state = "paused"
            except Exception as e:
                log.warning("sandbox pause failed, killing it: %s", e, extra={"user": box.user_id})
                with contextlib.suppress(Exception):
                    await box.sbx.kill()
                box.state, box.sbx_id = "none", None
            box.sbx = None
            await self.meter(box)

    async def _kill(self, box: _Box, snapshot: bool = True) -> None:
        """Max life (or a failed start): snapshot home, sync, unmount, kill. Caller holds no lock when snapshot=True."""
        if snapshot:
            await self.snapshot(box)
            with contextlib.suppress(Exception):
                await box.exec("sync; umount /work", "/", 60, asyncio.Event(), user="root")
        with contextlib.suppress(Exception):
            await box.sbx.kill()
        box.state, box.sbx, box.sbx_id = "none", None, None
        await self.meter(box)

    async def stop_idle(self, now: float | None = None) -> None:
        """Server tick: pause idle sandboxes, kill those at max life, snapshot home on schedule, meter running time.
        Never pauses or kills while a foreground tool call runs (active > 0)."""
        now = time.monotonic() if now is None else now
        for box in list(self.boxes.values()):
            if box.state != "running":
                continue
            if box.active == 0 and now - box.last >= self.idle_pause_s:
                log.info("sandbox idle pause", extra={"user": box.user_id})
                await self._pause(box)
            elif box.active == 0 and now - box.started >= self.max_life_s:
                log.info("sandbox max life: kill", extra={"user": box.user_id})
                async with box.lock:
                    await self._kill(box)
            else:
                if now - box.snap_at >= self.snapshot_every_s:
                    await self.snapshot(box)
                await self.meter(box, max(now, box.metered))

    async def close(self, session_id: str) -> None:
        env = self.envs.pop(session_id, None)
        if env:
            env.box.sessions.discard(session_id)
            if not env.box.sessions and env.box.active == 0:
                await self._pause(env.box)

    async def close_all(self) -> None:
        """Server shutdown: pause without a snapshot (the paused disk keeps home; there is little time)."""
        self.envs.clear()
        await asyncio.gather(*(self._pause(b, snapshot=False) for b in self.boxes.values()), return_exceptions=True)

    # ---- orphans and admin ----------------------------------------------------------------------------------------

    async def list_all(self) -> list[dict]:
        """Our sandboxes at the provider: [{id, user_id, state, started_at}]."""
        from e2b import SandboxQuery
        pg, out = self._sdk.list(query=SandboxQuery(metadata={"app": self.tag}), **self._api()), list()
        while pg.has_next:
            for i in await pg.next_items():
                out.append({"id": i.sandbox_id, "user_id": i.metadata.get("user_id", ""),
                            "state": str(getattr(i.state, "value", i.state)), "started_at": i.started_at})
        return out

    async def start(self) -> None:
        """Server start: adopt one sandbox per user (a running one is paused first: nobody uses it now), kill the
        rest. Paused sandboxes resume on the user's next tool call."""
        try:
            found = await self.list_all()
        except Exception as e:
            log.warning("listing e2b sandboxes failed: %s", e)
            return
        found.sort(key=lambda i: (i["state"] != "paused", -i["started_at"].timestamp()))
        for i in found:
            box = self.boxes.setdefault(i["user_id"], _Box(i["user_id"])) if i["user_id"] else None
            try:
                if box is None or box.sbx_id:
                    log.info("killing orphan sandbox %s", i["id"])
                    await self._sdk.kill(i["id"], **self._api())
                    continue
                if i["state"] == "running":
                    await self._sdk.pause(i["id"], **self._api())
                box.sbx_id, box.state = i["id"], "paused"
                box.started = time.monotonic() - (datetime.now(timezone.utc) - i["started_at"]).total_seconds()
            except Exception as e:
                log.warning("orphan sandbox %s: %s", i["id"], e)

    async def admin_kill(self, user_id: str) -> int:
        n = 0
        for i in await self.list_all():
            if i["user_id"] == user_id:
                await self._sdk.kill(i["id"], **self._api())
                n += 1
        return n

    async def admin_pause_all(self) -> int:
        n = 0
        for i in await self.list_all():
            if i["state"] == "running":
                await self._sdk.pause(i["id"], **self._api())
                n += 1
        return n
