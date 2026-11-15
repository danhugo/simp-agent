import os

import pytest

from simp_agent.agent.env import LocalEnv
from simp_agent.testing.env_conformance import EnvConformance


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


class TestLocalEnvConformance(EnvConformance):
    @pytest.fixture
    def make_env(self):
        return lambda root: LocalEnv(str(root))


async def test_symlink_swapped_in_after_the_path_check_is_refused(tmp_path, monkeypatch):
    """Review M3: a sandboxed process sharing the dir flips d/ to a symlink to an outside dir between the path check
    and the open. Simulated by swapping right after the check of d/ passes (or at the first os.open); read, write, list must refuse."""
    import os
    import shutil
    from pathlib import Path

    from simp_agent.agent.env import LocalEnv
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f").write_text("secret")
    root = tmp_path / "root"
    env = LocalEnv(str(root))

    def arm():
        (root / "d").mkdir(parents=True, exist_ok=True)
        (root / "d" / "f").write_text("mine")
        fired = []
        real_resolve, real_open = Path.resolve, os.open

        def swap():
            if not fired:
                fired.append(1)
                shutil.rmtree(root / "d")
                os.symlink(outside, root / "d")

        def resolve(self, *a, **k):
            r = real_resolve(self, *a, **k)
            if r.is_relative_to(real_resolve(root / "d")):  # the check of d/... passed: now swap
                swap()
            return r

        def op(*a, **k):
            swap()
            return real_open(*a, **k)
        monkeypatch.setattr(Path, "resolve", resolve)
        monkeypatch.setattr(os, "open", op)

    for call in (lambda: env.read_bytes("d/f"), lambda: env.write_bytes("d/f", b"pwned"), lambda: env.list("d")):
        arm()
        with pytest.raises(PermissionError):
            await call()
        monkeypatch.undo()
        (root / "d").unlink()
    assert (outside / "f").read_text() == "secret"
