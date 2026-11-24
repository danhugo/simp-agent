"""DockerSandbox in sync mode: /work is the container's own disk, synced with the dev MinIO bucket by the server.
Runs when docker and the dev MinIO are available (the `minio` fixture), skips otherwise."""

import asyncio
import subprocess
import uuid

import pytest

from simp_server.sandboxes.docker import IMAGE, DockerSandbox, build_image
from simp_server.workspace import S3Store


@pytest.fixture
async def sync(tmp_path, s3_settings):
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode and build_image():
        pytest.skip("no sandbox image")
    settings, keys = s3_settings(tmp_path, prefix=f"sync-{uuid.uuid4().hex[:6]}/{{user_id}}/", mount="sync",
                                 workspaces_dir=str(tmp_path / "ws"))
    sb = DockerSandbox(settings)
    sb.store = S3Store(settings, keys)
    yield sb
    await sb.close_all()
    for user in sb.boxes:
        subprocess.run(["docker", "volume", "rm", "-f", f"simp-home-{user}", f"simp-work-{user}"], capture_output=True)


async def test_sync_roundtrip(sync):
    user = f"u{uuid.uuid4().hex[:6]}"
    await sync.store.write(user, "old.txt", b"before start")
    env = await sync.open("s1", user)
    run = lambda cmd: env.exec(cmd, "/work", 60, asyncio.Event())  # noqa: E731
    assert (await run("cat old.txt; echo; id -u"))[1].split("\n")[:2] == ["before start", "1000"]  # pulled at start
    assert (await run("mountpoint -q /work/.. ; touch /work/x && echo ok"))[1].strip().endswith("ok")
    await run("echo agent > agent.txt; rm old.txt")
    await env.after_tool()
    await sync.boxes[user].ws.task
    assert await sync.store.read(user, "agent.txt") == b"agent\n"  # pushed after the tool call
    with pytest.raises(FileNotFoundError):
        await sync.store.read(user, "old.txt")
    # Files panel upload while the container runs: there before the next call
    await sync.store.write(user, "panel.txt", b"from panel")
    sync.web_changed(user)
    assert (await run("cat panel.txt"))[1] == "from panel"
    # no network in the container: the server moves the files
    assert (await run("python3 -c 'import socket; socket.create_connection((\"1.1.1.1\", 80), 3)' 2>&1 | tail -1"))[1]
    # stop flushes; a new container starts from the bucket (+ snapshot)
    await run("echo last > last.txt")
    await sync.close("s1")
    assert await sync.store.read(user, "last.txt") == b"last\n"
    env = await sync.open("s2", user)
    out = (await env.exec("ls", "/work", 60, asyncio.Event()))[1].split()
    assert sorted(out) == ["agent.txt", "last.txt", "panel.txt", "x"]
