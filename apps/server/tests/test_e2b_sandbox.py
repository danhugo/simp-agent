"""E2BSandbox lifecycle against FakeE2B (an in-process fake of the SDK surface we use), plus a live test gated on
E2B_API_KEY and an S3 test bucket (SIMP_TEST_S3_ENDPOINT/BUCKET/KEY/SECRET)."""

import asyncio
import itertools
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from simp_server.sandboxes import SandboxLimit
from simp_server.sandboxes import e2b as e2b_mod
from simp_server.sandboxes.e2b import E2BSandbox


class FakeHandle:
    def __init__(self, sbx, cmd, gate, on_stdout):
        self.sbx, self.cmd, self.gate, self.on_stdout, self.killed = sbx, cmd, gate, on_stdout, False

    async def wait(self):
        await self.on_stdout("4242\n")  # the setsid wrapper's pid line
        if self.gate:
            await self.gate.wait()
        code = self.sbx.cloud.codes.pop(self.cmd, 0)  # one-shot
        if code:
            from e2b import CommandExitException
            raise CommandExitException(stdout="", stderr="", exit_code=code, error=None)
        return SimpleNamespace(exit_code=0)

    async def kill(self):
        self.killed = True


class FakeSandbox:
    """One fake sandbox. `cloud` is the shared FakeE2B (all sandboxes, call log, gates)."""

    def __init__(self, cloud, metadata):
        self.cloud, self.sandbox_id, self.metadata = cloud, f"sbx-{next(cloud.ids)}", metadata
        self.state, self.files_ = "running", dict()
        self.commands = SimpleNamespace(run=self._run)
        self.files = SimpleNamespace(read=self._read, write=self._write, list=self._list)
        self.started_at = datetime.now(timezone.utc)

    async def _run(self, cmd, background=None, cwd=None, user=None, envs=None, on_stdout=None, on_stderr=None, timeout=60):
        if self.state != "running":
            from e2b.exceptions import SandboxNotRunningException
            raise SandboxNotRunningException("paused")
        inner = cmd.split("' ", 1)[1].strip("'") if cmd.startswith("setsid") else cmd
        self.cloud.log.append(("run", self.sandbox_id, user, inner))
        return FakeHandle(self, inner, self.cloud.gates.get(inner), on_stdout or (lambda t: asyncio.sleep(0)))

    async def _read(self, path, format="text"):
        if path not in self.files_:
            from e2b.exceptions import NotFoundException
            raise NotFoundException(path)
        return self.files_[path]

    async def _write(self, path, data):
        self.files_[path] = data

    async def _list(self, path, depth=1):
        return [SimpleNamespace(name=p.rsplit("/", 1)[1], type="file", size=len(d))
                for p, d in self.files_.items() if p.rsplit("/", 1)[0] == path]

    async def pause(self):
        self.cloud.log.append(("pause", self.sandbox_id))
        self.state = "paused"

    async def kill(self):
        self.cloud.log.append(("kill", self.sandbox_id))
        self.cloud.boxes.pop(self.sandbox_id, None)

    async def set_timeout(self, t):
        self.cloud.log.append(("set_timeout", self.sandbox_id, t))


class FakeE2B:
    """Stands in for e2b.AsyncSandbox: create/connect/kill/pause/list class methods."""

    def __init__(self):
        self.ids, self.boxes, self.log, self.gates, self.codes = itertools.count(1), dict(), list(), dict(), dict()

    async def create(self, template=None, timeout=None, metadata=None, lifecycle=None, **kw):
        sbx = FakeSandbox(self, metadata)
        self.boxes[sbx.sandbox_id] = sbx
        self.log.append(("create", sbx.sandbox_id, metadata["user_id"], timeout, lifecycle["on_timeout"]))
        return sbx

    async def connect(self, sandbox_id, timeout=None, **kw):
        from e2b.exceptions import SandboxNotFoundException
        if sandbox_id not in self.boxes:
            raise SandboxNotFoundException(sandbox_id)
        sbx = self.boxes[sandbox_id]
        self.log.append(("connect", sandbox_id))
        sbx.state = "running"
        return sbx

    async def kill(self, sandbox_id, **kw):
        self.log.append(("kill", sandbox_id))
        self.boxes.pop(sandbox_id, None)

    async def pause(self, sandbox_id, **kw):
        self.log.append(("pause", sandbox_id))
        self.boxes[sandbox_id].state = "paused"

    def list(self, query=None, **kw):
        items = [SimpleNamespace(sandbox_id=b.sandbox_id, metadata=b.metadata, state=b.state, started_at=b.started_at)
                 for b in self.boxes.values() if all(b.metadata.get(k) == v for k, v in (query.metadata or {}).items())]
        pg = SimpleNamespace(has_next=True)

        async def next_items():
            pg.has_next = False
            return items
        pg.next_items = next_items
        return pg

    def runs(self, sub=""):
        return [e[3] for e in self.log if e[0] == "run" and sub in e[3]]

    def kinds(self, kind):
        return [e for e in self.log if e[0] == kind]


class FakeStore:
    async def mount_creds(self, user_id):
        return {"endpoint": "http://s3", "bucket": "b", "prefix": f"users/{user_id}/", "region": "r",
                "access_key": "k", "secret_key": "s", "session_token": "t"}


class FakeDb:
    def __init__(self):
        self.rows, self.seconds = list(), 0.0

    async def add_usage(self, user_id, sid, model, input, output, cost=0.0):
        self.rows.append((user_id, model, input, cost))
        self.seconds += input

    async def sandbox_seconds(self, user_id, since):
        return self.seconds


@pytest.fixture
def cloud(monkeypatch):
    c = FakeE2B()
    monkeypatch.setattr(e2b_mod, "mirror_repos", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(e2b_mod, "restore_repos", lambda *a, **k: asyncio.sleep(0))
    return c


def make(cloud, **opts):
    sb = E2BSandbox({"data_dir": "/nonexistent", "sandbox": {"kind": "e2b", **opts}})
    sb.sdk, sb.store, sb.compute.db = cloud, FakeStore(), FakeDb()
    return sb


def go(env, cmd="true"):
    return env.exec(cmd, ".", None, asyncio.Event())


async def test_lazy_create_mount_restore_and_file_ops(cloud):
    sb = make(cloud)
    env = await sb.open("s1", "u1")
    assert cloud.log == []  # open starts nothing
    await env.write_file("a.txt", "hi")  # file ops go through the sandbox: /work is its mount
    assert cloud.kinds("create") == [("create", "sbx-1", "u1", 900, "pause")]  # provider-side safety net: pause
    sbx = cloud.boxes["sbx-1"]
    assert sbx.files_["/work/a.txt"] == b"hi" and await env.read_file("/work/a.txt") == "hi"
    assert (await env.list("."))[0]["name"] == "a.txt"
    mount = [e for e in cloud.log if e[0] == "run" and "s3fs" in e[3]]
    assert mount and mount[0][2] == "root"
    assert cloud.runs("home.tar.zst")  # home snapshot restored at create
    with pytest.raises(PermissionError):
        await env.read_file("/etc/passwd")
    with pytest.raises(PermissionError):
        await env.read_file("../x")
    with pytest.raises(FileNotFoundError):
        await env.read_file("missing")
    b = await sb.open("s2", "u1")
    await go(b)
    assert len(cloud.kinds("create")) == 1  # sessions of a user share one sandbox


async def test_idle_pause_then_resume_remounts_when_mount_is_dead(cloud):
    sb = make(cloud, idle_pause_s=600)
    env = await sb.open("s1", "u1")
    await go(env)
    await sb.stop_idle(now=env.box.last + 599)
    assert env.box.state == "running"
    await sb.stop_idle(now=env.box.last + 600)
    assert env.box.state == "paused" and cloud.kinds("pause")
    snap = [r for r in cloud.runs() if "zstd -q -f" in r]
    assert snap, "home snapshot at pause"
    cloud.codes["mountpoint -q /work && ls /work >/dev/null"] = 1  # the mount died while paused
    n_mounts = len(cloud.runs("s3fs"))
    await go(env, "echo hi")
    assert cloud.kinds("connect") and len(cloud.kinds("create")) == 1  # resumed, not recreated
    assert len(cloud.runs("s3fs")) == n_mounts + 1  # remounted (fresh creds)
    assert cloud.runs("echo hi")


async def test_resume_failure_creates_fresh(cloud):
    sb = make(cloud)
    env = await sb.open("s1", "u1")
    await go(env)
    await sb.stop_idle(now=env.box.last + 10_000)
    cloud.boxes.clear()  # provider lost it
    await go(env)
    assert len(cloud.kinds("create")) == 2 and env.box.state == "running"


async def test_max_life_kill_waits_for_foreground_call(cloud):
    sb = make(cloud, max_life_s=3300, idle_pause_s=10_000)
    env = await sb.open("s1", "u1")
    gate = cloud.gates["sleep 100"] = asyncio.Event()
    task = asyncio.create_task(go(env, "sleep 100"))
    for _ in range(200):
        if cloud.runs("sleep 100"):
            break
        await asyncio.sleep(0.01)
    await sb.stop_idle(now=env.box.started + 4000)
    assert env.box.state == "running" and not cloud.kinds("kill")  # never during a foreground call
    gate.set()
    assert (await task)[0] == 0
    await sb.stop_idle(now=env.box.started + 4000)
    assert env.box.state == "none" and cloud.kinds("kill")
    assert any("umount /work" in r for r in cloud.runs())  # snapshot, sync, unmount before kill
    await go(env)
    assert len(cloud.kinds("create")) == 2


async def test_snapshot_schedule(cloud):
    sb = make(cloud, snapshot_every_s=900, idle_pause_s=10_000)
    env = await sb.open("s1", "u1")
    await go(env)
    n = len(cloud.runs("zstd -q -f"))
    env.box.active = 1  # a call is running: snapshots still happen on schedule
    await sb.stop_idle(now=env.box.snap_at + 899)
    assert len(cloud.runs("zstd -q -f")) == n
    await sb.stop_idle(now=env.box.snap_at + 900)
    assert len(cloud.runs("zstd -q -f")) == n + 1
    env.box.active = 0


async def test_orphan_cleanup_on_start(cloud):
    a = await cloud.create(metadata={"app": "simp", "user_id": "u1"}, lifecycle={"on_timeout": "pause"})
    b = await cloud.create(metadata={"app": "simp", "user_id": "u1"}, lifecycle={"on_timeout": "pause"})
    a.state = "paused"
    other = await cloud.create(metadata={"app": "other", "user_id": "u9"}, lifecycle={"on_timeout": "pause"})
    sb = make(cloud)
    await sb.start()
    assert sb.boxes["u1"].sbx_id == a.sandbox_id and sb.boxes["u1"].state == "paused"  # paused one adopted
    assert b.sandbox_id not in cloud.boxes  # duplicate killed
    assert other.sandbox_id in cloud.boxes  # not ours
    env = await sb.open("s1", "u1")
    await go(env)
    assert ("connect", a.sandbox_id) in cloud.log and len(cloud.kinds("create")) == 3


async def test_paused_behind_our_back_is_resumed(cloud):
    sb = make(cloud)
    env = await sb.open("s1", "u1")
    await go(env)
    await cloud.pause(env.box.sbx_id)  # `simp-server sandboxes --pause-all` from another process
    assert (await go(env, "echo again"))[0] == 0
    assert cloud.kinds("connect")


async def test_usage_budget_and_concurrency(cloud):
    sb = make(cloud, max_running=1, day_minutes=1)
    env = await sb.open("s1", "u1")
    await go(env)
    with pytest.raises(SandboxLimit, match="limit is 1"):
        await go(await sb.open("s2", "u2"))
    await sb.stop_idle(now=env.box.metered + 30)
    db = sb.compute.db
    assert db.rows[0][:3] == ("u1", "sandbox:e2b", 30)
    assert db.rows[0][3] == pytest.approx(30 * (2 * 0.000014 + 2 * 0.0000045))
    await sb.stop_idle(now=env.box.last + 10_000)  # pause: the rest is metered
    db.seconds = 60
    with pytest.raises(SandboxLimit, match="daily compute budget of 1 minutes"):
        await go(env)


async def test_close_pauses_after_last_session(cloud):
    sb = make(cloud)
    a, b = await sb.open("sa", "u1"), await sb.open("sb", "u1")
    await go(a)
    await sb.close("sa")
    assert a.box.state == "running"
    await sb.close("sb")
    assert a.box.state == "paused"


LIVE = os.environ.get("E2B_API_KEY") and all(os.environ.get(f"SIMP_TEST_S3_{k}") for k in ("ENDPOINT", "BUCKET", "KEY", "SECRET"))


@pytest.mark.skipif(not LIVE, reason="needs E2B_API_KEY and a SIMP_TEST_S3_* bucket")
async def test_live_e2b(tmp_path):
    from simp_server.workspace import S3Store
    settings = {"data_dir": str(tmp_path), "sandbox": {"kind": "e2b", "tag": "simp-test"},
                "workspace": {"store": "s3", "endpoint": os.environ["SIMP_TEST_S3_ENDPOINT"],
                              "bucket": os.environ["SIMP_TEST_S3_BUCKET"], "mount_scope": os.environ.get("SIMP_TEST_S3_SCOPE", "none"),
                              "prefix": f"test-{uuid.uuid4().hex[:8]}/{{user_id}}/"}}
    store = S3Store(settings, {"S3_ACCESS_KEY_ID": os.environ["SIMP_TEST_S3_KEY"],
                               "S3_SECRET_ACCESS_KEY": os.environ["SIMP_TEST_S3_SECRET"]})
    sb = E2BSandbox(settings)
    sb.store = store
    env = await sb.open("s1", "u1")
    try:
        assert (await env.exec("echo hi > /work/x.txt && cat /work/x.txt", ".", 60, asyncio.Event())) == (0, "hi\n")
        await env.after_tool()
        assert await store.read("u1", "x.txt") == b"hi\n"
        await sb.stop_idle(now=env.box.last + 10_000)
        assert env.box.state == "paused"
        assert (await env.exec("cat /work/x.txt", ".", 60, asyncio.Event())) == (0, "hi\n")
    finally:
        for i in await sb.list_all():
            await sb._sdk.kill(i["id"])
