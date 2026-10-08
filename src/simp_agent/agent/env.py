"""ExecutionEnv: where tools read files and run commands. Core ships only LocalEnv; hosts pass their own."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Awaitable, Callable, Protocol


class ExecutionEnv(Protocol):
    async def read_file(self, path: str) -> str: ...

    async def write_file(self, path: str, text: str) -> None: ...

    async def exec(
        self, command: str, cwd: str, timeout: float, cancel: asyncio.Event,
        on_output: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[int, str]: ...


class LocalEnv:
    """This machine. File IO runs in a thread so the loop never blocks."""

    async def read_file(self, path: str) -> str:
        return await asyncio.to_thread(Path(path).read_text)

    async def write_file(self, path: str, text: str) -> None:
        def w():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text)

        await asyncio.to_thread(w)

    async def exec(self, command, cwd, timeout, cancel, on_output=None) -> tuple[int, str]:
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
            os.killpg(proc.pid, 9)
            await run
            raise RuntimeError("command aborted" if cancel.is_set() else f"command timed out after {timeout}s")
        return proc.returncode, "".join(chunks)
