"""Workspace storage quota: db-tracked usage, warn/full states, Files panel upload/delete, E2B read-only remount."""

import asyncio
import sys
from pathlib import Path

import httpx

from simp_server.quota import MB, Quota
from simp_server.store import SqliteStore
from simp_server.workspace import LocalStore

sys.path.insert(0, str(Path(__file__).parent))  # sibling test modules: their fakes and fixtures
from test_e2b_sandbox import FakeStore, cloud, go, make  # noqa: F401  (cloud: fixture)
from test_server import FakeProvider, env  # noqa: F401  (env: fixture)


async def _quota(tmp_path, quota_mb=1.0, **w):
    settings = {"data_dir": str(tmp_path), "workspace": {"quota_mb": quota_mb, **w}}
    db = SqliteStore(settings)
    await db.open()
    return Quota(settings, LocalStore(settings), db), db


async def test_usage_states_and_per_user_override(tmp_path):
    q, db = await _quota(tmp_path)
    try:
        await q.files.write("u1", "a.bin", b"x" * (MB // 2))
        assert await q.usage("u1") == {"used": MB // 2, "quota": MB, "state": "ok"}  # first call counts the store
        await q.files.write("u1", "b.bin", b"x" * (MB // 3))
        assert (await q.usage("u1"))["used"] == MB // 2  # sandbox-style write: the db only knows after a recount
        await q.recount("u1")
        assert (await q.usage("u1"))["state"] == "warn"  # 83% >= 80%
        assert not await q.fits("u1", MB // 5) and await q.fits("u1", MB // 20)  # 95% is the block line
        await q.added("u1", MB // 5)
        assert await q.full("u1")
        await db.ws_set_quota("u1", 10)  # admin override: 10 MB for this user only
        assert (await q.usage("u1"))["state"] == "ok" and (await q.usage("u2"))["quota"] == MB
        await db.ws_set_quota("u1", 0)  # 0 = no quota
        assert (await q.usage("u1"))["state"] == "off" and await q.fits("u1", 10 * MB)
    finally:
        await db.close()


async def test_touch_recounts_in_background_throttled(tmp_path):
    q, db = await _quota(tmp_path, quota_recount_s=60)
    try:
        await q.usage("u1")
        await q.files.write("u1", "a.bin", b"x" * 100)
        q.last.clear()
        q.touch("u1")
        await q.tasks["u1"]
        assert (await q.usage("u1"))["used"] == 100
        await q.files.write("u1", "b.bin", b"x" * 100)
        q.touch("u1")  # within 60 s: no recount
        await asyncio.sleep(0)
        assert (await q.usage("u1"))["used"] == 100
    finally:
        await db.close()


async def test_local_store_delete_folder_and_size(tmp_path):
    s = LocalStore({"data_dir": str(tmp_path)})
    await s.write("u1", "d/e/f.txt", b"abc")
    await s.write("u1", "g.txt", b"ab")
    assert await s.size("u1") == 5
    await s.delete("u1", "d")
    assert await s.size("u1") == 2 and [e["name"] for e in await s.list("u1", ".")] == ["g.txt"]


async def test_files_api_upload_refused_when_full_delete_frees(env):  # noqa: F811
    app, mgr, user, token, run = await env(FakeProvider())
    mgr.settings.setdefault("workspace", dict())["quota_mb"] = 1
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as api:
        url = f"/api/sessions/{run.sid}/files"
        assert (await api.put(f"{url}/raw?path=d/big.bin", content=b"x" * (MB * 9 // 10), headers=h)).status_code == 200
        w = (await api.get("/api/workspace", headers=h)).json()
        assert w["used"] == MB * 9 // 10 and w["state"] == "warn"
        r = await api.put(f"{url}/raw?path=more.bin", content=b"x" * (MB // 10), headers=h)
        assert r.status_code == 507
        r = await api.delete(f"{url}?path=d", headers=h)  # a whole folder
        assert r.status_code == 200 and r.json()["used"] == 0 and r.json()["state"] == "ok"
        assert (await api.put(f"{url}/raw?path=more.bin", content=b"x" * (MB // 10), headers=h)).status_code == 200
        assert (await api.delete(f"{url}?path=.", headers=h)).status_code == 403  # never the root


class FakeQuota:
    def __init__(self):
        self.u, self.touched, self.last = {"used": 0, "quota": 100, "state": "ok"}, 0, {}

    async def usage(self, user_id):
        return self.u

    async def full(self, user_id):
        return self.u["state"] == "full"

    def touch(self, user_id):
        self.touched += 1

    def note(self, u):
        return f"[{u['state']}]"


class RoStore(FakeStore):
    def __init__(self):
        self.ro = list()

    async def mount_creds(self, user_id, read_only=False):
        self.ro.append(read_only)
        return await super().mount_creds(user_id)


async def test_e2b_full_workspace_goes_read_only_and_back(cloud):  # noqa: F811
    sb = make(cloud)
    sb.quota, sb.store = FakeQuota(), RoStore()
    env = await sb.open("s1", "u1")
    await go(env)
    assert sb.store.ro == [False] and not env.box.ro
    sb.quota.u = {"used": 96, "quota": 100, "state": "full"}  # a background recount found it full
    code, out = await go(env, "echo hi")
    assert env.box.ro and sb.store.ro == [False, True]  # read-only credential, too
    assert any("pkill -x s3fs" in r for r in cloud.runs())  # the old (writable) s3fs is killed, not just unmounted
    assert cloud.runs("exec s3fs")[-1].endswith('"$O"') and "[full]" in out  # ro passed to s3fs as $4
    try:
        await env.write_file("x.txt", "no")
        raise AssertionError("write to a read-only /work must fail")
    except PermissionError as e:
        assert "[full]" in str(e)
    await env.write_file("/tmp/x.txt", "ok")  # outside /work: fine
    await env.after_tool()
    assert sb.quota.touched == 1 and env.box.mirror_failed  # no mirror on a read-only mount: retried before a kill
    sb.quota.u = {"used": 10, "quota": 100, "state": "ok"}  # user deleted files
    code, out = await go(env)
    assert not env.box.ro and sb.store.ro[-1] is False and "[" not in out


async def test_e2b_warn_note_once(cloud):  # noqa: F811
    sb = make(cloud)
    sb.quota = FakeQuota()
    env = await sb.open("s1", "u1")
    sb.quota.u = {"used": 85, "quota": 100, "state": "warn"}
    assert "[warn]" in (await go(env))[1]
    assert "[warn]" not in (await go(env))[1]
    assert not env.box.ro


async def test_e2b_kill_of_full_box_remounts_writable_for_last_snapshot(cloud, monkeypatch):  # noqa: F811
    monkeypatch.setattr("simp_server.sandboxes.e2b.HOME_DIRS", ".data")  # a home dir to pack (none by default)
    sb = make(cloud)
    sb.quota, sb.store = FakeQuota(), RoStore()
    sb.quota.u = {"used": 99, "quota": 100, "state": "full"}
    env = await sb.open("s1", "u1")
    await go(env)
    assert env.box.ro
    async with env.box.mirror_lock, env.box.lock:
        await sb._kill(env.box)
    runs = cloud.runs()
    kill_users = runs.index("pkill -KILL -u user; true")
    assert sb.store.ro[-1] is False and kill_users < max(i for i, r in enumerate(runs) if "home.tar" in r)
