import asyncio
from types import SimpleNamespace

from simp_server.sandboxes import docker


async def test_timeout_covers_the_pid_line(monkeypatch):
    """docker exec hangs before the pid line: the timeout still fires and the process is killed."""
    killed = list()

    async def fake_exec(*a, **kw):
        async def hang():
            await asyncio.Event().wait()

        async def wait():
            return -9
        return SimpleNamespace(stdout=SimpleNamespace(readline=hang), kill=lambda: killed.append(1), wait=wait)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await docker._exec_in("c", "true", "/", 0.05, asyncio.Event()) == (None, "")
    assert killed
