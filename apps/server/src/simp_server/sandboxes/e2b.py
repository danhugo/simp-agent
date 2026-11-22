"""E2BSandbox (design 2026-11-16 step 3): one E2B sandbox per USER, created lazily on the first tool call that needs it,
shared by the user's sessions. `[sandbox] kind = "e2b"`, needs `[workspace] store = "s3"`.

- /work is an s3fs mount of the user's bucket prefix (scoped credential from the store); every file op and command
  runs in the sandbox (one writer). The Files panel goes to the store, never here.
- /home/user is the sandbox's disk and is not saved: libraries are fixed in the template (toolset.py); repos are
  mirrored to /work after each tool call (repos.py). Old home snapshots (/work/.simp/home.tar.zst) are deleted at create.
- Lifecycle: create (mount, restore repos) -> running -> idle `idle_pause_s` -> pause ->
  next tool call -> resume, check mount, remount if dead. At `max_life_s` from create (Hobby: 1 h continuous cap) a
  sandbox with no foreground call running is synced, unmounted and killed; the next call creates a fresh
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
import urllib.parse
import uuid
from datetime import datetime, timezone

from simp_agent.coding import SANDBOX_HINT
from simp_server import policy, workspace
from simp_server.sandboxes import Compute, toolset, SandboxLimit, valid_id
from simp_server.sandboxes.docker import S3FS
from simp_server.sandboxes.repos import mirror_locked, remirror_if_failed, restore_repos

log = logging.getLogger("simp_server")
NO_NET = policy.NO_NET

REPOS, MIRRORS, SNAPSHOT = "/home/user/repos", "/work/.simp/repos", "/work/.simp/home.tar.zst"
SANDBOX_DIRS = ("/work", "/home/user", "/tmp")
# home snapshots are gone (fixed toolset): delete old ones, which count toward the workspace quota
CLEAN_SNAPSHOT_SH = f"rm -f {SNAPSHOT} {SNAPSHOT}.tmp"
SUDO_CHECK = "sudo -n true 2>/dev/null && echo SIMP_SUDO_OK; true"  # the template must not give `user` root
DENIED = ("Transport endpoint is not connected", "AccessDenied", "403 Forbidden")
CREDS_MARGIN_S = 300
# file contents cached on the sandbox disk, re-checked against s3fs's 5 s stat cache (a web upload still shows up).
# Measured on E2B + R2 (2026-11-22): repeated reads ~3-4x faster; writes unchanged (~1.7 s per small file).
S3FS_CACHE = "use_cache=/tmp/s3fs,del_cache,ensure_diskfree=256,parallel_count=10"
MOUNT_SH = 'printf "%s\\n%s\\n%s\\n" "$K" "$S" "$T" | sh -c ' + shlex.quote(S3FS) + ' sh "$B" "$U" "$R" "$O"'
# kill the old s3fs first: a lazy umount alone leaves it serving (and writing for) processes still inside /work
# then empty the bare mountpoint: a process still writing there (cwd or open dir in the old mount) would otherwise
# leave files in it and s3fs refuses a non-empty mountpoint; anything written in that gap is lost (it is not in R2)
UNMOUNT_SH = "sync; pkill -x s3fs; for i in 1 2 3 4 5; do pgrep -x s3fs >/dev/null || break; sleep 1; done; " \
             "umount -l /work 2>/dev/null; mkdir -p /work; mountpoint -q /work || find /work -mindepth 1 -delete"


def _sdk():
    from e2b import AsyncSandbox
    return AsyncSandbox


class SandboxLost(RuntimeError):
    """The sandbox was paused or killed while a command ran: it may have had effects, so it is never re-run."""


class _NotStarted(SandboxLost):
    """The sandbox was gone when commands.run was called (no start event). Behind a buffering proxy that is not proof
    the command never ran, so E2BEnv._call resumes the SAME sandbox and re-runs only if the command's start marker is
    missing there. Other callers of _run treat it as SandboxLost."""

    def __init__(self, marker: str, err: Exception):
        super().__init__(f"sandbox stopped before the command started: {err}")
        self.marker = marker


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

    # The pid also goes to a file: the stream (start event + output) can arrive only at the end (a buffering proxy,
    # e.g. Netskope), so the timeout clock starts before commands.run and the kill must not need the stream.
    pidfile = f"/tmp/.simp-{uuid.uuid4().hex}.pid"
    marker = pidfile[:-4] + ".started"  # kept after the command ends: proves it began (ponytail: 0-byte files in /tmp)
    # E2B ignores template envs at run time and resets PATH even when passed as envs, so export inside the command
    exports = " ".join(f"{k}={v}" for k, v in toolset.RUN_ENV.items())  # plain values: inside single quotes
    wrapped = (f"setsid -w sh -c 'touch {marker} || exit 97; export {exports}; echo $$ > {pidfile}; echo $$; exec sh -c \"$0\" 2>&1' "
               + shlex.quote(command)
               + f"; c=$?; rm -f {pidfile}; exit $c")

    started = list()

    async def start_and_wait():
        h = await sbx.commands.run(wrapped, background=True, cwd=cwd, user=user, envs=envs, on_stdout=out,
                                   timeout=0)  # stderr is merged inside; outside it is only the shell's "Killed" note
        started.append(h)
        return await h.wait()
    wait = asyncio.ensure_future(start_and_wait())
    stop = asyncio.ensure_future(cancel.wait())
    done, _ = await asyncio.wait({wait, stop}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    stop.cancel()
    if wait not in done:
        with contextlib.suppress(Exception):
            # the wrapper may not have written the pid file yet: wait up to 5 s for it
            await sbx.commands.run(f"for i in $(seq 50); do [ -s {pidfile} ] && break; sleep 0.1; done; "
                                   f"kill -9 -- -$(cat {pidfile}) 2>/dev/null; rm -f {pidfile}", user=user, timeout=15)
        await asyncio.wait({wait}, timeout=5)  # killed: the stream ends and flushes the output a proxy held back
        wait.cancel()
        await asyncio.gather(wait, return_exceptions=True)
        return None, "".join(chunks)
    try:
        return wait.result().exit_code, "".join(chunks)
    except Exception as e:  # CommandExitException: a non-zero exit
        if _gone(e):
            if not started:  # maybe never ran; behind a buffering proxy maybe it did: _call checks the marker
                raise _NotStarted(marker, e) from e
            raise SandboxLost(f"sandbox stopped while the command ran: {e}") from e
        if not started:  # could not start for another reason: nothing ran
            raise
        if (code := getattr(e, "exit_code", None)) is None:
            raise
        return code, "".join(chunks)


async def _began(sbx, marker: str) -> bool:
    """After resuming the same sandbox: did a _NotStarted command begin? Yes if its start marker exists, or if a process
    still has the marker path in its command line (frozen by the pause before `touch` ran, now waking up)."""
    base = marker.removesuffix(".started")
    pat = base.rsplit("/", 1)[1] + "[.]started"
    # never write the full marker path in this command: its own shell would then match the pgrep pattern
    r = await sbx.commands.run(f"m={base}; if [ -e \"$m.started\" ] || pgrep -f '{pat}' >/dev/null; then echo began; "
                               "else echo no; fi", user="user", timeout=15)
    return r.stdout.strip() != "no"  # anything unexpected counts as "began": never risk a second run


class _Box:
    """A user's E2B sandbox state, shared by their sessions' envs. state: none | running | stopping | paused.
    "stopping" (pause/kill in progress, under the lock): ensure() waits for the lock instead of using the box."""

    def __init__(self, user_id: str):
        self.user_id, self.sbx, self.sbx_id, self.state = user_id, None, None, "none"
        self.active, self.last = 0, time.monotonic()
        self.started = self.metered = self.timeout_at = 0.0
        self.sessions: set[str] = set()
        self.lock = asyncio.Lock()
        self.starting = self.over = False  # starting: holds a running slot (M8); over: daily budget used up
        self.mirror_lock, self.mirror_failed, self.mirror_sid, self.mirror_bg = asyncio.Lock(), False, None, None
        self.creds_until = 0.0  # monotonic time the mount credential expires (0 = none)
        self.ro = False  # /work mounted read-only (workspace full)
        self.noted = ""  # last quota state told to the agent ("warn" once; "full" on every command)

    async def exec(self, command, cwd, timeout, cancel, on_output=None, user="user"):  # raw: no start, no busy count
        return await _run(self.sbx, command, cwd, timeout, cancel, on_output, user=user)


class E2BEnv:
    """One per session (the session id names its WIP ref). Paths: relative or /work/... (the mount), /home/user/...,
    /tmp/...; nothing else."""

    root = "/work"

    def __init__(self, sandbox: "E2BSandbox", box: _Box, session_id: str):
        self.sandbox, self.box, self.session_id = sandbox, box, session_id
        self.used = False
        self.internal = False  # after_tool's own commands (sync, mirror): no quota note, the agent never sees them

    @contextlib.asynccontextmanager
    async def _use(self, need_s: float | None = None):
        self.box.active += 1  # before any await: stop_idle sees it even while we wait for the start lock
        try:
            if self.box.over:  # set by the tick (M8); cleared once the budget resets
                if msg := await self.sandbox.compute.over_reason(self.box.user_id):
                    raise SandboxLimit(msg)
                self.box.over = False
            await self.sandbox.ensure(self.box)
            await self.sandbox.fresh_creds(self.box, need_s)
            await self.sandbox.apply_quota(self.box)
            self.used = True
            yield self.box.sbx
        finally:
            self.box.active -= 1
            self.box.last = time.monotonic()

    async def _call(self, fn, need_s: float | None = None):
        """fn(sbx) in the running sandbox; once more on a fresh/resumed one if it was paused or killed behind our back
        before fn started anything (a _gone error; a command lost mid-run raises SandboxLost and is never re-run)."""
        pending = None  # (_NotStarted, sandbox id) of a first try that hit a paused sandbox
        for attempt in (1, 2):
            try:
                async with self._use(need_s) as sbx:
                    if pending and (sbx.sandbox_id != pending[1] or await _began(sbx, pending[0].marker)):
                        raise SandboxLost(f"{pending[0]}; it may have run, so it is not run again")  # new box: unknown
                    return await fn(sbx)
            except _NotStarted as e:
                if self.box.state == "running":
                    self.box.state = "paused" if self.box.sbx_id else "none"
                if attempt == 2:
                    raise
                pending = (e, self.box.sbx_id)
            except SandboxLost:
                if self.box.state == "running":
                    self.box.state = "paused" if self.box.sbx_id else "none"
                raise
            except Exception as e:
                if attempt == 2 or not _gone(e):
                    raise
                if self.box.state == "running":
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

        async def write(sbx):
            if self.box.ro and (p == "/work" or p.startswith("/work/")):
                raise PermissionError(await self.sandbox.quota_note(self.box) or "workspace full: /work is read-only")
            return await sbx.files.write(p, data)
        await self._call(write)

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
        code, out = await self._call(lambda sbx: _run(sbx, command, cwd, timeout, cancel, on_output), timeout)
        self.sandbox.check_denied(self.box, out)
        if not self.internal and (note := await self.sandbox.quota_note(self.box)):
            out = f"{out.rstrip()}\n{note}" if out.strip() else note
        return code, out

    async def after_tool(self) -> None:
        """After each tool call that used the sandbox: sync (s3fs uploads closed files), mirror changed repos."""
        if not self.used:
            return
        self.internal = True
        try:
            await self.exec("sync", "/work", 60, asyncio.Event())
            if self.sandbox.quota is not None:
                self.sandbox.quota.touch(self.box.user_id)  # background recount of the bucket prefix, throttled
            if not self.box.ro:  # read-only /work: the mirror fails; it is retried before a kill (remirror_if_failed)
                await mirror_locked(self, self.box, REPOS, MIRRORS, self.session_id, cwd="/work")
            else:
                self.box.mirror_failed = True
        except Exception as e:
            log.warning("after-tool sync failed: %s", e, extra={"session": self.session_id})
        finally:
            self.used = self.internal = False


class E2BSandbox:
    """Server Sandbox slot, same surface as DockerSandbox: open/close/stop_idle/close_all, plus start() (orphans) and
    the admin calls used by `simp-server sandboxes`. `store`, `keys` and `compute.db` are set by create_app."""

    kind = "e2b"
    prompt_hint = SANDBOX_HINT

    def __init__(self, settings: dict):
        s = settings.get("sandbox", dict())
        self.template = s.get("template", "simp-sandbox")
        # egress: "allowlist" (default) = only `egress_allow` + the workspace endpoint; "open" = no filter (dev)
        self.egress, self.egress_allow = s.get("egress", "allowlist"), list(s.get("egress_allow", []))
        self.toolset_line = toolset.prompt_list(bool(s.get("office")))  # named in policy deny reasons
        fixed = f"{self.toolset_line} Libraries are fixed: do not install packages."
        self.prompt_hint = " ".join([SANDBOX_HINT, fixed, *([] if self.egress == "open" else [NO_NET])])
        self.tag = s.get("tag", "simp")  # metadata app=<tag>: which sandboxes this server owns
        self.idle_pause_s, self.max_life_s = s.get("idle_pause_s", 600), s.get("max_life_s", 3300)
        self.provider_timeout_s = s.get("provider_timeout_s", self.idle_pause_s + 300)
        self.cpus, self.memory_gib = float(s.get("cpus", 2)), float(s.get("memory_mb", 2048)) / 1024  # for cost
        self.store, self.keys, self.compute = None, dict(), Compute(settings, "e2b")
        self.quota = None  # quota.Quota, set by create_app; None = no workspace quota
        self.sdk = None  # e2b.AsyncSandbox (tests put a fake here)
        self.envs: dict[str, E2BEnv] = dict()
        self.boxes: dict[str, _Box] = dict()

    def _network(self) -> dict | None:
        """Outbound allowlist: the sandbox reaches only the workspace store (s3fs) and `egress_allow`; web access goes
        through the server's web tools. Hosts are matched by name. DNS (8.8.8.8) stays open: a very slow channel."""
        if self.egress == "open":
            return None
        host = urllib.parse.urlsplit(getattr(self.store, "mount_endpoint", "") or "").hostname
        if not host:  # deny-all with no store host would leave /work unmountable with an obscure s3fs error
            raise RuntimeError("sandbox egress allowlist needs the workspace endpoint ([workspace] endpoint or "
                               "mount_endpoint); set [sandbox] egress = \"open\" only for local dev")
        return {"allow_out": [*self.egress_allow, *([host] if host else [])], "deny_out": ["0.0.0.0/0"]}

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
        return sum(b.state in ("running", "stopping") or b.starting for b in self.boxes.values())

    async def _refresh_timeout(self, box: _Box, now: float) -> None:
        """Keep the provider-side pause timer ahead of us (on use, and in the tick while a call runs: M1)."""
        if box.sbx is not None and now - box.timeout_at > 60:
            box.timeout_at = now
            with contextlib.suppress(Exception):
                await box.sbx.set_timeout(self.provider_timeout_s)

    async def ensure(self, box: _Box) -> None:
        if box.state == "running":  # "stopping" falls through to the lock: wait for the pause/kill, then resume
            await self._refresh_timeout(box, time.monotonic())
            return
        async with box.lock:
            if box.state == "running":
                return
            await self.compute.reserve(box, self.running)  # M8: slot held (box.starting) until running or failed
            try:
                await self._start(box)
            finally:
                box.starting = False

    async def _start(self, box: _Box) -> None:
        resumed = False
        if box.state == "paused" and box.sbx_id:
            await self.compute.unpaused(box.sbx_id)  # paused time ends now: resumed, or killed below
            try:
                box.sbx = await self._sdk.connect(box.sbx_id, timeout=self.provider_timeout_s, **self._api())
                resumed = True
            except Exception as e:
                log.warning("sandbox resume failed, creating a new one: %s", e, extra={"user": box.user_id})
                if box.mirror_failed:
                    log.error("RECREATING SANDBOX after a FAILED repo mirror: repo changes since the last good "
                              "mirror are lost", extra={"user": box.user_id})
                with contextlib.suppress(Exception):
                    await self._sdk.kill(box.sbx_id, **self._api())
        if not resumed:
            box.sbx = await self._sdk.create(
                template=self.template, timeout=self.provider_timeout_s, **self._api(),
                metadata={"app": self.tag, "user_id": box.user_id, "egress": self.egress,
                          "template": self.template},
                lifecycle={"on_timeout": "pause", "auto_resume": False}, **({"network": n} if (n := self._network()) else {}))
            box.started = time.monotonic()
            box.mirror_failed = False
        box.sbx_id, box.state = box.sbx.sandbox_id, "running"
        box.last = box.metered = box.timeout_at = time.monotonic()
        try:
            if not resumed or not await self._mounted(box):
                await self._mount(box)
            if not resumed:
                _, out = await box.exec(SUDO_CHECK, "/", 20, asyncio.Event())
                if "SIMP_SUDO_OK" in out:
                    raise RuntimeError("e2b template gives `user` passwordless sudo: rebuild it with "
                                       "apps/server/sandboxes/e2b_template.py")
                await box.exec(CLEAN_SNAPSHOT_SH, "/home/user", 600, asyncio.Event())
                await restore_repos(box, REPOS, MIRRORS, cwd="/work")
        except Exception:
            await self._kill(box, finalize=False)
            raise

    async def _mounted(self, box: _Box) -> bool:
        code, _ = await box.exec("mountpoint -q /work && ls /work >/dev/null", "/", 20, asyncio.Event())
        return code == 0

    async def _mount(self, box: _Box, ro: bool | None = None) -> None:
        """(Re)mount the user's prefix at /work with a fresh scoped credential (as root; the files belong to `user`).
        Every mount path comes here, so a full workspace is always mounted read-only, with a read-only credential."""
        ro = await self._want_ro(box) if ro is None else ro
        c = await self.store.mount_creds(box.user_id, read_only=ro)
        box.creds_until = time.monotonic() + c["expires_in"] if c.get("expires_in") else 0.0
        envs = {"K": c["access_key"], "S": c["secret_key"], "T": c["session_token"] or "",
                "B": f"{c['bucket']}:/{c['prefix'].rstrip('/')}", "U": c["endpoint"], "R": c["region"],
                "O": ("ro," if ro else "") + "nonempty," + S3FS_CACHE}  # nonempty: see UNMOUNT_SH (a writer can race the cleanup)
        await box.exec(UNMOUNT_SH, "/", 30, asyncio.Event(), user="root")
        code, out = await _run(box.sbx, MOUNT_SH, "/", 60, asyncio.Event(), user="root", envs=envs)
        if code != 0 or not await self._mounted(box):
            raise RuntimeError(f"workspace mount failed: {out.strip()}")
        box.ro = ro

    async def _want_ro(self, box: _Box) -> bool:
        if self.quota is None:
            return False
        try:
            return await self.quota.full(box.user_id)
        except Exception as e:  # a failed count must not stop the sandbox: keep the current mode
            log.warning("workspace quota check failed: %s", e, extra={"user": box.user_id})
            return box.ro

    async def apply_quota(self, box: _Box) -> None:
        """Before a call (and on the idle tick): switch /work to read-only once the workspace is full, back to
        read-write once there is room. Only when no other call uses the mount (like fresh_creds)."""
        want = await self._want_ro(box)
        if want == box.ro:
            return
        async with box.lock:
            if box.state != "running" or box.active > 1 or want == box.ro:
                return  # another call is in /work: the next call (or tick) switches
            log.info("workspace %s: remounting /work %s", "full" if want else "has room", "read-only" if want else
                     "read-write", extra={"user": box.user_id})
            await self._mount(box, want)

    async def quota_note(self, box: _Box) -> str:
        if self.quota is None:
            return ""
        try:
            u = await self.quota.usage(box.user_id)
        except Exception:
            return ""
        if u["state"] == "full" or (u["state"] == "warn" and box.noted != "warn"):
            box.noted = u["state"]
            return self.quota.note(u)
        box.noted = u["state"] if u["state"] == "warn" else ""
        return ""

    async def meter(self, box: _Box, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if box.metered:
            await self.compute.record(box.user_id, max(0.0, now - box.metered), self.cpus, self.memory_gib)
        box.metered = now if box.state == "running" else 0.0

    def check_denied(self, box: _Box, out: str) -> None:
        if any(m in out for m in DENIED):
            left = box.creds_until - time.monotonic() if box.creds_until else None
            log.error("WORKSPACE MOUNT DENIED (s3fs 403 / dead mount) for user %s; credential expires in %s s",
                      box.user_id, None if left is None else round(left), extra={"user": box.user_id})

    async def fresh_creds(self, box: _Box, need_s: float | None) -> None:
        """Review M2: never start a call that would outlive the mount credential (STS: at most the role's max
        session, 1 h when chained; max_life_s does not bound a long call). If it expires within the call's timeout
        (or CREDS_MARGIN_S), take a fresh one and remount first, when no other call uses the mount."""
        if not box.creds_until or box.creds_until - time.monotonic() > max(need_s or 0, CREDS_MARGIN_S):
            return
        async with box.lock:
            if box.state != "running" or box.creds_until - time.monotonic() > max(need_s or 0, CREDS_MARGIN_S):
                return
            if box.active > 1:
                raise SandboxLimit("sandbox: the workspace credential is about to expire and another command is still "
                                   "running; try again when it ends.")
            log.info("refreshing workspace mount credential", extra={"user": box.user_id})
            await box.exec("sync", "/work", 60, asyncio.Event())
            await self._mount(box)

    async def _pause(self, box: _Box, idle: bool = False) -> None:
        """idle=True (tick, close): only if no call is active once both locks are held (C3). The mirror lock first:
        a background mirror finishes before the pause (M7)."""
        async with box.mirror_lock, box.lock:
            if box.state != "running" or idle and box.active:
                return
            box.state = "stopping"  # before any await: a new call waits on box.lock, then resumes
            try:
                await box.sbx.pause()
                box.state = "paused"
                await self.compute.paused(box.user_id, box.sbx_id, self.cpus, self.memory_gib)
            except Exception as e:
                log.warning("sandbox pause failed, killing it: %s", e, extra={"user": box.user_id})
                if box.mirror_failed:
                    log.error("KILLING SANDBOX after a FAILED repo mirror", extra={"user": box.user_id})
                with contextlib.suppress(Exception):
                    await box.sbx.kill()
                box.state, box.sbx_id = "none", None
            box.sbx = None
            await self.meter(box)

    async def _kill(self, box: _Box, finalize: bool = True) -> None:
        """Max life (or a failed start): retry a failed mirror, sync, unmount, kill (finalize=False: just kill). Caller
        holds box.lock (and box.mirror_lock when finalize=True)."""
        box.state = "stopping"
        if finalize and box.ro:  # full workspace: let the last repo mirror through, nobody else can write
            with contextlib.suppress(Exception):
                await box.exec("pkill -KILL -u user; true", "/", 30, asyncio.Event(), user="root")
                await self._mount(box, ro=False)
        if finalize:
            with contextlib.suppress(Exception):
                await remirror_if_failed(box, REPOS, MIRRORS)
            with contextlib.suppress(Exception):
                await box.exec("sync; umount /work", "/", 60, asyncio.Event(), user="root")
        with contextlib.suppress(Exception):
            await box.sbx.kill()
        box.state, box.sbx, box.sbx_id = "none", None, None
        await self.meter(box)

    async def _kill_idle(self, box: _Box) -> None:
        async with box.mirror_lock, box.lock:
            if box.state == "running" and not box.active:  # C3: re-checked under the locks
                await self._kill(box)

    async def stop_idle(self, now: float | None = None) -> None:
        """Server tick: pause idle sandboxes, kill those at max life, meter running time.
        Never pauses or kills while a foreground tool call runs (active > 0)."""
        now = time.monotonic() if now is None else now
        for box in list(self.boxes.values()):
            if box.state != "running":
                continue
            if box.active == 0 and (now - box.last >= self.idle_pause_s or box.over):
                log.info("sandbox idle pause", extra={"user": box.user_id})
                await self._pause(box, idle=True)
            elif box.active == 0 and now - box.started >= self.max_life_s:
                log.info("sandbox max life: kill", extra={"user": box.user_id})
                await self._kill_idle(box)
            else:
                if box.active:  # M1: a long call must not hit the provider-side pause timer
                    await self._refresh_timeout(box, now)
                await self.meter(box, max(now, box.metered))
                if box.active == 0 and box.creds_until and box.creds_until - time.monotonic() < 2 * CREDS_MARGIN_S:
                    try:
                        await self.fresh_creds(box, 2 * CREDS_MARGIN_S)  # M2: refresh at an idle point
                    except Exception as e:
                        log.error("workspace credential refresh failed: %s", e, extra={"user": box.user_id})
                if self.quota is not None and box.last > self.quota.last.get(box.user_id, 0.0):
                    self.quota.touch(box.user_id)  # used since the last recount (a throttled touch may have skipped it)
                if box.active == 0:
                    try:
                        await self.apply_quota(box)  # a background recount found it full (or freed): switch now
                    except Exception as e:
                        log.error("workspace quota remount failed: %s", e, extra={"user": box.user_id})
                if not box.over and await self.compute.over(box.user_id):
                    log.warning("sandbox budget used up (daily minutes or points): pausing after the current call",
                                extra={"user": box.user_id})
                    box.over = True  # M8: no new calls; paused on the next tick with active == 0

    async def close(self, session_id: str) -> None:
        env = self.envs.pop(session_id, None)
        if env:
            env.box.sessions.discard(session_id)
            if not env.box.sessions and env.box.active == 0:
                await self._pause(env.box, idle=True)

    async def close_all(self) -> None:
        """Server shutdown: pause every sandbox (the paused disk keeps home)."""
        self.envs.clear()
        await asyncio.gather(*(self._pause(b) for b in self.boxes.values()), return_exceptions=True)

    # ---- orphans and admin ----------------------------------------------------------------------------------------

    async def list_all(self) -> list[dict]:
        """Our sandboxes at the provider: [{id, user_id, state, started_at}]."""
        from e2b import SandboxQuery
        pg, out = self._sdk.list(query=SandboxQuery(metadata={"app": self.tag}), **self._api()), list()
        while pg.has_next:
            for i in await pg.next_items():
                out.append({"id": i.sandbox_id, "user_id": i.metadata.get("user_id", ""), "egress": i.metadata.get("egress", ""),
                            "template": i.metadata.get("template", ""),
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
        await self._settle_pauses({i["id"] for i in found if i["user_id"] and i["state"] == "paused"})
        for i in found:
            box = self.boxes.setdefault(i["user_id"], _Box(i["user_id"])) if i["user_id"] else None
            try:
                # egress or template differs (older server, or settings changed): network rules and toolset are fixed
                # at create, so do not resume it; files are in /work and repos in their mirror, nothing is lost
                if box is None or box.sbx_id or i["egress"] != self.egress or i["template"] != self.template:
                    log.info("killing orphan sandbox %s", i["id"])
                    await self._sdk.kill(i["id"], **self._api())
                    await self.compute.unpaused(i["id"])
                    continue
                if i["state"] == "running":
                    await self._sdk.pause(i["id"], **self._api())
                box.sbx_id, box.state = i["id"], "paused"
                await self.compute.paused(box.user_id, i["id"], self.cpus, self.memory_gib)  # kept if already paused
                box.started = time.monotonic() - (datetime.now(timezone.utc) - i["started_at"]).total_seconds()
            except Exception as e:
                log.warning("orphan sandbox %s: %s", i["id"], e)

    async def _settle_pauses(self, keep: set[str]) -> None:
        """Paused boxes we remember but the provider no longer has (expired, admin-killed while we were down, or an
        orphan): charge their paused time up to now. Paused at most once per box, so never charged twice."""
        if self.compute.db is None or self.compute.paused_ratio <= 0:
            return
        for sbx_id in set(await self.compute.db.pause_ids()) - keep:
            await self.compute.unpaused(sbx_id)

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
