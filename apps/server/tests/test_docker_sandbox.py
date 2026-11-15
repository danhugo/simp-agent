import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from simp_agent.testing.env_conformance import EnvConformance
from simp_server.sandboxes.docker import IMAGE, DockerSandbox, build_image


def _docker_ok():
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode:
        return False
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
        return build_image() == 0
    return True


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="docker not available")


@pytest.fixture
async def sandbox(tmp_path):
    sb = DockerSandbox({"data_dir": str(tmp_path), "sandbox": {"workspaces_dir": str(tmp_path / "ws")}})
    yield sb
    await sb.close_all()
    for user in sb.boxes:
        subprocess.run(["docker", "volume", "rm", "-f", f"simp-home-{user}"], capture_output=True)


class TestDockerEnvConformance(EnvConformance):
    @pytest.fixture
    def make_env(self, sandbox, tmp_path):
        async def make(root):
            sandbox.workspaces_dir = root.parent
            return await sandbox.open(f"s-{uuid.uuid4().hex[:8]}", root.name)
        return make


async def test_hardening(sandbox, tmp_path):
    env = await sandbox.open(f"s1-{uuid.uuid4().hex[:8]}", "u1")
    run = lambda cmd: env.exec(cmd, ".", 30, asyncio.Event())
    assert (await run("id -u"))[1].strip() == "1000"
    code, out = await run("python -c 'import socket; socket.create_connection((\"1.1.1.1\", 53), timeout=3)'")
    assert code != 0
    assert (await run("touch /etc/x"))[0] != 0  # read-only rootfs
    assert (await run("touch /tmp/x && touch /work/x"))[0] == 0
    assert (await run("grep CapEff /proc/self/status"))[1].split()[1] == "0000000000000000"  # no caps
    code, out = await run("for i in $(seq 400); do sleep 5 & done; wait")
    assert "fork" in out.lower() or "resource" in out.lower()  # pids limit hit


async def test_open_close(sandbox):
    sid = f"s2-{uuid.uuid4().hex[:8]}"
    env = await sandbox.open(sid, "u1")
    assert await sandbox.open(sid, "u1") is env
    with pytest.raises(ValueError):
        await sandbox.open("../x", "u1")
    await sandbox.close(sid)
    assert subprocess.run(["docker", "inspect", env.container], capture_output=True).returncode != 0


async def test_coding_tools_with_host_paths(sandbox):
    """ls/grep get the host workspace path from the tools; inside the container that is /work."""
    from simp_agent.coding import make_tools
    env = await sandbox.open("s-paths", "u1")
    await env.write_bytes("notes.txt", b"hello world\n")

    from simp_agent.agent import ToolContext

    async def noop(_): pass
    ctx = ToolContext(asyncio.Event(), env, env.root, noop)
    tools = {t.name: t for t in make_tools()}
    assert "notes.txt" in await tools["ls"].execute({}, ctx)
    assert "hello world" in await tools["grep"].execute({"pattern": "hello"}, ctx)
    assert (await env.read_bytes("/work/notes.txt")) == b"hello world\n"  # container paths work host-side too


async def test_user_sessions_share_one_container(sandbox):
    a, b = f"sa-{uuid.uuid4().hex[:8]}", f"sb-{uuid.uuid4().hex[:8]}"
    user = f"u-{uuid.uuid4().hex[:8]}"
    ea, eb = await sandbox.open(a, user), await sandbox.open(b, user)
    assert ea.container == eb.container == f"simp-u-{user}" and ea.root == eb.root
    assert not ea.box.running  # lazy: open starts nothing
    await ea.write_bytes("shared.txt", b"hi")
    assert not ea.box.running  # /work file ops run on the host mount
    assert (await ea.exec("cat shared.txt", ".", 30, asyncio.Event()))[1] == "hi"
    await sandbox.close(a)  # b still uses the container
    assert (await eb.exec("cat shared.txt", ".", 30, asyncio.Event()))[1] == "hi"
    await sandbox.close(b)
    assert subprocess.run(["docker", "inspect", ea.container], capture_output=True).returncode != 0
    subprocess.run(["docker", "volume", "rm", "-f", f"simp-home-{user}"], capture_output=True)


async def test_repo_survives_container_loss(sandbox):
    """A repo under /home/user/repos is mirrored to /work/.simp/repos after a tool call and restored on the next
    start, even with the home volume gone."""
    from simp_agent.agent import ToolContext
    from simp_agent.coding import make_tools
    user, sid = f"u-{uuid.uuid4().hex[:8]}", f"s-{uuid.uuid4().hex[:8]}"
    env = await sandbox.open(sid, user)
    run = lambda cmd: env.exec(cmd, ".", 60, asyncio.Event())
    code, out = await run("mkdir -p /home/user/repos/app && cd /home/user/repos/app && git init -q -b main && "
                          "echo a > a.txt && echo '.env' > .gitignore && echo SECRET=1 > .env && "
                          "git add -A && git -c user.name=t -c user.email=t@t commit -qm init && echo b > b.txt")
    assert code == 0, out
    tools = {t.name: t for t in make_tools()}

    async def noop(_): pass
    ctx = ToolContext(asyncio.Event(), env, env.root, noop)
    await tools["write"].execute({"path": "/home/user/repos/app/c.txt", "content": "c\n"}, ctx)  # via the container
    assert "c" in await tools["read"].execute({"path": "/home/user/repos/app/c.txt"}, ctx)
    await env.after_tool()
    assert (Path(env.root) / ".simp/repos/app.git").is_dir()
    await sandbox.close(sid)
    subprocess.run(["docker", "volume", "rm", "-f", f"simp-home-{user}"], capture_output=True)
    env = await sandbox.open(sid, user)
    code, out = await env.exec("cd /home/user/repos/app && cat a.txt b.txt c.txt .env && git status --porcelain && "
                               "git branch --show-current", ".", 60, asyncio.Event())
    assert code == 0, out
    assert "SECRET=1" in out and "?? b.txt" in out and "?? c.txt" in out and out.strip().endswith("main")
    await sandbox.close(sid)
    subprocess.run(["docker", "volume", "rm", "-f", f"simp-home-{user}"], capture_output=True)


async def test_container_killed_behind_the_box_is_restarted(sandbox):
    """Review C1: docker's "No such container" is not taken as the pid; the box is marked gone and the call runs
    once on a fresh container."""
    user = f"u-{uuid.uuid4().hex[:8]}"
    env = await sandbox.open(f"s-{uuid.uuid4().hex[:8]}", user)
    assert (await env.exec("echo one", ".", 30, asyncio.Event())) == (0, "one\n")
    subprocess.run(["docker", "rm", "-f", env.container], check=True, capture_output=True)
    assert (await env.exec("echo two", ".", 30, asyncio.Event())) == (0, "two\n")
    assert env.box.running
    assert subprocess.run(["docker", "inspect", env.container], capture_output=True).returncode == 0
    subprocess.run(["docker", "volume", "rm", "-f", f"simp-home-{user}"], capture_output=True)
