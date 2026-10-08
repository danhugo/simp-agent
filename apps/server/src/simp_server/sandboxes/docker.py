"""DockerSandbox: one hardened container per session. File ops run on the host (LocalEnv with root
containment) on a dir bind-mounted at /work; only exec goes through `docker exec`."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

from simp_agent.agent.env import LocalEnv

IMAGE = "simp-sandbox:latest"
DOCKERFILE_DIR = Path(__file__).resolve().parents[3] / "sandboxes"


def build_image(tag: str = IMAGE) -> int:
    return subprocess.call(["docker", "build", "-t", tag, str(DOCKERFILE_DIR)])


async def _docker(*args: str) -> tuple[int, str]:
    p = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await p.communicate()
    return p.returncode, out.decode(errors="replace")


class DockerEnv(LocalEnv):
    def __init__(self, root: str, container: str):
        super().__init__(root)
        self.container = container

    def _cwd(self, cwd: str) -> str:
        rel = self._path(cwd).relative_to(Path(self.root).resolve())  # host path (or relative) -> /work/...
        return str(Path("/work") / rel)

    async def exec(self, command, cwd, timeout, cancel, on_output=None) -> tuple[int | None, str]:
        # setsid: the command leads its own process group; first line out is its pid so we can kill the group.
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-w", self._cwd(cwd), self.container,
            "setsid", "-w", "sh", "-c", 'echo $$; exec sh -c "$0"', command,
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
                await _docker("exec", self.container, "kill", "-9", "--", f"-{pid}")
            if proc.returncode is None:
                proc.kill()
            await run
            return None, "".join(chunks)
        return proc.returncode, "".join(chunks)


class DockerSandbox:
    """Server Sandbox slot: open(session_id) -> DockerEnv, close(session_id), close_all() on shutdown.
    Built from the server settings dict; options in its [sandbox] table. Workspaces: workspaces_dir/<session_id>."""

    def __init__(self, settings: dict):
        s = settings.get("sandbox", dict())
        self.workspaces_dir = Path(s.get("workspaces_dir", Path(settings["data_dir"]) / "workspaces")).expanduser()
        self.image, self.network = s.get("image", IMAGE), s.get("network", "none")
        self.memory, self.cpus, self.pids_limit = s.get("memory", "1g"), str(s.get("cpus", "1")), s.get("pids_limit", 256)
        self.envs: dict[str, DockerEnv] = dict()

    async def open(self, session_id: str) -> DockerEnv:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
            raise ValueError(f"bad session id: {session_id!r}")
        if session_id in self.envs:
            return self.envs[session_id]
        root = self.workspaces_dir / session_id
        root.mkdir(parents=True, exist_ok=True)
        name = f"simp-{session_id}"
        await _docker("rm", "-f", name)  # leftover from a crash
        code, out = await _docker(
            "run", "-d", "--name", name, "--user", "1000:1000", "--network", self.network,
            "--pids-limit", str(self.pids_limit), "--memory", self.memory, "--cpus", self.cpus,
            "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
            "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
            "-v", f"{root.resolve()}:/work", "-w", "/work", self.image, "sleep", "infinity",
        )
        if code != 0:
            raise RuntimeError(f"docker run failed: {out.strip()}")
        env = self.envs[session_id] = DockerEnv(str(root), name)
        return env

    async def close(self, session_id: str) -> None:
        env = self.envs.pop(session_id, None)
        if env:
            await _docker("rm", "-f", env.container)

    async def close_all(self) -> None:
        await asyncio.gather(*(self.close(s) for s in list(self.envs)))
