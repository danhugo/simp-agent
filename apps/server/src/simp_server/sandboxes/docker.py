"""DockerSandbox: one hardened container per USER, started lazily on the first tool call that needs it, shared by all
the user's sessions, removed after `idle_pause_s` without use (or when the user's last session closes).

[sandbox] mount = "bind" (default): /work is a bind mount of the user's workspace dir, so file ops on /work run on the
host (LocalEnv with root containment): same files, one writer. mount = "fuse" (needs [workspace] store = "s3"): the
container mounts the user's bucket prefix at /work with s3fs, and every file op runs in the container. Security
trade-off of fuse mode: the container gets /dev/fuse and CAP_SYS_ADMIN (only root, used once by `docker exec -u 0` for
the mount; commands run as 1000 with no capabilities and no-new-privileges), AppArmor is unconfined (the default profile
blocks mount), and it needs a network to reach the store (default "bridge" instead of "none"). Paths outside /work (/home/user/repos, /tmp) and all commands go through
`docker exec`. /home/user is a per-user named volume (simp-home-<user_id>), so repos and libraries survive a
container restart; repos are also mirrored to /work/.simp/repos after each tool call (repos.py)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from simp_agent.agent.env import LocalEnv
from simp_agent.coding import SANDBOX_HINT
from simp_server import workspace
from simp_server.sandboxes import Compute, SandboxLimit, gib, user_root, valid_id
from simp_server.sandboxes.repos import mirror_locked, remirror_if_failed, restore_repos

log = logging.getLogger("simp_server")

IMAGE = "simp-sandbox:latest"
DOCKERFILE_DIR = Path(__file__).resolve().parents[3] / "sandboxes"
REPOS, MIRRORS = "/home/user/repos", "/work/.simp/repos"
USER = ("-u", "1000:1000")  # every exec: in fuse mode the container's root holds CAP_SYS_ADMIN
GONE = ("No such container", "is not running")
DENIED = ("Transport endpoint is not connected", "AccessDenied", "403 Forbidden")
CREDS_MARGIN_S = 300
# fuse stop (review M10): SIGTERM the user's processes, wait briefly, then unmount as root so s3fs flushes
FUSE_STOP = "pkill -TERM -u 1000; sleep 2; pkill -KILL -u 1000; sync; umount /work 2>/dev/null || umount -l /work"
CONTAINER_DIRS = ("/home/user", "/tmp")  # file tools may reach these container-only dirs; any other path outside /work is refused


# s3fs as root; $1 bucket:/prefix, $2 endpoint, $3 region; key, secret, session token on stdin. uid 1000 owns the files.
S3FS = """read -r AWSACCESSKEYID; read -r AWSSECRETACCESSKEY; read -r AWSSESSIONTOKEN
export AWSACCESSKEYID AWSSECRETACCESSKEY; [ -n "$AWSSESSIONTOKEN" ] && export AWSSESSIONTOKEN
exec s3fs "$1" /work -o url="$2" -o endpoint="$3" -o use_path_request_style -o allow_other -o uid=1000 -o gid=1000 \
  -o umask=0022 -o compat_dir -o stat_cache_expire=5 -o enable_noobj_cache"""


def build_image(tag: str = IMAGE) -> int:
    return subprocess.call(["docker", "build", "-t", tag, str(DOCKERFILE_DIR)])


async def _docker(*args: str, stdin: bytes | None = None) -> tuple[int, str]:
    p = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
    )
    out, _ = await p.communicate(stdin)
    return p.returncode, out.decode(errors="replace")


async def _exec_in(container, command, cwd, timeout, cancel, on_output=None) -> tuple[int | None, str]:
    """`docker exec` in container cwd. setsid: the command leads its own process group; first line out is its pid so
    we can kill the group. 2>&1 inside the container: docker sends stderr as its own stream, which could overtake
    the pid line."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", *USER, "-w", cwd, container,
        "setsid", "-w", "sh", "-c", 'echo $$; exec sh -c "$0" 2>&1', command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:  # the timeout also covers the wait for the pid line
        first = await asyncio.wait_for(proc.stdout.readline(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None, ""
    pid = first.strip().decode(errors="replace")
    if not pid.isdigit():  # the command never started: docker's own error ("No such container", ...) or EOF
        rest = await proc.stdout.read()
        await proc.wait()
        out = (first + rest).decode(errors="replace")
        if any(g in out for g in GONE):
            raise ContainerGone(out.strip())
        return proc.returncode, out
    chunks = list()

    async def pump():
        while data := await proc.stdout.read(4096):
            text = data.decode(errors="replace")
            chunks.append(text)
            if on_output:
                await on_output(text)
        await proc.wait()

    run = asyncio.ensure_future(pump())
    stop = asyncio.ensure_future(cancel.wait())
    done, _ = await asyncio.wait({run, stop}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    stop.cancel()
    if run not in done:
        if pid.isdigit():
            await _docker("exec", *USER, container, "kill", "-9", "--", f"-{pid}")
        if proc.returncode is None:
            proc.kill()
        await run
        return None, "".join(chunks)
    return proc.returncode, "".join(chunks)


class ContainerGone(RuntimeError):
    """`docker exec` found no running container: the command did not start, so running it again is safe."""


class _Box:
    """A user's container state, shared by their sessions' envs."""

    def __init__(self, user_id: str, root: Path):
        self.user_id, self.root, self.name = user_id, root, f"simp-u-{user_id}"
        self.running, self.active, self.last = False, 0, time.monotonic()
        self.started = self.metered = 0.0
        self.sessions: set[str] = set()
        self.lock = asyncio.Lock()
        self.starting = self.over = False  # starting: holds a running slot (M8); over: daily budget used up
        self.mirror_lock, self.mirror_failed, self.mirror_sid, self.mirror_bg = asyncio.Lock(), False, None, None
        self.creds_until = 0.0  # fuse: monotonic time the mount credential expires (0 = none)

    async def exec(self, command, cwd, timeout, cancel, on_output=None):  # raw: no start, no busy count
        return await _exec_in(self.name, command, "/work", timeout, cancel, on_output)


class DockerEnv(LocalEnv):
    """One per session (the session id names its WIP ref); the container belongs to the user's _Box."""

    def __init__(self, root: str, sandbox: "DockerSandbox", box: _Box, session_id: str):
        super().__init__(root)
        self.sandbox, self.box, self.session_id = sandbox, box, session_id
        self.container = box.name
        self.used = False  # something ran in the container since the last after_tool

    @contextlib.asynccontextmanager
    async def _use(self, need_s: float | None = None):
        """Start the container if needed; count as busy so the idle stop never kills a running command."""
        self.box.active += 1  # before any await: stop_idle sees it even while we wait for the start lock
        try:
            if self.box.over:  # set by the tick (M8); cleared once the budget resets
                if msg := await self.sandbox.compute.over_reason(self.box.user_id):
                    raise SandboxLimit(msg)
                self.box.over = False
            await self.sandbox.ensure(self.box)
            await self.sandbox.fresh_creds(self.box, need_s)
            self.used = True
            yield
        finally:
            self.box.active -= 1
            self.box.last = time.monotonic()

    def _host_rel(self, path: str) -> str | None:
        """Path relative to the workspace if it is on /work (container path, host path or relative), else None."""
        path = str(path)
        if path == "/work" or path.startswith("/work/"):
            return path[len("/work"):].lstrip("/") or "."
        if not path.startswith("/"):
            return path
        for host in {str(Path(self.root).resolve()), str(self.root)}:
            if path == host or path.startswith(host + "/"):
                return path[len(host):].lstrip("/") or "."
        return None

    def _path(self, path: str) -> Path:
        rel = self._host_rel(path)
        return super()._path(rel if rel is not None else path)  # an outside path raises "escapes root"

    def _parts(self, path: str) -> list[str]:  # host-side file IO (bind mode): O_NOFOLLOW walk from the root fd
        rel = self._host_rel(path)
        return super()._parts(rel if rel is not None else path)

    def _to_container(self, command: str) -> str:
        """Tools pass host paths (the workspace root) inside commands; inside the container that dir is /work. Only
        on a path boundary: root .../u1 must not rewrite .../u10."""
        for host in sorted({str(Path(self.root).resolve()), str(self.root)}, key=len, reverse=True):
            command = re.sub(re.escape(host) + r"(?![\w.-])", "/work", command)
        return command

    def _cwd(self, cwd: str) -> str:
        rel = self._host_rel(cwd)
        if rel is None:
            return cwd  # a container path such as /home/user/repos/x
        return str(Path("/work") / self._path(rel).relative_to(Path(self.root).resolve()))

    def _in_container(self, path: str) -> bool:
        path = str(path)
        if self._host_rel(path) is not None:
            return self.sandbox.mount == "fuse"  # /work is the container's s3fs mount
        return any(path == d or path.startswith(d + "/") for d in CONTAINER_DIRS) and "/../" not in path + "/"

    def _cpath(self, path: str) -> str:
        """The container path of a path _in_container (fuse: workspace paths map to /work, never escaping it)."""
        rel = self._host_rel(path)
        return path if rel is None else "/work/" + workspace.rel(rel)

    # files outside /work live only in the container
    async def _cat(self, path: str) -> bytes:
        async with self._use():
            p = await asyncio.create_subprocess_exec(
                "docker", "exec", *USER, self.container, "cat", "--", self._cpath(path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await p.communicate()
        if p.returncode:
            msg = err.decode(errors="replace").strip()
            raise (IsADirectoryError if "Is a directory" in msg else FileNotFoundError)(msg or path)
        return out

    async def read_file(self, path: str) -> str:
        if self._in_container(path):
            return (await self._cat(path)).decode()
        return await super().read_file(path)

    async def read_bytes(self, path: str) -> bytes:
        if self._in_container(path):
            return await self._cat(path)
        return await super().read_bytes(path)

    async def write_bytes(self, path: str, data: bytes) -> None:
        if not self._in_container(path):
            return await super().write_bytes(path, data)
        async with self._use():
            code, out = await _docker("exec", *USER, "-i", self.container, "sh", "-c",
                                      'mkdir -p "$(dirname "$1")" && cat > "$1"', "sh", self._cpath(path), stdin=data)
        if code:
            raise PermissionError(out.strip() or f"cannot write {path}")

    async def list(self, path: str) -> list[dict]:
        if not self._in_container(path):
            return await super().list(path)
        script = ("import json,os,sys; print(json.dumps([{'name': e.name, 'is_dir': e.is_dir(), "
                  "'size': 0 if e.is_dir() else e.stat().st_size} for e in sorted(os.scandir(sys.argv[1]), key=lambda e: e.name)]))")
        async with self._use():
            code, out = await _docker("exec", *USER, self.container, "python3", "-c", script, self._cpath(path))
        if code:
            raise FileNotFoundError(out.strip().splitlines()[-1] if out.strip() else path)
        return json.loads(out)

    async def exec(self, command, cwd, timeout, cancel, on_output=None) -> tuple[int | None, str]:
        for attempt in (1, 2):
            try:
                async with self._use(timeout):
                    code, out = await _exec_in(self.container, self._to_container(command), self._cwd(cwd), timeout,
                                               cancel, on_output)
            except ContainerGone:
                # removed behind our back (`simp-server sandboxes --kill`, docker restart): the command never
                # started, so start the container again and run it once more
                log.warning("sandbox container gone: restarting", extra={"user": self.box.user_id})
                await self.sandbox.mark_gone(self.box)
                if attempt == 2:
                    raise
                continue
            if self.sandbox.mount == "fuse":
                self.sandbox.check_denied(self.box, out)
            return code, out

    async def after_tool(self) -> None:
        """After each tool call that used the container: make it durable. One place for steps 2/3 to extend
        (FUSE upload wait). Never raises."""
        if not self.used:
            return
        try:
            await self.exec("sync", "/work", 60, asyncio.Event())
            await mirror_locked(self, self.box, REPOS, MIRRORS, self.session_id, cwd="/work")
        except Exception as e:
            log.warning("after-tool sync failed: %s", e, extra={"session": self.session_id})
        finally:
            self.used = False


class DockerSandbox:
    """Server Sandbox slot: open(session_id, user_id) -> DockerEnv, close(session_id), stop_idle(), close_all().
    Built from the server settings dict; options in its [sandbox] table. open() is cheap (no container); the user's
    container starts on first use and is shared by all their sessions. All containers run as 1000:1000."""

    prompt_hint = SANDBOX_HINT

    kind = "docker"

    def __init__(self, settings: dict):
        s = settings.get("sandbox", dict())
        self.mount = s.get("mount", "bind")
        self.store = None  # workspace store (fuse mode: mount creds), set by create_app
        self.compute = Compute(settings, "docker")
        self.max_life_s = s.get("max_life_s", 3300)  # fuse: restart before the mount credential expires
        self.workspaces_dir = Path(s.get("workspaces_dir", Path(settings["data_dir"]) / "workspaces")).expanduser()
        self.image, self.network = s.get("image", IMAGE), s.get("network", "bridge" if self.mount == "fuse" else "none")
        self.memory, self.cpus, self.pids_limit = s.get("memory", "1g"), str(s.get("cpus", "1")), s.get("pids_limit", 256)
        self.tmp_size = s.get("tmp_size", "256m")
        self.idle_pause_s = s.get("idle_pause_s", 600)
        self.envs: dict[str, DockerEnv] = dict()
        self.boxes: dict[str, _Box] = dict()
        self.legacy_dir = Path(settings["data_dir"]) / "sandboxes"

    async def open(self, session_id: str, user_id: str) -> DockerEnv:
        root = user_root(self.workspaces_dir, self.legacy_dir, user_id, session_id)  # validates both ids
        if session_id in self.envs:
            return self.envs[session_id]
        box = self.boxes.get(user_id)
        if box is None or box.root != root:
            box = self.boxes[user_id] = _Box(user_id, root)
        box.sessions.add(session_id)
        env = self.envs[session_id] = DockerEnv(str(root), self, box, session_id)
        return env

    async def ensure(self, box: _Box) -> None:
        """Start the user's container if it is not running; restore missing repos from their mirrors."""
        if box.running:
            return
        async with box.lock:
            if box.running:
                return
            await self.compute.reserve(box, self.running)  # M8: slot held (box.starting) before docker run
            try:
                await self._start(box)
            finally:
                box.starting = False

    def running(self) -> int:
        return sum(b.running or b.starting for b in self.boxes.values())

    async def _start(self, box: _Box) -> None:
        await _docker("rm", "-f", box.name)  # leftover from a crash
        work = (["--device", "/dev/fuse", "--cap-add", "SYS_ADMIN", "--security-opt", "apparmor=unconfined",
                 "--add-host", "host.docker.internal:host-gateway"] if self.mount == "fuse"
                else ["-v", f"{box.root.resolve()}:/work"])
        code, out = await _docker(
            "run", "-d", "--name", box.name, "--user", "1000:1000", "--network", self.network,
            "--pids-limit", str(self.pids_limit), "--memory", self.memory, "--cpus", self.cpus,
            "--read-only", "--tmpfs", f"/tmp:rw,nosuid,nodev,size={self.tmp_size}",
            "--security-opt", "no-new-privileges", "--cap-drop", "ALL", *work,
            "-v", f"simp-home-{box.user_id}:/home/user",
            "-w", "/work", "--label", f"simp.user={box.user_id}", self.image, "sleep", "infinity",
        )
        if code != 0:
            raise RuntimeError(f"docker run failed: {out.strip()}")
        if self.mount == "fuse":
            try:
                await self._mount(box)
            except Exception:
                await _docker("rm", "-f", box.name)
                raise
        box.running, box.last = True, time.monotonic()
        box.started = box.metered = box.last
        box.mirror_failed = False
        await restore_repos(box, REPOS, MIRRORS, cwd="/work")

    async def _mount(self, box: _Box) -> None:
        """s3fs mount of the user's prefix at /work, as root (the only root exec). Credentials go in on stdin."""
        c = await self.store.mount_creds(box.user_id)
        box.creds_until = time.monotonic() + c["expires_in"] if c.get("expires_in") else 0.0
        creds = f"{c['access_key']}\n{c['secret_key']}\n{c['session_token']}\n".encode()
        code, out = await _docker("exec", "-i", "-u", "0", box.name, "sh", "-c", S3FS, "sh",
                                  f"{c['bucket']}:/{c['prefix'].rstrip('/')}", c["endpoint"], c["region"], stdin=creds)
        if code != 0:
            raise RuntimeError(f"workspace mount failed: {out.strip()}")

    async def meter(self, box: _Box, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if box.metered:
            await self.compute.record(box.user_id, now - box.metered, float(self.cpus), gib(self.memory))
        box.metered = now if box.running else 0.0

    async def mark_gone(self, box: _Box) -> None:
        async with box.lock:
            if box.running:
                box.running = False
                await self.meter(box)

    def check_denied(self, box: _Box, out: str) -> None:
        if any(m in out for m in DENIED):
            left = box.creds_until - time.monotonic() if box.creds_until else None
            log.error("WORKSPACE MOUNT DENIED (s3fs 403 / dead mount) for user %s; credential expires in %s s",
                      box.user_id, None if left is None else round(left), extra={"user": box.user_id})

    async def fresh_creds(self, box: _Box, need_s: float | None) -> None:
        """Fuse (review M2): never start a call that would outlive the mount credential: if it expires within the
        call's timeout (or CREDS_MARGIN_S), take a fresh one and remount first, when no other call uses the mount."""
        if self.mount != "fuse" or not box.creds_until:
            return
        if box.creds_until - time.monotonic() > max(need_s or 0, CREDS_MARGIN_S):
            return
        async with box.lock:
            if box.creds_until - time.monotonic() > max(need_s or 0, CREDS_MARGIN_S):
                return
            if box.active > 1:
                raise SandboxLimit("sandbox: the workspace credential is about to expire and another command is still "
                                   "running; try again when it ends.")
            log.info("refreshing workspace mount credential", extra={"user": box.user_id})
            await self._remount(box)

    async def _remount(self, box: _Box) -> None:
        await _docker("exec", "-u", "0", box.name, "sh", "-c", "sync; umount /work 2>/dev/null || umount -l /work")
        await self._mount(box)

    async def _stop(self, box: _Box, idle: bool = False) -> bool:
        """Remove the container. idle=True (tick): only if no call is active once both locks are held (C3); the
        mirror lock first, so a background mirror finishes before the container goes (M7)."""
        async with box.mirror_lock, box.lock:
            if not box.running or idle and box.active:
                return False
            box.running = False  # before any await: a new call now waits on box.lock and starts a new container
            try:
                await remirror_if_failed(box, REPOS, MIRRORS)
                if self.mount == "fuse":  # M10: let s3fs flush: stop user processes, unmount as root, then remove
                    await _docker("exec", "-u", "0", box.name, "sh", "-c", FUSE_STOP)
            finally:
                await self.meter(box)
                await _docker("rm", "-f", box.name)
            return True

    async def stop_idle(self, now: float | None = None) -> None:
        """Remove containers unused for idle_pause_s. Never while a command runs (active > 0)."""
        now = time.monotonic() if now is None else now
        for box in list(self.boxes.values()):
            if not box.running:
                continue
            if box.active == 0 and (now - box.last >= self.idle_pause_s or box.over
                                    or self.mount == "fuse" and now - box.started >= self.max_life_s):
                log.info("sandbox idle stop", extra={"user": box.user_id})
                await self._stop(box, idle=True)
            else:
                await self.meter(box, max(now, box.metered))
                if box.active == 0 and self.mount == "fuse" and box.creds_until and \
                        box.creds_until - time.monotonic() < 2 * CREDS_MARGIN_S:
                    with contextlib.suppress(Exception):
                        await self.fresh_creds(box, 2 * CREDS_MARGIN_S)  # M2: refresh at an idle point
                if not box.over and await self.compute.over(box.user_id):
                    log.warning("sandbox budget used up (daily minutes or points): stopping after the current call",
                                extra={"user": box.user_id})
                    box.over = True  # M8: no new calls; stopped on the next tick with active == 0

    async def close(self, session_id: str) -> None:
        """The session is done with the sandbox; the container goes when the user's last session closes."""
        env = self.envs.pop(session_id, None)
        if env:
            env.box.sessions.discard(session_id)
            if not env.box.sessions and env.box.active == 0:
                await self._stop(env.box)

    async def close_all(self) -> None:
        self.envs.clear()
        await asyncio.gather(*(self._stop(b) for b in self.boxes.values()))

    # ---- admin (`simp-server sandboxes`) ---------------------------------------------------------------------------

    async def list_all(self) -> list[dict]:
        code, out = await _docker("ps", "-a", "--filter", "label=simp.user", "--format",
                                  '{{.ID}}\t{{.Label "simp.user"}}\t{{.State}}\t{{.CreatedAt}}')
        rows = [line.split("\t") for line in out.splitlines() if line.count("\t") == 3] if code == 0 else []
        return [{"id": i, "user_id": u, "state": st, "started_at": datetime.strptime(c[:19], "%Y-%m-%d %H:%M:%S").astimezone()}
                for i, u, st, c in rows]

    async def admin_kill(self, user_id: str) -> int:
        n = sum(r["user_id"] == user_id for r in await self.list_all())
        await _docker("rm", "-f", f"simp-u-{valid_id(user_id)}")
        return n

    async def admin_pause_all(self) -> int:
        """Docker has no paused state here: stop (remove) every user container; the next tool call starts it again."""
        rows = [r for r in await self.list_all() if r["state"] == "running"]
        for r in rows:
            await _docker("rm", "-f", r["id"])
        return len(rows)
