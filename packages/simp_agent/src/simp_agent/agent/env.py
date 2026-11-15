"""ExecutionEnv: where tools read files and run commands. Core ships only LocalEnv; hosts pass their own."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import stat
from pathlib import Path
from typing import Awaitable, Callable, Protocol


class ExecutionEnv(Protocol):
    async def read_file(self, path: str) -> str: ...

    async def write_file(self, path: str, text: str) -> None: ...

    async def list(self, path: str) -> list[dict]: ...  # [{name, is_dir, size}]

    async def read_bytes(self, path: str) -> bytes: ...

    async def write_bytes(self, path: str, data: bytes) -> None: ...

    async def exec(
        self, command: str, cwd: str, timeout: float | None, cancel: asyncio.Event,
        on_output: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[int | None, str]: ...  # exit code is None when killed (timeout or cancel); output = what came so far


async def run_kill(pgid: int) -> None:
    """SIGKILL the whole process group (start_new_session) until it is empty: a child forked while the first
    signal is delivered can miss it."""
    for _ in range(100):
        try:
            os.killpg(pgid, 9)
        except (ProcessLookupError, PermissionError):  # group empty (macOS: EPERM once only zombies are left)
            return
        await asyncio.sleep(0.02)


def _is_link(dir_fd: int, name: str) -> bool:
    try:
        return stat.S_ISLNK(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode)
    except OSError:
        return False


class LocalEnv:
    """This machine. File IO runs in a thread so the loop never blocks.
    With a root, file paths are relative to it and may not escape it: every component is opened with O_NOFOLLOW
    relative to the parent's dir fd, so a symlink (even one swapped in between a check and the open, e.g. by a
    sandboxed process sharing the dir) is refused, never followed."""

    root: str | None = None

    def __init__(self, root: str | None = None):
        self.root = root

    def _parts(self, path: str) -> list[str]:
        """Path components under the root, lexically ('..' cannot climb out). Absolute paths must be under the root."""
        path, root = str(path), Path(self.root)
        if os.path.isabs(path):
            for r in (str(root), str(root.resolve())):
                if path == r or path.startswith(r.rstrip("/") + "/"):
                    path = path[len(r):]
                    break
            else:
                raise PermissionError(f"path escapes root: {path}")
        parts = list()
        for seg in path.split("/"):
            if seg == "..":
                if not parts:
                    raise PermissionError(f"path escapes root: {path}")
                parts.pop()
            elif seg not in ("", "."):
                parts.append(seg)
        return parts

    def _path(self, path: str) -> Path:
        """Host path for a non-IO use (a command's cwd). File IO goes through _open_dir/_open_file."""
        if self.root is None:
            return Path(path)
        return Path(self.root).resolve().joinpath(*self._parts(path))

    def _open_dir(self, parts: list[str], create: bool = False) -> int:
        """fd of root/parts, each component opened O_NOFOLLOW|O_DIRECTORY relative to its parent. Caller closes."""
        fd = os.open(Path(self.root).resolve(), os.O_RDONLY | os.O_DIRECTORY)
        try:
            for name in parts:
                try:
                    nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    with contextlib.suppress(FileExistsError):
                        os.mkdir(name, 0o755, dir_fd=fd)
                    nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except OSError as e:
                    if _is_link(fd, name):
                        raise PermissionError(f"symlink refused: {name}") from None
                    if e.errno == errno.ENOTDIR:
                        raise NotADirectoryError(name) from None
                    raise
                os.close(fd)
                fd = nxt
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _open_file(self, path: str, flags: int, create_dirs: bool = False) -> int:
        parts = self._parts(path)
        if not parts:
            raise IsADirectoryError(path)
        dfd = self._open_dir(parts[:-1], create_dirs)
        try:
            return os.open(parts[-1], flags | os.O_NOFOLLOW, 0o644, dir_fd=dfd)
        except OSError as e:
            if e.errno in (errno.ELOOP, errno.EMLINK) or _is_link(dfd, parts[-1]):
                raise PermissionError(f"symlink refused: {path}") from None
            raise
        finally:
            os.close(dfd)

    def _read(self, path: str) -> bytes:
        if self.root is None:
            return Path(path).read_bytes()
        with os.fdopen(self._open_file(path, os.O_RDONLY), "rb") as f:
            return f.read()

    def _write(self, path: str, data: bytes) -> None:
        if self.root is None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            return
        with os.fdopen(self._open_file(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, create_dirs=True), "wb") as f:
            f.write(data)

    def _unlink(self, path: str) -> None:
        parts = self._parts(path)
        if not parts:
            raise IsADirectoryError(path)
        dfd = self._open_dir(parts[:-1])
        try:
            os.unlink(parts[-1], dir_fd=dfd)
        finally:
            os.close(dfd)

    async def read_file(self, path: str) -> str:
        return (await self.read_bytes(path)).decode()

    async def write_file(self, path: str, text: str) -> None:
        await self.write_bytes(path, text.encode())

    async def read_bytes(self, path: str) -> bytes:
        return await asyncio.to_thread(self._read, path)

    async def write_bytes(self, path: str, data: bytes) -> None:
        await asyncio.to_thread(self._write, path, data)

    async def list(self, path: str) -> list[dict]:
        def ls():
            if self.root is None:
                it = os.scandir(path)
            else:
                fd = self._open_dir(self._parts(path))
                it = os.scandir(fd)
            out = []
            try:
                for e in sorted(it, key=lambda e: e.name):
                    is_dir = e.is_dir(follow_symlinks=False)
                    out.append({"name": e.name, "is_dir": is_dir,
                                "size": 0 if is_dir else e.stat(follow_symlinks=False).st_size})
            finally:
                if self.root is not None:
                    os.close(fd)
            return out

        return await asyncio.to_thread(ls)

    async def exec(self, command, cwd, timeout, cancel, on_output=None) -> tuple[int | None, str]:
        proc = await asyncio.create_subprocess_shell(
            command, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True
        )
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
            await run_kill(proc.pid)
            await run
            return None, "".join(chunks)
        return proc.returncode, "".join(chunks)
