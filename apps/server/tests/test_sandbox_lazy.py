"""Lazy per-user Docker sandbox and repo mirror, without docker: docker calls are faked; the mirror runs on LocalEnv."""

import asyncio
import subprocess

import pytest
from simp_agent.agent.env import LocalEnv
from simp_agent.testing import FakeProvider

from simp_server import protocol as p
from simp_server.sandboxes import docker, repos
from simp_server.server import create_app, load_settings

from simp_agent.ai import AssistantMessage, TextContent, ToolCall


def reply(text="done", calls=()):
    return AssistantMessage([TextContent(text), *calls], stop_reason="tool_use" if calls else "stop",
                            usage={"input": 10, "output": 5})


def bash(cid, cmd):
    return reply("", [ToolCall(cid, "bash", {"command": cmd})])


async def wait_for(cond, timeout=5):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timeout")


@pytest.fixture
def fake_docker(monkeypatch):
    calls, gate = list(), dict()

    async def _docker(*args, stdin=None):
        calls.append(args)
        await asyncio.sleep(0)  # a real docker call yields: lets concurrent starts interleave
        return 0, ""

    async def _exec_in(container, command, cwd, timeout, cancel, on_output=None):
        calls.append(("exec", container, command))
        if ev := gate.get(command):
            await ev.wait()
        return 0, ""

    async def noop(*a, **k):
        return "SIMP_DONE"

    monkeypatch.setattr(docker, "_docker", _docker)
    monkeypatch.setattr(docker, "_exec_in", _exec_in)
    monkeypatch.setattr(docker, "restore_repos", noop)
    monkeypatch.setattr(repos, "mirror_repos", noop)
    return calls, gate


def runs(calls):
    return [c for c in calls if c[0] == "run"]


def sandbox(tmp_path, **opts):
    return docker.DockerSandbox({"data_dir": str(tmp_path), "sandbox": opts})


async def test_open_and_file_ops_start_nothing(tmp_path, fake_docker):
    calls, _ = fake_docker
    sb = sandbox(tmp_path)
    env = await sb.open("s1", "u1")
    await env.write_file("/work/a.txt", "hi")
    assert await env.read_file("a.txt") == "hi" and (await env.list("."))[0]["name"] == "a.txt"
    assert calls == []
    await env.exec("ls", ".", None, asyncio.Event())
    assert len(runs(calls)) == 1 and "simp-u-u1" in runs(calls)[0] and "simp-home-u1:/home/user" in runs(calls)[0]


async def test_chat_only_session_starts_no_container(tmp_path, fake_docker, ask_all):
    calls, _ = fake_docker
    (tmp_path / "settings.toml").write_text('[plugins]\nsandbox = "simp_server.sandboxes.docker:DockerSandbox"\n'
                                            '[profiles.test]\napi = "fake"\nmodel = "m"\n')
    app = create_app(load_settings(tmp_path), FakeProvider(reply("hello"), bash("c1", "echo hi"), reply()))
    mgr = app.state.mgr
    await mgr.store.open()
    user = await mgr.store.user_by_token(await mgr.store.add_user("d"))
    run = await mgr.get(user, (await mgr.store.add_session(user["id"], "test", "t"))["id"])
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: run.task and run.task.done())
    assert runs(calls) == []  # chat (and the context-file read) never starts a container
    assert "/home/user/repos" in await run.session._build_prompt()
    await run.command(p.Prompt(text="run it"))
    await wait_for(lambda: run.pending is not None)
    await run.command(p.Approve(call_id="c1", decision="allow"))
    await wait_for(lambda: run.state == "idle" and run.task.done())
    assert len(runs(calls)) == 1
    assert ("exec", "simp-u-" + user["id"], "sync") in calls  # after-tool durability hook
    await mgr.store.close()


async def test_sessions_of_a_user_share_one_container(tmp_path, fake_docker):
    calls, _ = fake_docker
    sb = sandbox(tmp_path)
    a, b, other = await sb.open("sa", "u1"), await sb.open("sb", "u1"), await sb.open("sc", "u2")
    await asyncio.gather(*(e.exec("true", ".", None, asyncio.Event()) for e in (a, b, a)))
    await other.exec("true", ".", None, asyncio.Event())
    assert [r[r.index("--name") + 1] for r in runs(calls)] == ["simp-u-u1", "simp-u-u2"]
    await sb.close("sa")
    assert b.box.running  # one session ending does not kill the other's container
    await sb.close("sb")
    assert not b.box.running and ("rm", "-f", "simp-u-u1") in calls


async def test_idle_stop_never_during_a_running_tool(tmp_path, fake_docker, monkeypatch):
    calls, gate = fake_docker
    # exact clock: with a real monotonic value (Linux: seconds since boot), (last + 600) - last can round to
    # 599.999..., so the "exactly idle_pause_s" step flaked on CI
    monkeypatch.setattr(docker, "time", type("Clock", (), {"monotonic": staticmethod(lambda: 1000.0)}))
    sb = sandbox(tmp_path, idle_pause_s=600)
    env = await sb.open("s1", "u1")
    gate["sleep 1000"] = asyncio.Event()
    task = asyncio.create_task(env.exec("sleep 1000", ".", None, asyncio.Event()))
    await wait_for(lambda: env.box.running and env.box.active == 1)
    await sb.stop_idle(now=env.box.last + 10_000)
    assert env.box.running
    gate["sleep 1000"].set()
    await task
    await sb.stop_idle(now=env.box.last + 599)
    assert env.box.running
    await sb.stop_idle(now=env.box.last + 600)
    assert not env.box.running
    await env.exec("true", ".", None, asyncio.Event())  # next tool call starts it again
    assert env.box.running and len(runs(calls)) == 2


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout


async def test_mirror_and_restore_round_trip(tmp_path):
    env, home, mirrors = LocalEnv(), tmp_path / "home" / "repos", tmp_path / "work" / ".simp" / "repos"
    repo = home / "app"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / ".gitignore").write_text(".env\nnode_modules/\nbig.bin\n")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "tag", "v1")
    git(repo, "remote", "add", "upstream", "https://example.invalid/app.git")
    (repo / "a.txt").write_text("a changed\n")  # uncommitted change
    (repo / "new.txt").write_text("untracked\n")
    (repo / ".env").write_text("SECRET=1\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "x.js").write_text("x")
    (repo / "big.bin").write_bytes(b"0" * (11 * 2**20))
    index_before = (repo / ".git" / "index").read_bytes()

    out = await repos.mirror_repos(env, str(home), str(mirrors), "sess1", cwd=str(tmp_path))
    assert "ok app" in out, out
    assert (repo / ".git" / "index").read_bytes() == index_before and git(repo, "status", "--porcelain")  # untouched
    assert "1" == git(mirrors / "app.git", "config", "receive.unpackLimit").strip()
    assert "refs/simp/wip/sess1" in git(mirrors / "app.git", "for-each-ref")
    archive = next(mirrors.glob("app.ignored.tar.*"))
    mtime = archive.stat().st_mtime_ns
    assert "ok app" in await repos.mirror_repos(env, str(home), str(mirrors), "sess1", cwd=str(tmp_path))
    assert archive.stat().st_mtime_ns == mtime  # unchanged: nothing pushed or packed again

    import shutil
    shutil.rmtree(repo)
    out = await repos.restore_repos(env, str(home), str(mirrors), cwd=str(tmp_path))
    assert "restored app" in out, out
    assert (repo / "a.txt").read_text() == "a changed\n" and (repo / "new.txt").read_text() == "untracked\n"
    assert (repo / ".env").read_text() == "SECRET=1\n"
    assert not (repo / "node_modules").exists() and not (repo / "big.bin").exists()
    assert not (repo / ".simp-not-backed-up.txt").exists()
    status = git(repo, "status", "--porcelain")
    assert " M a.txt" in status and "?? new.txt" in status
    assert git(repo, "branch", "--show-current").strip() == "main" and "v1" in git(repo, "tag")
    assert "upstream" in git(repo, "remote") and "origin" not in git(repo, "remote")
    # the manifest lists what was not backed up
    import tarfile
    if archive.suffix == ".gz":
        with tarfile.open(archive) as t:
            assert "big.bin" in t.extractfile(".simp-not-backed-up.txt").read().decode()


async def test_mirror_repo_without_commits_and_failures_never_raise(tmp_path):
    env, home, mirrors = LocalEnv(), tmp_path / "repos", tmp_path / "mirrors"
    repo = home / "fresh"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "dev")
    (repo / "x.txt").write_text("x\n")
    assert "ok fresh" in await repos.mirror_repos(env, str(home), str(mirrors), "s", cwd=str(tmp_path))
    import shutil
    shutil.rmtree(repo)
    assert "restored fresh" in await repos.restore_repos(env, str(home), str(mirrors), cwd=str(tmp_path))
    assert (repo / "x.txt").read_text() == "x\n" and "?? x.txt" in git(repo, "status", "--porcelain")

    class Broken:
        async def exec(self, *a, **k):
            raise RuntimeError("sandbox gone")
    assert await repos.mirror_repos(Broken(), "/nope", "/nope", "s") == ""


async def test_files_panel_goes_to_the_store_and_starts_nothing(tmp_path, fake_docker):
    import httpx
    calls, _ = fake_docker
    (tmp_path / "settings.toml").write_text('[plugins]\nsandbox = "simp_server.sandboxes.docker:DockerSandbox"\n'
                                            '[profiles.test]\napi = "fake"\nmodel = "m"\n')
    app = create_app(load_settings(tmp_path), FakeProvider())
    mgr = app.state.mgr
    await mgr.store.open()
    token = await mgr.store.add_user("d")
    user = await mgr.store.user_by_token(token)
    sid = (await mgr.store.add_session(user["id"], "test", "t"))["id"]
    h, base = {"Authorization": f"Bearer {token}"}, f"/api/sessions/{sid}/files"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.put(base + "/raw?path=/work/up.txt", headers=h, content=b"x")).status_code == 200
        assert (await c.get(base, headers=h)).json() == [{"name": "up.txt", "is_dir": False, "size": 1}]
        assert (await c.get(base + "/raw?path=up.txt", headers=h)).content == b"x"
        assert (await c.get(base + "/raw?path=/home/user/.bashrc", headers=h)).status_code == 403  # /work only
    assert calls == []
    assert (tmp_path / "workspaces" / user["id"] / "up.txt").read_bytes() == b"x"
    await mgr.store.close()


async def test_docker_usage_rows_and_concurrency_limit(tmp_path, fake_docker):
    from simp_server.sandboxes import SandboxLimit
    sb = sandbox(tmp_path, max_running=1)

    class Db:
        rows = []

        async def add_usage(self, *a, **k):
            self.rows.append((a, k))

        async def sandbox_seconds(self, *a):
            return 0
    sb.compute.db = Db()
    env = await sb.open("s1", "u1")
    await env.exec("true", ".", None, asyncio.Event())
    with pytest.raises(SandboxLimit, match="limit is 1"):
        await (await sb.open("s2", "u2")).exec("true", ".", None, asyncio.Event())
    await sb.stop_idle(now=env.box.metered + 42)
    (user, sid, model, secs, out), kw = Db.rows[0]
    assert (user, model, secs, kw["cost"]) == ("u1", "sandbox:docker", 42, 0.0)


def _repo(tmp_path):
    env, home, mirrors = LocalEnv(), tmp_path / "home" / "repos", tmp_path / "work" / ".simp" / "repos"
    repo = home / "app"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n")
    return env, home, mirrors, repo


async def test_restore_skips_symlinks_in_ignored_files_and_keeps_the_repo(tmp_path):
    """Review M5: an absolute symlink in an ignored dir is not archived; a bad archive member is skipped, and a
    failure after the git restore never removes the restored repo."""
    import io
    import os
    import shutil
    import tarfile
    env, home, mirrors, repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("logs/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    (repo / "logs").mkdir()
    (repo / "logs" / "ok.log").write_text("kept\n")
    os.symlink("/etc/hosts", repo / "logs" / "abs")
    assert "ok app" in await repos.mirror_repos(env, str(home), str(mirrors), "s", cwd=str(tmp_path))
    archive = next(mirrors.glob("app.ignored.tar.*"))
    if archive.suffix == ".gz":
        with tarfile.open(archive) as t:
            assert "logs/abs" not in t.getnames()
        # an old archive with an absolute symlink (from before the fix) must not sink the restore
        with tarfile.open(archive, "w:gz") as t:
            t.add(repo / "logs" / "ok.log", "logs/ok.log")
            link = tarfile.TarInfo("logs/abs")
            link.type, link.linkname = tarfile.SYMTYPE, "/etc/hosts"
            t.addfile(link)
            t.addfile(tarfile.TarInfo(".simp-not-backed-up.txt"), io.BytesIO(b""))
    shutil.rmtree(repo)
    out = await repos.restore_repos(env, str(home), str(mirrors), cwd=str(tmp_path))
    assert "restored app" in out, out
    assert (repo / "a.txt").read_text() == "a\n" and (repo / "logs" / "ok.log").read_text() == "kept\n"
    assert not os.path.lexists(repo / "logs" / "abs")


async def test_restore_keeps_wip_deletions_and_never_runs_repo_hooks(tmp_path):
    """git safety: a file deleted in the WIP stays deleted after restore (read-tree), and the repo's own hooks
    (pre-push) never run during the mirror; a status file records the last good mirror."""
    import json
    import shutil
    env, home, mirrors, repo = _repo(tmp_path)
    (repo / "gone.txt").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    (repo / "gone.txt").unlink()
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch {tmp_path / 'HOOK_RAN'}\n")
    hook.chmod(0o755)
    assert "ok app" in await repos.mirror_repos(env, str(home), str(mirrors), "s", cwd=str(tmp_path))
    assert not (tmp_path / "HOOK_RAN").exists()
    assert json.loads((mirrors / "app.status").read_text())["ok_at"] > 0
    shutil.rmtree(repo)
    assert "restored app" in await repos.restore_repos(env, str(home), str(mirrors), cwd=str(tmp_path))
    assert not (repo / "gone.txt").exists() and " D gone.txt" in git(repo, "status", "--porcelain")


async def test_mirrors_of_one_user_run_one_at_a_time(tmp_path, fake_docker, monkeypatch):
    """Review M6: two sessions' after-tool mirrors of one user never overlap."""
    inflight, peak = [0], [0]

    async def mirror(*a, **k):
        inflight[0] += 1
        peak[0] = max(peak[0], inflight[0])
        await asyncio.sleep(0.05)
        inflight[0] -= 1
        return "SIMP_DONE"
    monkeypatch.setattr(repos, "mirror_repos", mirror)
    sb = sandbox(tmp_path)
    a, b = await sb.open("sa", "u1"), await sb.open("sb", "u1")
    await asyncio.gather(*(e.exec("true", ".", None, asyncio.Event()) for e in (a, b)))
    await asyncio.gather(a.after_tool(), b.after_tool())
    assert peak[0] == 1


async def test_slow_mirror_goes_on_in_background_and_stop_waits(tmp_path, fake_docker, monkeypatch):
    """Review M7: the foreground mirror is capped; the rest runs in the background holding the mirror lock, and the
    idle stop waits for it. A failed mirror is retried once before the container is removed."""
    calls, _ = fake_docker
    gate, n = asyncio.Event(), [0]

    async def mirror(*a, **k):
        n[0] += 1
        if n[0] == 1:
            await gate.wait()
            return "FAIL app: boom\nSIMP_DONE"
        return "SIMP_DONE"
    monkeypatch.setattr(repos, "mirror_repos", mirror)
    monkeypatch.setattr(repos, "MIRROR_FG_S", 0.05)
    sb = sandbox(tmp_path, idle_pause_s=1)
    env = await sb.open("s1", "u1")
    await env.exec("true", ".", None, asyncio.Event())
    await asyncio.wait_for(env.after_tool(), 2)  # returns at the cap
    stop = asyncio.create_task(sb.stop_idle(now=env.box.last + 100))
    await asyncio.sleep(0.1)
    rm = lambda: calls.count(("rm", "-f", "simp-u-u1"))  # noqa: E731 (the first is the leftover cleanup at start)
    assert env.box.running and rm() == 1  # waits for the background mirror
    gate.set()
    await stop
    assert not env.box.running and rm() == 2
    assert n[0] == 2  # the failed mirror was retried before the removal


async def test_idle_stop_aborts_when_a_call_starts_while_it_waits(tmp_path, fake_docker):
    """Review C3 (docker): the tick saw active == 0, but a call started before the stop got the lock: no removal."""
    calls, gate = fake_docker
    sb = sandbox(tmp_path, idle_pause_s=1)
    env = await sb.open("s1", "u1")
    await env.exec("true", ".", None, asyncio.Event())
    await env.box.lock.acquire()  # e.g. a credential refresh in progress
    stop = asyncio.create_task(sb.stop_idle(now=env.box.last + 100))
    await asyncio.sleep(0.01)
    gate["sleep 5"] = asyncio.Event()
    call = asyncio.create_task(env.exec("sleep 5", ".", None, asyncio.Event()))
    await wait_for(lambda: ("exec", "simp-u-u1", "sleep 5") in calls)
    env.box.lock.release()
    await stop
    assert env.box.running and calls.count(("rm", "-f", "simp-u-u1")) == 1  # only the start's cleanup
    gate["sleep 5"].set()
    await call


async def test_concurrent_starts_respect_max_running(tmp_path, fake_docker):
    """Review M8: the slot is reserved under a global lock before `docker run`."""
    from simp_server.sandboxes import SandboxLimit
    sb = sandbox(tmp_path, max_running=1)
    envs = [await sb.open(f"s{i}", f"u{i}") for i in range(3)]
    res = await asyncio.gather(*(e.exec("true", ".", None, asyncio.Event()) for e in envs), return_exceptions=True)
    assert sum(isinstance(r, SandboxLimit) for r in res) == 2 and sb.running() == 1


async def test_budget_enforced_in_the_tick(tmp_path, fake_docker):
    """Review M8: a box that went over its daily budget stops after its current call; new calls are refused."""
    from simp_server.sandboxes import SandboxLimit
    sb = sandbox(tmp_path, day_minutes=1)

    class Db:
        seconds = 0

        async def add_usage(self, *a, **k):
            pass

        async def sandbox_seconds(self, *a):
            return self.seconds
    sb.compute.db = Db()
    env = await sb.open("s1", "u1")
    await env.exec("true", ".", None, asyncio.Event())
    sb.compute.db.seconds = 61
    env.box.active = 1  # a call is running: not stopped under it
    await sb.stop_idle(now=env.box.last + 1)
    assert env.box.running and env.box.over
    env.box.active = 0
    await sb.stop_idle(now=env.box.last + 1)
    assert not env.box.running
    with pytest.raises(SandboxLimit, match="budget"):
        await env.exec("true", ".", None, asyncio.Event())


async def test_fuse_stop_unmounts_before_removal(tmp_path, fake_docker):
    """Review M10: fuse mode stops user processes and unmounts /work as root (s3fs flushes) before `docker rm`."""
    calls, _ = fake_docker
    sb = sandbox(tmp_path, mount="fuse")

    class Store:
        async def mount_creds(self, user_id):
            return {"endpoint": "http://s3", "bucket": "b", "prefix": "p/", "region": "r", "access_key": "k",
                    "secret_key": "s", "session_token": "t", "expires_in": 3600}
    sb.store = Store()
    env = await sb.open("s1", "u1")
    await env.exec("true", ".", None, asyncio.Event())
    await sb.close("s1")
    i = next(i for i, c in enumerate(calls) if "umount /work" in " ".join(c) and "pkill -TERM" in " ".join(c))
    assert calls[i][:4] == ("exec", "-u", "0", "simp-u-u1")
    assert calls.index(("rm", "-f", "simp-u-u1"), 1) > i


async def test_to_container_replaces_the_root_only_on_a_path_boundary(tmp_path, fake_docker):
    sb = sandbox(tmp_path)
    env = await sb.open("s1", "u1")
    root = str(env.root)
    assert env._to_container(f"ls {root} {root}/a {root}0/x {root}-b {root}.x") == f"ls /work /work/a {root}0/x {root}-b {root}.x"
