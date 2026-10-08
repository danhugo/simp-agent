"""ExecutionEnv: where tools read files and run commands. Core ships only LocalEnv; hosts pass their own."""

from __future__ import annotations

import asyncio
import os
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


class LocalEnv:
    """This machine. File IO runs in a thread so the loop never blocks.
    With a root, file paths are relative to it and may not escape it (via .. or symlinks)."""

    root: str | None = None

    def __init__(self, root: str | None = None):
        self.root = root

    def _path(self, path: str) -> Path:
        if self.root is None:
            return Path(path)
        root = Path(self.root).resolve()
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise PermissionError(f"path escapes root: {path}")
        return p

    async def read_file(self, path: str) -> str:
        return await asyncio.to_thread(self._path(path).read_text)

    async def write_file(self, path: str, text: str) -> None:
        await self.write_bytes(path, text.encode())

    async def read_bytes(self, path: str) -> bytes:
        return await asyncio.to_thread(self._path(path).read_bytes)

    async def write_bytes(self, path: str, data: bytes) -> None:
        p = self._path(path)

        def w():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

        await asyncio.to_thread(w)

    async def list(self, path: str) -> list[dict]:
        def ls():
            out = []
            for e in sorted(os.scandir(self._path(path)), key=lambda e: e.name):
                is_dir = e.is_dir()
                out.append({"name": e.name, "is_dir": is_dir, "size": 0 if is_dir else e.stat().st_size})
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
            os.killpg(proc.pid, 9)  # whole process tree (start_new_session)
            await run
            return None, "".join(chunks)
        return proc.returncode, "".join(chunks)
