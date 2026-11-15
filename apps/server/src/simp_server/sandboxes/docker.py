"""DockerSandbox: one hardened container per USER, started lazily on the first tool call that needs it, shared by all
the user's sessions, removed after `idle_pause_s` without use (or when the user's last session closes).

/work is a bind mount of the user's workspace dir, so file ops on /work run on the host (LocalEnv with root
containment): same files, one writer. Paths outside /work (/home/user/repos, /tmp) and all commands go through
`docker exec`. /home/user is a per-user named volume (simp-home-<user_id>), so repos and libraries survive a
container restart; repos are also mirrored to /work/.simp/repos after each tool call (repos.py)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import time
from pathlib import Path

from simp_agent.agent.env import LocalEnv
from simp_agent.coding import SANDBOX_HINT
from simp_server.sandboxes import user_root
from simp_server.sandboxes.repos import mirror_repos, restore_repos

log = logging.getLogger("simp_server")

IMAGE = "simp-sandbox:latest"
DOCKERFILE_DIR = Path(__file__).resolve().parents[3] / "sandboxes"
REPOS, MIRRORS = "/home/user/repos", "/work/.simp/repos"
CONTAINER_DIRS = ("/home/user", "/tmp")  # file tools may reach these container-only dirs; any other path outside /work is refused


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
        "docker", "exec", "-w", cwd, container,
        "setsid", "-w", "sh", "-c", 'echo $$; exec sh -c "$0" 2>&1', command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    pid = (await proc.stdout.readline()).strip().decode()
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
            await _docker("exec", container, "kill", "-9", "--", f"-{pid}")
        if proc.returncode is None:
            proc.kill()
        await run
        return None, "".join(chunks)
    return proc.returncode, "".join(chunks)


class _Box:
    """A user's container state, shared by their sessions' envs."""

    def __init__(self, user_id: str, root: Path):
        self.user_id, self.root, self.name = user_id, root, f"simp-u-{user_id}"
        self.running, self.active, self.last = False, 0, time.monotonic()
        self.sessions: set[str] = set()
        self.lock = asyncio.Lock()

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
    async def _use(self):
        """Start the container if needed; count as busy so the idle stop never kills a running command."""
        self.box.active += 1  # before any await: stop_idle sees it even while we wait for the start lock
        try:
            await self.sandbox.ensure(self.box)
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

    def _to_container(self, command: str) -> str:
        """Tools pass host paths (the workspace root) inside commands; inside the container that dir is /work."""
        for host in {str(Path(self.root).resolve()), str(self.root)}:
            command = command.replace(host, "/work")
        return command

    def _cwd(self, cwd: str) -> str:
        rel = self._host_rel(cwd)
        if rel is None:
            return cwd  # a container path such as /home/user/repos/x
        return str(Path("/work") / self._path(rel).relative_to(Path(self.root).resolve()))

    def _in_container(self, path: str) -> bool:
        path = str(path)
        return self._host_rel(path) is None and any(path == d or path.startswith(d + "/") for d in CONTAINER_DIRS) and "/../" not in path + "/"

    # files outside /work live only in the container
    async def _cat(self, path: str) -> bytes:
        async with self._use():
            p = await asyncio.create_subprocess_exec(
                "docker", "exec", self.container, "cat", "--", path,
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
            code, out = await _docker("exec", "-i", self.container, "sh", "-c",
                                      'mkdir -p "$(dirname "$1")" && cat > "$1"', "sh", path, stdin=data)
        if code:
            raise PermissionError(out.strip() or f"cannot write {path}")

    async def list(self, path: str) -> list[dict]:
        if not self._in_container(path):
            return await super().list(path)
        script = ("import json,os,sys; print(json.dumps([{'name': e.name, 'is_dir': e.is_dir(), "
                  "'size': 0 if e.is_dir() else e.stat().st_size} for e in sorted(os.scandir(sys.argv[1]), key=lambda e: e.name)]))")
        async with self._use():
            code, out = await _docker("exec", self.container, "python3", "-c", script, path)
        if code:
            raise FileNotFoundError(out.strip().splitlines()[-1] if out.strip() else path)
        return json.loads(out)

    async def exec(self, command, cwd, timeout, cancel, on_output=None) -> tuple[int | None, str]:
        async with self._use():
            return await _exec_in(self.container, self._to_container(command), self._cwd(cwd), timeout, cancel, on_output)

    async def after_tool(self) -> None:
        """After each tool call that used the container: make it durable. One place for steps 2/3 to extend
        (FUSE upload wait). Never raises."""
        if not self.used:
            return
        try:
            await self.exec("sync", "/work", 60, asyncio.Event())
            await mirror_repos(self, REPOS, MIRRORS, self.session_id, cwd="/work")
        except Exception as e:
            log.warning("after-tool sync failed: %s", e, extra={"session": self.session_id})
        finally:
            self.used = False


class DockerSandbox:
    """Server Sandbox slot: open(session_id, user_id) -> DockerEnv, close(session_id), stop_idle(), close_all().
    Built from the server settings dict; options in its [sandbox] table. open() is cheap (no container); the user's
    container starts on first use and is shared by all their sessions. All containers run as 1000:1000."""

    prompt_hint = SANDBOX_HINT

    def __init__(self, settings: dict):
        s = settings.get("sandbox", dict())
        self.workspaces_dir = Path(s.get("workspaces_dir", Path(settings["data_dir"]) / "workspaces")).expanduser()
        self.image, self.network = s.get("image", IMAGE), s.get("network", "none")
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
            await _docker("rm", "-f", box.name)  # leftover from a crash
            code, out = await _docker(
                "run", "-d", "--name", box.name, "--user", "1000:1000", "--network", self.network,
                "--pids-limit", str(self.pids_limit), "--memory", self.memory, "--cpus", self.cpus,
                "--read-only", "--tmpfs", f"/tmp:rw,nosuid,nodev,size={self.tmp_size}",
                "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
                "-v", f"{box.root.resolve()}:/work", "-v", f"simp-home-{box.user_id}:/home/user",
                "-w", "/work", "--label", f"simp.user={box.user_id}", self.image, "sleep", "infinity",
            )
            if code != 0:
                raise RuntimeError(f"docker run failed: {out.strip()}")
            box.running, box.last = True, time.monotonic()
            await restore_repos(box, REPOS, MIRRORS, cwd="/work")

    async def _stop(self, box: _Box) -> None:
        async with box.lock:
            if box.running:
                box.running = False
                await _docker("rm", "-f", box.name)

    async def stop_idle(self, now: float | None = None) -> None:
        """Remove containers unused for idle_pause_s. Never while a command runs (active > 0)."""
        now = time.monotonic() if now is None else now
        for box in list(self.boxes.values()):
            if box.running and box.active == 0 and now - box.last >= self.idle_pause_s:
                log.info("sandbox idle stop", extra={"user": box.user_id})
                await self._stop(box)

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
