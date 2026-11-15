"""DockerSandbox in fuse mode (design "dev with prod semantics"): MinIO bucket + s3fs at /work in the container.
Runs when docker and the dev MinIO are available (the `minio` fixture), skips otherwise."""

import asyncio
import subprocess
import uuid

import pytest

from simp_agent.testing.env_conformance import EnvConformance
from simp_server.sandboxes.docker import IMAGE, DockerSandbox, build_image
from simp_server.workspace import S3Store


@pytest.fixture
async def fuse(tmp_path, s3_settings):
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode and build_image():
        pytest.skip("no sandbox image")
    settings, keys = s3_settings(tmp_path, prefix=f"fuse-{uuid.uuid4().hex[:6]}/{{user_id}}/", mount="fuse",
                                 workspaces_dir=str(tmp_path / "ws"))
    sb = DockerSandbox(settings)
    sb.store = S3Store(settings, keys)
    yield sb
    await sb.close_all()
    for user in sb.boxes:
        subprocess.run(["docker", "volume", "rm", "-f", f"simp-home-{user}"], capture_output=True)


class TestFuseEnvConformance(EnvConformance):
    @pytest.fixture
    def make_env(self, fuse):
        async def make(root):
            fuse.workspaces_dir = root.parent
            return await fuse.open(f"s-{uuid.uuid4().hex[:8]}", root.name)
        return make

    async def test_containment(self, env):
        pytest.skip("host symlinks: /work is the bucket in fuse mode; '..' escapes are covered below")

    async def test_exec_cwd(self, env):  # the dir is made in the container: the host root is not /work here
        await self.run(env, "mkdir sub")
        code, text = await self.run(env, "pwd", cwd=self.root / "sub")
        assert code == 0 and text.strip() == "/work/sub"


async def test_fuse_one_store_two_views(fuse):
    user = f"u{uuid.uuid4().hex[:6]}"
    env = await fuse.open("s1", user)
    run = lambda cmd: env.exec(cmd, "/work", 60, asyncio.Event())  # noqa: E731
    assert (await run("mountpoint -q /work && id -u"))[1].strip() == "1000"
    assert (await run("grep CapEff /proc/self/status"))[1].split()[1] == "0000000000000000"  # commands: no caps
    await env.write_file("/work/agent.txt", "from agent")
    assert await fuse.store.read(user, "agent.txt") == b"from agent"  # written through the mount
    await fuse.store.write(user, "panel.txt", b"from panel")  # Files panel upload -> store
    await asyncio.sleep(6)  # s3fs stat cache (stat_cache_expire=5)
    assert (await run("cat panel.txt"))[1] == "from panel"
    with pytest.raises(PermissionError):
        await env.read_file("/work/../etc/passwd")
    # a repo under /home/user/repos is mirrored onto the mount after the tool call
    assert (await run("mkdir -p /home/user/repos/r && cd /home/user/repos/r && git init -q && echo a > a && "
                      "git -c user.name=t -c user.email=t@t commit -qam x --allow-empty && git add a"))[0] == 0
    await env.after_tool()
    assert any(o["name"] == "r.git" for o in await fuse.store.list(user, ".simp/repos"))
