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
        return 0, ""

    async def _exec_in(container, command, cwd, timeout, cancel, on_output=None):
        calls.append(("exec", container, command))
        if ev := gate.get(command):
            await ev.wait()
        return 0, ""

    async def noop(*a, **k):
        return ""

    monkeypatch.setattr(docker, "_docker", _docker)
    monkeypatch.setattr(docker, "_exec_in", _exec_in)
    monkeypatch.setattr(docker, "restore_repos", noop)
    monkeypatch.setattr(docker, "mirror_repos", noop)
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


async def test_chat_only_session_starts_no_container(tmp_path, fake_docker):
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


async def test_idle_stop_never_during_a_running_tool(tmp_path, fake_docker):
    calls, gate = fake_docker
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
