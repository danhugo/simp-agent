"""Workspace sync (sandboxes/wsync.py) against the dev MinIO, with the sandbox side run on this machine (LocalPort)."""

import asyncio
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from simp_server.sandboxes import wsync
from simp_server.workspace import S3Store


class LocalPort:
    """The sandbox side in a temp dir: /work -> tmp/work, /tmp/.simp-sync -> tmp/state."""

    def __init__(self, root: Path):
        self.work, self.state = root / "work", root / "state"
        self.work.mkdir(parents=True, exist_ok=True)

    def _p(self, path: str) -> Path:
        return Path(path.replace(wsync.STATE, str(self.state)))

    async def sh(self, command, timeout=300):
        command = command.replace(wsync.STATE, str(self.state))
        env = {**os.environ, "SIMP_WORK": str(self.work), "SIMP_SYNC": str(self.state)}
        r = await asyncio.to_thread(subprocess.run, ["sh", "-c", command], capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr

    async def put(self, path, data):
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    async def get(self, path):
        p = self._p(path)
        if not p.exists():
            raise FileNotFoundError(path)
        return p.read_bytes()


class FakeQuota:
    def __init__(self, room=True):
        self.room = room

    async def fits(self, user_id, n):
        return self.room

    def touch(self, user_id):
        pass


@pytest.fixture
def store(tmp_path, s3_settings):
    settings, keys = s3_settings(tmp_path, prefix=f"wsync-{uuid.uuid4().hex[:8]}/{{user_id}}/")
    return S3Store(settings, keys)


def write(port, rel, text):
    p = port.work / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    t = time.time() + 1  # a new mtime even within the same clock tick
    os.utime(p, (t, t))


async def test_push_pull_and_snapshot(tmp_path, store):
    ws = wsync.WorkSync(store, "u1")
    a = LocalPort(tmp_path / "a")
    await ws.pull(a)  # empty workspace
    write(a, "src/x.py", "x = 1\n")
    write(a, "notes.md", "hi")
    await ws.flush(a)
    assert await store.read("u1", "src/x.py") == b"x = 1\n"
    # edit + delete
    write(a, "src/x.py", "x = 2\n")
    (a.work / "notes.md").unlink()
    await ws.flush(a)
    assert await store.read("u1", "src/x.py") == b"x = 2\n"
    with pytest.raises(FileNotFoundError):
        await store.read("u1", "notes.md")
    # a panel upload after the snapshot: a new sandbox takes x.py from the snapshot, new.txt by itself
    await store.write("u1", "new.txt", b"web")
    b = LocalPort(tmp_path / "b")
    n = await wsync.WorkSync(store, "u1").pull(b)
    assert (n["snapshot"], n["fetched"]) == (1, 1)
    assert (b.work / "src/x.py").read_text() == "x = 2\n" and (b.work / "new.txt").read_text() == "web"
    # the snapshot is outside the user's files
    assert [e["name"] for e in await store.list("u1", ".")] == ["new.txt", "src"]


async def test_panel_changes_and_conflict(tmp_path, store):
    ws = wsync.WorkSync(store, "u2")
    a = LocalPort(tmp_path / "a")
    await store.write("u2", "a.txt", b"one")
    await store.write("u2", "b.txt", b"two")
    await ws.pull(a)
    assert (a.work / "a.txt").read_text() == "one"
    # the panel uploads and deletes; the agent changed a.txt meanwhile
    write(a, "a.txt", "agent")
    await store.write("u2", "a.txt", b"panel")
    await store.write("u2", "c.txt", b"three")
    await store.delete("u2", "b.txt")
    ws.web_dirty = True
    await ws.before_call(a)
    names = sorted(p.name for p in a.work.iterdir())
    assert (a.work / "a.txt").read_text() == "panel" and (a.work / "c.txt").read_text() == "three"
    assert "b.txt" not in names
    conflict = [n for n in names if n.startswith("a.txt.conflict-")]
    assert len(conflict) == 1 and (a.work / conflict[0]).read_text() == "agent"
    # the push sends the conflict copy and nothing else changes in the bucket
    await ws.flush(a)
    assert await store.read("u2", conflict[0]) == b"agent"
    assert await store.read("u2", "a.txt") == b"panel"


async def test_background_push_and_quota(tmp_path, store):
    q = FakeQuota(room=False)
    ws = wsync.WorkSync(store, "u3", q)
    a = LocalPort(tmp_path / "a")
    await ws.pull(a)
    write(a, "big.bin", "x" * 1000)
    ws.push_soon(a)
    await ws.task
    assert ws.full
    with pytest.raises(FileNotFoundError):
        await store.read("u3", "big.bin")
    q.room = True
    ws.push_soon(a)
    ws.push_soon(a)  # queued behind the first: one more push at most
    await ws.task
    assert not ws.full and await store.read("u3", "big.bin") == b"x" * 1000


async def test_symlink_cannot_lead_a_panel_file_out(tmp_path, store):
    ws = wsync.WorkSync(store, "u4")
    a = LocalPort(tmp_path / "a")
    await ws.pull(a)
    outside = tmp_path / "outside"
    outside.mkdir()
    (a.work / "link").symlink_to(outside)
    await store.write("u4", "link/evil.txt", b"x")
    ws.web_dirty = True
    with pytest.raises(wsync.SyncError):
        await ws.before_call(a)
    assert not (outside / "evil.txt").exists()
