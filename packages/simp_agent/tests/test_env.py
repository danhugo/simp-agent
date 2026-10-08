import os

import pytest

from simp_agent.agent.env import LocalEnv


async def test_local_env_files(tmp_path):
    env = LocalEnv(str(tmp_path))
    await env.write_bytes("d/a.bin", b"\x00\xff")
    assert await env.read_bytes("d/a.bin") == b"\x00\xff"
    await env.write_file("b.txt", "hi")
    assert await env.read_file("b.txt") == "hi"
    assert await env.list(".") == [{"name": "b.txt", "is_dir": False, "size": 2}, {"name": "d", "is_dir": True, "size": 0}]


async def test_local_env_containment(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret").write_text("s")
    os.symlink(tmp_path / "secret", root / "link")
    env = LocalEnv(str(root))
    for bad in ("../secret", "link", str(tmp_path / "secret")):
        with pytest.raises(PermissionError):
            await env.read_bytes(bad)
    with pytest.raises(PermissionError):
        await env.write_bytes("../x", b"")
    with pytest.raises(PermissionError):
        await env.list("..")
