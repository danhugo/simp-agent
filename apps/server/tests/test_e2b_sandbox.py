"""E2BSandbox lifecycle against FakeE2B (an in-process fake of the SDK surface we use), plus a live test gated on
E2B_API_KEY and an S3 test bucket (SIMP_TEST_S3_ENDPOINT/BUCKET/KEY/SECRET)."""

import asyncio
import itertools
import os
import shlex
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from simp_server.sandboxes import SandboxLimit
from simp_server.sandboxes import e2b as e2b_mod
from simp_server.sandboxes import repos as repos_mod
from simp_server.sandboxes.e2b import E2BSandbox


class FakeHandle:
    def __init__(self, sbx, cmd, gate, on_stdout):
        self.sbx, self.cmd, self.gate, self.on_stdout, self.killed = sbx, cmd, gate, on_stdout, False

    async def wait(self):
        await self.on_stdout("4242\n" + self.sbx.cloud.out.get(self.cmd, ""))  # the setsid wrapper's pid line
        if self.gate:
            await self.gate.wait()
        if self.cmd in self.sbx.cloud.lose:  # paused/killed while the command ran
            self.sbx.state = "paused"
            from e2b.exceptions import SandboxNotRunningException
            raise SandboxNotRunningException("paused")
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
        self.files = SimpleNamespace(read=self._read, write=self._write, list=self._list, exists=self._exists)
        self.started_at = datetime.now(timezone.utc)

    async def _run(self, cmd, background=None, cwd=None, user=None, envs=None, on_stdout=None, on_stderr=None, timeout=60):
        if cmd.startswith("m=/tmp/.simp-"):  # _began: marker file or a frozen process that still has it on its cmdline
            marker = cmd.split(";", 1)[0][2:] + ".started"
            began = marker in self.files_ or marker in self.cloud.frozen
            return SimpleNamespace(stdout="began\n" if began else "no\n", exit_code=0)
        inner = shlex.split(cmd.split("' ", 1)[1].rsplit("; c=$?", 1)[0])[0] if cmd.startswith("setsid") else cmd
        if inner in self.cloud.began:  # buffering proxy: it started, then the sandbox paused before the start event
            self.cloud.began.discard(inner)
            self.files_[cmd.split("touch ", 1)[1].split(" ", 1)[0]] = ""
            self.cloud.log.append(("run", self.sandbox_id, user, inner))
            self.state = "paused"
        if self.state != "running":
            from e2b.exceptions import SandboxNotRunningException
            raise SandboxNotRunningException("paused")
        self.cloud.log.append(("run", self.sandbox_id, user, inner))
        return FakeHandle(self, inner, self.cloud.gates.get(inner), on_stdout or (lambda t: asyncio.sleep(0)))

    async def _read(self, path, format="text"):
        if path not in self.files_:
            from e2b.exceptions import NotFoundException
            raise NotFoundException(path)
        return self.files_[path]

    async def _exists(self, path):
        return path in self.files_

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
        self.out, self.lose, self.began, self.frozen, self.create_delay = dict(), set(), set(), set(), 0

    async def create(self, template=None, timeout=None, metadata=None, lifecycle=None, **kw):
        await asyncio.sleep(self.create_delay)
        sbx = FakeSandbox(self, metadata)
        self.boxes[sbx.sandbox_id] = sbx
        self.log.append(("create", sbx.sandbox_id, metadata["user_id"], timeout, lifecycle["on_timeout"]))
        self.network = kw.get("network")
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
    expires_in = None
    mount_endpoint = "https://acct.r2.cloudflarestorage.com"

    async def mount_creds(self, user_id, read_only=False):
        return {"endpoint": "http://s3", "bucket": "b", "prefix": f"users/{user_id}/", "region": "r",
                "access_key": "k", "secret_key": "s", "session_token": "t", "expires_in": self.expires_in}


class FakeDb:
    def __init__(self):
        self.rows, self.seconds, self.pauses = list(), 0.0, dict()

    async def add_usage(self, user_id, sid, model, input, output, cost=0.0):
        self.rows.append((user_id, model, input, cost))
        if model.startswith("sandbox:"):
            self.seconds += input

    async def add_pause(self, user_id, sbx_id, cpus, mem_gib):
        self.pauses.setdefault(sbx_id, {"user_id": user_id, "paused_at": time.time(), "cpus": cpus, "mem_gib": mem_gib})

    async def pop_pause(self, sbx_id):
        return self.pauses.pop(sbx_id, None)

    async def pause_ids(self):
        return list(self.pauses)

    async def sandbox_seconds(self, user_id, since):
        return self.seconds


@pytest.fixture
def cloud(monkeypatch):
    c = FakeE2B()
    monkeypatch.setattr(repos_mod, "mirror_repos", lambda *a, **k: asyncio.sleep(0, "SIMP_DONE"))
    monkeypatch.setattr(e2b_mod, "restore_repos", lambda *a, **k: asyncio.sleep(0))
    return c


def make(cloud, **opts):
    sb = E2BSandbox({"data_dir": "/nonexistent", "sandbox": {"kind": "e2b", "template": "simp-sandbox", **opts}})
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
    assert cloud.runs("rm -f /work/.simp/home.tar.zst")  # old home snapshot deleted at create
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
    cloud.codes["mountpoint -q /work && ls /work >/dev/null"] = 1  # the mount died while paused
    n_mounts = len(cloud.runs("exec s3fs"))
    await go(env, "echo hi")
    assert cloud.kinds("connect") and len(cloud.kinds("create")) == 1  # resumed, not recreated
    assert len(cloud.runs("exec s3fs")) == n_mounts + 1  # remounted (fresh creds)
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
    assert any("umount /work" in r for r in cloud.runs())  # sync, unmount before kill
    await go(env)
    assert len(cloud.kinds("create")) == 2


async def test_orphan_cleanup_on_start(cloud):
    a = await cloud.create(metadata={"app": "simp", "user_id": "u1", "egress": "allowlist", "template": "simp-sandbox"}, lifecycle={"on_timeout": "pause"})
    b = await cloud.create(metadata={"app": "simp", "user_id": "u1", "egress": "allowlist", "template": "simp-sandbox"}, lifecycle={"on_timeout": "pause"})
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
    assert (await go(env, "echo again"))[0] == 0  # not started: resumed and run, no error for the user
    assert cloud.kinds("connect") and len(cloud.runs("echo again")) == 1


async def test_paused_after_start_behind_proxy_is_not_rerun(cloud):
    """A buffering proxy can hide the start event: the command began, then the sandbox paused. Its start marker is in
    the resumed sandbox, so it is not run a second time."""
    sb = make(cloud)
    env = await sb.open("s1", "u1")
    await go(env)
    cloud.began.add("side effect")
    with pytest.raises(e2b_mod.SandboxLost):
        await go(env, "side effect")
    assert len(cloud.runs("side effect")) == 1 and cloud.kinds("connect")
    assert (await go(env, "echo next"))[0] == 0  # the sandbox is usable again


async def test_paused_before_touch_is_not_rerun(cloud):
    """Frozen by the pause after envd started the wrapper but before `touch`: no marker yet, but its process is
    still there, so it is not run a second time."""
    sb = make(cloud)
    env = await sb.open("s1", "u1")
    await go(env)
    real = env.box.sbx.commands.run

    async def run(cmd, **kw):
        if "frozen cmd" in cmd and cmd.startswith("setsid"):
            cloud.frozen.add(cmd.split("touch ", 1)[1].split(" ", 1)[0])
            env.box.sbx.state = "paused"
        return await real(cmd, **kw)
    env.box.sbx.commands.run = run
    with pytest.raises(e2b_mod.SandboxLost):
        await go(env, "frozen cmd")
    assert not cloud.runs("frozen cmd")


async def test_not_started_then_new_sandbox_is_not_rerun(cloud):
    """Paused before start but the resume fails (a new sandbox): the old one cannot be checked, so no re-run."""
    sb = make(cloud)
    env = await sb.open("s1", "u1")
    await go(env)
    await cloud.pause(env.box.sbx_id)
    cloud.boxes.pop(env.box.sbx_id)  # gone for good: resume fails, a fresh sandbox is created
    with pytest.raises(e2b_mod.SandboxLost):
        await go(env, "maybe ran")
    assert not cloud.runs("maybe ran")


async def test_timeout_before_pid_file_waits_for_it(cloud):
    """The kill waits for the pid file, so a timeout before the wrapper wrote it still kills the command."""
    sb = make(cloud)
    env = await sb.open("s1", "u1")
    cloud.gates["slow"] = asyncio.Event()
    assert (await env.exec("slow", ".", 0.05, asyncio.Event()))[0] is None
    kill = cloud.runs("kill -9")[-1]
    assert kill.index("[ -s") < kill.index("kill -9")


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


async def until(cond, n=300):
    for _ in range(n):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timeout")


async def test_pause_waits_and_aborts_for_a_call_that_started(cloud):
    """Review C3: the tick's pause re-checks active under the lock and aborts if a call started meanwhile."""
    sb = make(cloud, idle_pause_s=1)
    env = await sb.open("s1", "u1")
    await go(env)
    await env.box.lock.acquire()
    tick = asyncio.create_task(sb.stop_idle(now=env.box.last + 100))
    await asyncio.sleep(0.01)
    gate = cloud.gates["sleep 5"] = asyncio.Event()
    call = asyncio.create_task(go(env, "sleep 5"))
    await until(lambda: cloud.runs("sleep 5"))
    env.box.lock.release()
    await tick
    assert env.box.state == "running" and not cloud.kinds("pause")
    gate.set()
    assert (await call)[0] == 0


async def test_call_during_a_pause_waits_then_resumes(cloud):
    """Review C3: while the pause runs (state "stopping"), a new call waits for it, then resumes the sandbox;
    it never runs in the sandbox being paused."""
    sb = make(cloud, idle_pause_s=1)
    env = await sb.open("s1", "u1")
    await go(env)
    gate, real = asyncio.Event(), env.box.sbx.pause

    async def slow_pause(*a, **k):
        await gate.wait()
        return await real(*a, **k)
    env.box.sbx.pause = slow_pause
    tick = asyncio.create_task(sb.stop_idle(now=env.box.last + 100))
    await until(lambda: env.box.state == "stopping")
    call = asyncio.create_task(go(env, "echo after"))
    await asyncio.sleep(0.05)
    assert not cloud.runs("echo after")  # waits for the pause
    gate.set()
    await tick
    assert (await call)[0] == 0
    names = [e[0] for e in cloud.log]
    assert names.index("pause") < names.index("connect") < max(i for i, e in enumerate(cloud.log) if e[0] == "run"
                                                                 and e[3] == "echo after")


async def test_tick_refreshes_provider_timeout_during_a_long_call_and_lost_exec_is_not_rerun(cloud):
    """Review M1: the tick keeps the provider-side pause timer ahead while a call runs; a command whose sandbox was
    paused under it raises and is not run a second time."""
    sb = make(cloud, idle_pause_s=600)
    env = await sb.open("s1", "u1")
    gate = cloud.gates["long"] = asyncio.Event()
    call = asyncio.create_task(go(env, "long"))
    await until(lambda: cloud.runs("long"))
    n = len(cloud.kinds("set_timeout"))
    await sb.stop_idle(now=env.box.timeout_at + 61)
    assert len(cloud.kinds("set_timeout")) == n + 1
    gate.set()
    await call
    cloud.lose.add("side effect")
    with pytest.raises(e2b_mod.SandboxLost):
        await go(env, "side effect")
    assert len(cloud.runs("side effect")) == 1


async def test_mount_credential_refreshed_before_it_expires(cloud):
    """Review M2: a call that would outlive the mount credential remounts first; the tick refreshes at an idle
    point; with another call on the mount, a new call is refused instead."""
    sb = make(cloud, idle_pause_s=10_000)
    sb.store.expires_in = 3600
    env = await sb.open("s1", "u1")
    await go(env)
    mounts = lambda: len(cloud.runs("exec s3fs"))  # noqa: E731
    n = mounts()
    await env.exec("short", ".", 60, asyncio.Event())
    assert mounts() == n  # plenty left
    env.box.creds_until = time.monotonic() + 1000
    await env.exec("long build", ".", 2000, asyncio.Event())  # would run past expiry: remount first
    assert mounts() == n + 1
    i = [k for k, e in enumerate(cloud.log) if e[0] == "run" and "s3fs" in e[3]][-1]
    assert i < [k for k, e in enumerate(cloud.log) if e[0] == "run" and e[3] == "long build"][0]
    env.box.creds_until = time.monotonic() + 400
    await sb.stop_idle(now=env.box.last + 1)  # idle, near expiry
    assert mounts() == n + 2
    gate = cloud.gates["zz-other"] = asyncio.Event()
    env.box.creds_until = time.monotonic() + 10_000
    other = asyncio.create_task(go(env, "zz-other"))
    await until(lambda: cloud.runs("zz-other"))
    env.box.creds_until = time.monotonic() + 10
    with pytest.raises(SandboxLimit, match="credential"):
        await go(env, "blocked")
    gate.set()
    await other


async def test_concurrent_creates_respect_max_running_and_budget_tick(cloud):
    """Review M8: the running slot is reserved under a global lock before create; the tick pauses a box that
    went over the daily budget once its call ended, and new calls are refused."""
    cloud.create_delay = 0.02
    sb = make(cloud, max_running=1, day_minutes=1)
    envs = [await sb.open(f"s{i}", f"u{i}") for i in range(3)]
    res = await asyncio.gather(*(go(e) for e in envs), return_exceptions=True)
    assert sum(isinstance(r, SandboxLimit) for r in res) == 2 and len(cloud.kinds("create")) == 1
    env = next(e for e, r in zip(envs, res) if not isinstance(r, Exception))
    sb.compute.db.seconds = 61
    env.box.active = 1
    await sb.stop_idle(now=env.box.last + 1)
    assert env.box.state == "running" and env.box.over
    env.box.active = 0
    await sb.stop_idle(now=env.box.last + 1)
    assert env.box.state == "paused"
    with pytest.raises(SandboxLimit, match="budget"):
        await go(env)


async def test_failed_mirror_is_retried_before_max_life_kill(cloud, monkeypatch):
    """Review C2/M7: never kill silently after a failed mirror: retry it first."""
    n = [0]

    async def mirror(*a, **k):
        n[0] += 1
        return "SIMP_DONE"
    monkeypatch.setattr(repos_mod, "mirror_repos", mirror)
    sb = make(cloud, max_life_s=100, idle_pause_s=10_000)
    env = await sb.open("s1", "u1")
    await go(env)
    env.box.mirror_failed = True
    await sb.stop_idle(now=env.box.started + 200)
    assert env.box.state == "none" and n[0] == 1 and not env.box.mirror_failed


async def test_template_with_sudo_is_refused(cloud):
    from simp_server.sandboxes.e2b import SUDO_CHECK
    cloud.out[SUDO_CHECK] = "SIMP_SUDO_OK\n"
    sb = make(cloud)
    env = await sb.open("s1", "u1")
    with pytest.raises(RuntimeError, match="sudo"):
        await go(env)
    assert cloud.kinds("kill")


LIVE = os.environ.get("E2B_API_KEY") and all(os.environ.get(f"SIMP_TEST_S3_{k}") for k in ("ENDPOINT", "BUCKET", "KEY", "SECRET"))


@pytest.mark.skipif(not LIVE, reason="needs E2B_API_KEY and a SIMP_TEST_S3_* bucket")
async def test_live_e2b(tmp_path):
    from simp_server.workspace import S3Store
    settings = {"data_dir": str(tmp_path), "sandbox": {"kind": "e2b", "tag": "simp-test"},
                "workspace": {"store": "s3", "endpoint": os.environ["SIMP_TEST_S3_ENDPOINT"],
                              "bucket": os.environ["SIMP_TEST_S3_BUCKET"], "mount_scope": os.environ.get("SIMP_TEST_S3_SCOPE", "none"),
                              "dev_unscoped_mount": True,
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


async def test_running_box_paused_when_points_run_out(cloud):
    """Billing on: once the balance is <= 0 the tick marks the box over, pauses it when idle, and calls are refused."""
    sb = make(cloud)
    balance = [5]

    async def credits(user_id, rate):
        return {"balance": balance[0]}
    sb.compute.db.credits, sb.compute.billing = credits, (True, 1000.0)
    env = await sb.open("s1", "u1")
    await go(env)
    balance[0] = 0
    await sb.stop_idle(now=env.box.last + 1)  # marks it over
    await sb.stop_idle(now=env.box.last + 1)  # next tick: paused
    assert env.box.over and env.box.state == "paused"
    with pytest.raises(SandboxLimit, match="out of points"):
        await go(env)
    balance[0] = 10
    await go(env)  # credit added: works again


async def _paused_store(cloud, tmp_path, **opts):
    from simp_server.store import SqliteStore
    sb = make(cloud, **opts)
    db = SqliteStore({"data_dir": str(tmp_path)})
    await db.open()
    sb.compute.db = db
    env = await sb.open("s1", "u1")
    await go(env)
    await sb.stop_idle(now=env.box.last + 10_000)  # idle pause
    assert env.box.state == "paused"
    return sb, db, env


async def paused_rows(db):
    return [r for r in await db.usage("u1") if r["model"].startswith("sandbox-paused")]


async def test_paused_time_charged_once_on_resume(cloud, tmp_path):
    sb, db, env = await _paused_store(cloud, tmp_path)
    await db._do("UPDATE sandbox_pauses SET paused_at=paused_at-100")  # paused 100 s
    await sb.stop_idle(now=env.box.last + 20_000)  # still paused: no charge yet
    assert await paused_rows(db) == []
    await go(env)  # resume
    [r] = await paused_rows(db)
    assert r["input"] == 100
    assert r["cost"] == pytest.approx(0.1 * 100 * (2 * 0.000014 + 2 * 0.0000045), rel=0.01)
    await go(env)
    assert len(await paused_rows(db)) == 1  # no double charge
    await db.close()


async def test_paused_ratio_zero_records_nothing(cloud, tmp_path):
    sb, db, env = await _paused_store(cloud, tmp_path, paused_price_ratio=0)
    assert await db.pause_ids() == []
    await go(env)
    assert await paused_rows(db) == []
    await db.close()


async def test_paused_box_survives_restart_and_expiry_charged_once(cloud, tmp_path):
    sb, db, env = await _paused_store(cloud, tmp_path)
    await db._do("UPDATE sandbox_pauses SET paused_at=paused_at-50")
    sb2 = make(cloud)  # server restart: same db, adopts the paused box, keeps the first pause time
    sb2.compute.db = db
    await sb2.start()
    assert await paused_rows(db) == []
    cloud.boxes.pop(env.box.sbx_id)  # expired at the provider
    sb3 = make(cloud)
    sb3.compute.db = db
    await sb3.start()
    [r] = await paused_rows(db)
    assert r["input"] == 50
    await sb3.start()
    assert len(await paused_rows(db)) == 1
    await db.close()


async def test_egress_allowlist_only_storage(cloud):
    sb = make(cloud, egress_allow=["example.org"])
    await go(await sb.open("s1", "u1"))
    assert cloud.network == {"allow_out": ["example.org", "acct.r2.cloudflarestorage.com"], "deny_out": ["0.0.0.0/0"]}


async def test_egress_open_setting(cloud):
    sb = make(cloud, egress="open")
    await go(await sb.open("s1", "u1"))
    assert cloud.network is None


def test_prompt_hint_says_no_internet(cloud):
    assert "no internet" in make(cloud).prompt_hint and "web_fetch" in make(cloud).prompt_hint
    assert "no internet" not in make(cloud, egress="open").prompt_hint


def test_prompt_hint_lists_tools(cloud):
    from simp_server.sandboxes import toolset
    h = make(cloud).prompt_hint
    assert toolset.prompt_list(True) in h and "Libraries are fixed: do not install packages" in h and "/opt" not in h
    assert "LibreOffice" not in make(cloud, office=False).prompt_hint  # on by default: the skills need it


async def test_old_home_snapshot_deleted_never_unpacked(cloud):
    """Libraries are fixed in the template: old home snapshots are deleted at create (quota), never unpacked; repos
    still come back only from their mirror."""
    sb = make(cloud, idle_pause_s=1)
    env = await sb.open("s1", "u1")
    await go(env)
    assert any(r.startswith("rm -f /work/.simp/home.tar.zst") for r in cloud.runs())
    await sb.stop_idle(now=env.box.last + 10)
    assert not [r for r in cloud.runs() if "zstd" in r or "tar -" in r]

async def test_sandbox_from_before_the_egress_filter_is_not_adopted(cloud):
    """A sandbox created without the allowlist (older server) would keep open internet if resumed: kill it."""
    old = await cloud.create(metadata={"app": "simp", "user_id": "u1"}, lifecycle={"on_timeout": "pause"})
    old.state = "paused"
    sb = make(cloud)
    await sb.start()
    assert old.sandbox_id not in cloud.boxes and not sb.boxes["u1"].sbx_id
    await go(await sb.open("s1", "u1"))
    assert cloud.network and cloud.boxes[sb.boxes["u1"].sbx_id].metadata["egress"] == "allowlist"


def test_allowlist_without_store_endpoint_fails_fast(cloud):
    sb = make(cloud)
    sb.store.mount_endpoint = ""
    with pytest.raises(RuntimeError, match="workspace endpoint"):
        sb._network()


async def test_sandbox_from_another_template_is_not_adopted(cloud):
    """After switching [sandbox] template, old sandboxes would keep the old toolset if resumed: kill them."""
    old = await cloud.create(metadata={"app": "simp", "user_id": "u1", "egress": "allowlist", "template": "simp-sandbox"},
                             lifecycle={"on_timeout": "pause"})
    old.state = "paused"
    sb = make(cloud, template="simp-sandbox-next")
    await sb.start()
    assert old.sandbox_id not in cloud.boxes and not sb.boxes["u1"].sbx_id
    await go(await sb.open("s1", "u1"))
    assert cloud.boxes[sb.boxes["u1"].sbx_id].metadata["template"] == "simp-sandbox-next"


def test_mount_caches_reads_on_sandbox_disk():
    """Measured on E2B + R2: a local read cache cuts repeated reads ~3-4x; stat cache stays 5 s so web uploads show up."""
    from simp_server.sandboxes.docker import S3FS
    from simp_server.sandboxes.e2b import S3FS_CACHE
    assert "use_cache=/tmp/s3fs" in S3FS_CACHE and "ensure_diskfree=256" in S3FS_CACHE and "del_cache" in S3FS_CACHE
    assert "stat_cache_expire=5" in S3FS


def test_template_auto_is_the_content_hash():
    from simp_server.sandboxes import toolset
    sb = E2BSandbox({"data_dir": "/nonexistent", "sandbox": {"kind": "e2b"}})
    assert sb.template == toolset.template_alias(True) and sb.template.startswith("simp-sandbox-")
    assert toolset.template_alias(False) != sb.template
