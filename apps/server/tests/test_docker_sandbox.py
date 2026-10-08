import asyncio
import shutil
import subprocess
import uuid

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


class TestDockerEnvConformance(EnvConformance):
    @pytest.fixture
    def make_env(self, sandbox, tmp_path):
        async def make(root):
            sandbox.workspaces_dir = root.parent
            return await sandbox.open(root.name)
        return make


async def test_hardening(sandbox, tmp_path):
    env = await sandbox.open(f"s1-{uuid.uuid4().hex[:8]}")
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
    env = await sandbox.open(sid)
    assert await sandbox.open(sid) is env
    with pytest.raises(ValueError):
        await sandbox.open("../x")
    await sandbox.close(sid)
    assert subprocess.run(["docker", "inspect", env.container], capture_output=True).returncode != 0
