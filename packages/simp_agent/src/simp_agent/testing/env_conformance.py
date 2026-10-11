"""Reusable ExecutionEnv conformance suite (like pi durable/src/testing/env-conformance.ts).

Subclass EnvConformance in a test module and give it a `make_env` fixture:
a callable (root: Path) -> env (or awaitable env) whose file paths are relative to root and whose exec
accepts host paths under root as cwd."""

from __future__ import annotations

import asyncio
import inspect
import os
import time
import uuid

import pytest


class EnvConformance:
    @pytest.fixture
    async def env(self, make_env, tmp_path):
        self.root = tmp_path / f"root-{uuid.uuid4().hex[:8]}"  # unique: Docker names containers after it
        self.root.mkdir()
        env = make_env(self.root)
        return await env if inspect.isawaitable(env) else env

    async def run(self, env, cmd, timeout=30, cancel=None, cwd=None):
        return await env.exec(cmd, str(cwd or self.root), timeout, cancel or asyncio.Event())

    async def test_text_and_bytes_round_trip(self, env):
        await env.write_file("d/a.txt", "héllo\n")
        assert await env.read_file("d/a.txt") == "héllo\n"
        await env.write_bytes("b.bin", b"\x00\xff\x10")
        assert await env.read_bytes("b.bin") == b"\x00\xff\x10"

    async def test_list(self, env):
        await env.write_file("b.txt", "hi")
        await env.write_bytes("d/x", b"")
        assert await env.list(".") == [
            {"name": "b.txt", "is_dir": False, "size": 2},
            {"name": "d", "is_dir": True, "size": 0},
        ]

    async def test_containment(self, env, tmp_path):
        (tmp_path / "secret").write_text("s")
        os.symlink(tmp_path / "secret", self.root / "link")
        os.symlink(tmp_path, self.root / "dirlink")
        for bad in ("../secret", "link", "dirlink/secret", str(tmp_path / "secret")):
            with pytest.raises(PermissionError):
                await env.read_bytes(bad)
        for bad in ("../x", "dirlink/x"):
            with pytest.raises(PermissionError):
                await env.write_bytes(bad, b"")
        with pytest.raises(PermissionError):
            await env.list("..")
        assert not (tmp_path / "x").exists()

    async def test_exec_exit_code_and_output(self, env):
        out = []

        async def on_output(t):
            out.append(t)

        code, text = await env.exec("echo hi; echo err >&2; exit 3", str(self.root), 30, asyncio.Event(), on_output)
        assert code == 3
        assert "hi" in text and "err" in text
        assert "".join(out) == text

    async def test_exec_sees_written_files(self, env):
        await env.write_file("f.txt", "data")
        assert await self.run(env, "cat f.txt") == (0, "data")

    async def test_exec_cwd(self, env):
        (self.root / "sub").mkdir()
        code, text = await self.run(env, "pwd", cwd=self.root / "sub")
        assert code == 0 and text.strip().endswith("/sub")

    async def test_exec_timeout_kills_tree(self, env):
        t = time.monotonic()
        code, text = await self.run(env, "echo start; (sleep 6; sleep 1; echo late > late.txt) & sleep 30", timeout=2)
        assert code is None and "start" in text
        assert time.monotonic() - t < 10
        while time.monotonic() < t + 8:  # slack for a loaded event loop
            assert not (self.root / "late.txt").exists()  # background child was killed too
            await asyncio.sleep(0.1)

    async def test_exec_cancel(self, env):
        cancel = asyncio.Event()
        asyncio.get_running_loop().call_later(0.5, cancel.set)
        t = time.monotonic()
        code, _ = await self.run(env, "sleep 30", cancel=cancel)
        assert code is None and time.monotonic() - t < 10
