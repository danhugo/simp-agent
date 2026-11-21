"""Live smoke test of E2BSandbox against REAL E2B, without an S3 bucket: the /work mount is stubbed (a plain dir on the
sandbox disk) by a test-only subclass; everything else is the production code path. Needs E2B_API_KEY and the
template built by apps/server/sandboxes/e2b_template.py. Costs a few sandbox-minutes; kills what it creates."""

import asyncio
import os
import time
import uuid

import pytest

from simp_server.sandboxes.e2b import SUDO_CHECK, E2BSandbox, _run

KEY = os.environ.get("E2B_API_KEY")  # captured now: create_app pops it from os.environ in other tests
pytestmark = pytest.mark.skipif(not KEY, reason="needs E2B_API_KEY (real E2B)")


class NoMountE2BSandbox(E2BSandbox):
    """TEST ONLY: /work is a local dir instead of the s3fs bucket mount."""

    async def _mount(self, box):
        code, out = await _run(box.sbx, "mkdir -p /work/.simp && chown -R user:user /work", "/", 30, asyncio.Event(),
                               user="root")
        assert code == 0, out

    async def _mounted(self, box):
        return True


def ev():
    return asyncio.Event()


async def test_live_e2b_no_bucket(tmp_path):
    tag = f"simp-live-{uuid.uuid4().hex[:8]}"
    settings = {"data_dir": str(tmp_path), "sandbox": {"kind": "e2b", "tag": tag, "provider_timeout_s": 300}}
    sb = NoMountE2BSandbox(settings)
    sb.keys = {"E2B_API_KEY": KEY}
    t = dict()
    try:
        env = await sb.open("s1", "u1")
        t0 = time.monotonic()
        assert await env.exec("echo hi", ".", 60, ev()) == (0, "hi\n")  # lazy create (+ sudo check, restore)
        t["create_s"] = time.monotonic() - t0
        box = env.box
        sid = box.sbx_id
        info = await sb._sdk.get_info(sid, api_key=KEY)
        assert info.metadata == {"app": tag, "user_id": "u1"}
        assert info.lifecycle and info.lifecycle["on_timeout"] == "pause", info.lifecycle

        # command output, exit codes, stderr merged, file ops in /home/user and /work
        assert await env.exec("echo err >&2; exit 3", ".", 60, ev()) == (3, "err\n")
        assert (await env.exec("whoami", ".", 60, ev()))[1].strip() == "user"
        await env.write_file("/home/user/note.txt", "kept")
        assert await env.read_file("/home/user/note.txt") == "kept"
        await env.write_file("a.txt", "A")
        assert [e["name"] for e in await env.list(".") if e["name"] == "a.txt"] == ["a.txt"]
        with pytest.raises(FileNotFoundError):
            await env.read_file("/home/user/missing.txt")
        assert "SIMP_SUDO_OK" not in (await box.exec(SUDO_CHECK, "/", 20, ev()))[1]
        code, out = await env.exec("pip install --user -q six && python -c 'import six; print(six.__file__)'",
                                   ".", 180, ev())
        assert code == 0 and "/home/user/.local" in out, out
        await sb._refresh_timeout(box, time.monotonic() + 120)  # set_timeout accepted by the API

        # timeout: killed process group, (None, partial output)
        assert await env.exec("echo start; sleep 30", ".", 2, ev()) == (None, "start\n")

        # idle pause (snapshot to /work/.simp, then provider pause)
        await sb.stop_idle(now=box.last + 10_000)
        assert box.state == "paused"
        assert [i["state"] for i in await sb.list_all()] == ["paused"]

        # a second server instance adopts the paused sandbox by metadata and resumes it
        sb2 = NoMountE2BSandbox(settings)
        sb2.keys = sb.keys
        await sb2.start()
        assert sb2.boxes["u1"].sbx_id == sid and sb2.boxes["u1"].state == "paused"
        env2 = await sb2.open("s2", "u1")
        t0 = time.monotonic()
        assert await env2.exec("cat /home/user/note.txt", ".", 60, ev()) == (0, "kept")
        t["resume_s"] = time.monotonic() - t0
        assert (await env2.exec("python -c 'import six'", ".", 60, ev()))[0] == 0
        assert env2.box.sbx_id == sid

        # max life: snapshot, unmount, kill; nothing left at the provider
        sb2.idle_pause_s, sb2.max_life_s = 10**9, 0
        await sb2.stop_idle()
        assert env2.box.state == "none" and env2.box.sbx_id is None
        assert await sb2.list_all() == []
        print(f"\nE2B live latencies: create {t['create_s']:.2f}s, resume {t['resume_s']:.2f}s")
    finally:
        for i in await sb.list_all():
            await sb._sdk.kill(i["id"], api_key=KEY)


@pytest.mark.skipif(not os.environ.get("SIMP_LIVE_PAUSE"), reason="slow (~2 min): set SIMP_LIVE_PAUSE=1")
async def test_live_provider_timeout_pauses(tmp_path):
    """The safety net: a sandbox we stop touching is PAUSED by E2B at its timeout, not killed."""
    tag = f"simp-live-{uuid.uuid4().hex[:8]}"
    sb = NoMountE2BSandbox({"data_dir": str(tmp_path), "sandbox": {"kind": "e2b", "tag": tag, "provider_timeout_s": 30}})
    sb.keys = {"E2B_API_KEY": KEY}
    try:
        env = await sb.open("s1", "u1")
        assert (await env.exec("echo hi", ".", 30, ev()))[0] == 0
        states = list()
        for _ in range(24):  # up to 2 min after the 30 s timer
            await asyncio.sleep(5)
            states = [i["state"] for i in await sb.list_all()]
            if states != ["running"]:
                break
        assert states == ["paused"], states
    finally:
        for i in await sb.list_all():
            await sb._sdk.kill(i["id"], **sb._api())


async def test_live_paused_behind_our_back_resumes(tmp_path):
    """Pause the sandbox through the E2B API (as `sandboxes --pause-all` from another process would): the server still
    thinks it runs, and the next command resumes it and runs, with no error and without running anything twice."""
    tag = f"simp-live-{uuid.uuid4().hex[:8]}"
    sb = NoMountE2BSandbox({"data_dir": str(tmp_path), "sandbox": {"kind": "e2b", "tag": tag, "provider_timeout_s": 300}})
    sb.keys = {"E2B_API_KEY": KEY}
    try:
        env = await sb.open("s1", "u1")
        assert await env.exec("echo 1 >> /home/user/count", ".", 60, ev()) == (0, "")
        await sb._sdk.pause(env.box.sbx_id, api_key=KEY)
        assert env.box.state == "running"  # the server does not know
        assert await env.exec("echo 1 >> /home/user/count; wc -l < /home/user/count", ".", 60, ev()) == (0, "2\n")
    finally:
        await sb.close_all()
        for i in await sb.list_all():
            await sb._sdk.kill(i["id"], api_key=KEY)


async def test_live_egress_allowlist(tmp_path):
    """Default egress: package indexes and random hosts unreachable; an allowlisted host reachable."""
    settings = {"data_dir": str(tmp_path), "sandbox": {"kind": "e2b", "tag": f"simp-live-{uuid.uuid4().hex[:8]}",
                                                        "provider_timeout_s": 300, "egress_allow": ["example.com"]}}
    sb = NoMountE2BSandbox(settings)
    sb.keys = {"E2B_API_KEY": KEY}
    try:
        env = await sb.open("s1", "u1")
        probe = "curl -s -o /dev/null -m 8 -w '%{http_code}' "
        assert (await env.exec(probe + "https://example.com", ".", 60, ev()))[1].strip() == "200"
        for url in ("https://pypi.org/simple/", "https://registry.npmjs.org/", "https://httpbin.org/post"):
            assert (await env.exec(probe + url, ".", 60, ev()))[1].strip() in ("000", ""), url
    finally:
        for i in await sb.list_all():
            await sb._sdk.kill(i["id"], api_key=KEY)


async def test_live_template_toolset(tmp_path):
    """The template's libraries import; user cannot change /opt/simp or install packages (no index route)."""
    settings = {"data_dir": str(tmp_path), "sandbox": {"kind": "e2b", "tag": f"simp-live-{uuid.uuid4().hex[:8]}",
                                                        "provider_timeout_s": 300,
                                                        "template": os.environ.get("SIMP_E2B_TEMPLATE", "simp-sandbox")}}
    sb = NoMountE2BSandbox(settings)
    sb.keys = {"E2B_API_KEY": KEY}
    try:
        env = await sb.open("s1", "u1")
        assert (await env.exec("python -c 'import pandas, docx, pptx, openpyxl, pdfplumber, matplotlib'", ".", 120, ev()))[0] == 0
        assert (await env.exec("touch /opt/simp/x", ".", 30, ev()))[0] != 0
        assert "vie" in (await env.exec("tesseract --list-langs", ".", 30, ev()))[1]
        assert (await env.exec("pip install --target /work/x six", ".", 60, ev()))[0] != 0
        assert (await env.exec("pip install six", ".", 60, ev()))[0] != 0
    finally:
        for i in await sb.list_all():
            await sb._sdk.kill(i["id"], api_key=KEY)
