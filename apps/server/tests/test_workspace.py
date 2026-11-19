"""Workspace store slot: path rules, config validation, LocalStore, and S3Store on the dev MinIO (scoped mount
credentials, versioned restore)."""

import time
import uuid
from datetime import datetime, timezone

import boto3
import pytest

from simp_server import workspace
from simp_server.server import create_app, load_settings


def test_rel():
    assert workspace.rel(".") == workspace.rel("/work") == workspace.rel("/work/") == ""
    assert workspace.rel("/work/a/../b/./c") == "b/c" and workspace.rel("a//b/") == "a/b"
    for bad in ("..", "../x", "a/../../x", "/etc/passwd", "/work/../x"):
        with pytest.raises(PermissionError):
            workspace.rel(bad)


def test_check_config(tmp_path):
    ok = lambda **s: workspace.check_config(s)  # noqa: E731
    e2b = {"plugins": {"sandbox": "simp_server.sandboxes.e2b:E2BSandbox"}}
    docker = {"plugins": {"sandbox": "simp_server.sandboxes.docker:DockerSandbox"}}
    assert ok() is None and ok(**docker) is None
    assert "cannot mount a folder" in ok(**e2b)
    assert ok(**e2b, workspace={"store": "s3"}) is None
    assert "needs [workspace] store" in ok(**docker, sandbox={"mount": "fuse"})
    assert "needs [sandbox] mount" in ok(**docker, workspace={"store": "s3"})
    assert "tests only" in ok(**docker, workspace={"store": "s3"}, sandbox={"mount": "fuse"})  # review M4
    assert "host.docker.internal" in ok(**docker, workspace={"store": "s3"}, sandbox={"mount": "fuse"})
    assert ok(**docker, workspace={"store": "s3"}, sandbox={"mount": "fuse", "dev_fuse": True}) is None
    assert "dev_unscoped_mount" in ok(**e2b, workspace={"store": "s3", "mount_scope": "none"})
    assert ok(**e2b, workspace={"store": "s3", "mount_scope": "none", "dev_unscoped_mount": True}) is None
    (tmp_path / "settings.toml").write_text('[sandbox]\nkind = "e2b"\n[profiles.test]\napi = "fake"\nmodel = "m"\n')
    settings = load_settings(tmp_path)
    assert settings["plugins"]["sandbox"].endswith(":E2BSandbox")
    with pytest.raises(SystemExit, match="cannot mount a folder"):
        create_app(settings)


async def test_local_store(tmp_path):
    st = workspace.LocalStore({"data_dir": str(tmp_path)})
    await st.write("u1", "/work/d/a.txt", b"hi")
    assert (tmp_path / "workspaces" / "u1" / "d" / "a.txt").read_bytes() == b"hi"
    assert await st.list("u1", "d") == [{"name": "a.txt", "is_dir": False, "size": 2}]
    assert await st.read("u1", "d/a.txt") == b"hi" and await st.mount_creds("u1") is None
    with pytest.raises(PermissionError):
        await st.read("u1", "../u2/x")
    with pytest.raises(FileNotFoundError):
        await st.read("u1", "nope")


async def test_s3_store_files_scoped_creds_and_restore(tmp_path, minio, s3_settings):
    settings, keys = s3_settings(tmp_path, prefix=f"t-{uuid.uuid4().hex[:6]}/{{user_id}}/")
    st = workspace.S3Store(settings, keys)
    await st.write("u1", "a.txt", b"v1")
    await st.write("u1", "/work/d/b.bin", b"\x00\x01")
    assert await st.list("u1", ".") == [{"name": "a.txt", "is_dir": False, "size": 2},
                                        {"name": "d", "is_dir": True, "size": 0}]
    assert await st.list("u1", "/work/d") == [{"name": "b.bin", "is_dir": False, "size": 2}]
    assert await st.read("u1", "d/b.bin") == b"\x00\x01"
    with pytest.raises(FileNotFoundError):
        await st.read("u1", "nope")
    with pytest.raises(FileNotFoundError):
        await st.list("u1", "nodir")
    with pytest.raises(PermissionError):
        await st.read("u1", "../u2/a.txt")

    # the mount credential reaches only the user's prefix
    c = await st.mount_creds("u1")
    s3 = boto3.client("s3", endpoint_url=minio["endpoint"], region_name="us-east-1", aws_access_key_id=c["access_key"],
                      aws_secret_access_key=c["secret_key"], aws_session_token=c["session_token"])
    assert s3.get_object(Bucket=c["bucket"], Key=c["prefix"] + "a.txt")["Body"].read() == b"v1"
    s3.put_object(Bucket=c["bucket"], Key=c["prefix"] + "c.txt", Body=b"c")
    with pytest.raises(Exception, match="AccessDenied"):
        s3.put_object(Bucket=c["bucket"], Key=st.prefix("u2") + "x", Body=b"x")
    with pytest.raises(Exception, match="AccessDenied"):
        s3.list_objects_v2(Bucket=c["bucket"], Prefix=st.prefix("u2"))
    assert "host.docker.internal" in c["endpoint"]

    # restore to a time: overwritten files come back, newer files go, deleted files come back
    time.sleep(1.1)
    at = datetime.now(timezone.utc)
    time.sleep(1.1)
    await st.write("u1", "a.txt", b"v2")
    await st.delete("u1", "d/b.bin")
    await st.write("u1", "new.txt", b"n")
    changed = await st.restore("u1", at, "a.txt")
    assert changed == [st.prefix("u1") + "a.txt"] and await st.read("u1", "a.txt") == b"v1"
    assert await st.read("u1", "new.txt") == b"n"  # --path limits the restore
    await st.restore("u1", at)
    assert await st.read("u1", "d/b.bin") == b"\x00\x01" and await st.read("u1", "c.txt") == b"c"
    with pytest.raises(FileNotFoundError):
        await st.read("u1", "new.txt")
    assert await st.restore("u1", at) == []  # nothing left to change


def _r2_settings(tmp_path, **w):
    return {"data_dir": str(tmp_path), "workspace": {
        "store": "s3", "bucket": "simp-ws", "endpoint": "https://acct.r2.cloudflarestorage.com", "region": "auto",
        "mount_scope": "r2", "cf_account_id": "acct", "mount_creds_ttl_s": 900} | w}


async def test_r2_scoped_mount_creds(tmp_path):
    import json as _json

    import httpx

    seen = list()

    def cf(req):
        seen.append(req)
        return httpx.Response(200, json={"success": True, "errors": [], "messages": [], "result": {
            "accessKeyId": "TMPKEY", "secretAccessKey": "TMPSECRET", "sessionToken": "TMPTOKEN"}})

    keys = {"S3_ACCESS_KEY_ID": "PARENTKEY", "S3_SECRET_ACCESS_KEY": "parentsecret", "R2_API_TOKEN": "cftoken"}
    st = workspace.S3Store(_r2_settings(tmp_path), keys)
    st.cf_transport = httpx.MockTransport(cf)
    c = await st.mount_creds("u1")
    req = seen[0]
    assert req.method == "POST" and str(req.url) == \
        "https://api.cloudflare.com/client/v4/accounts/acct/r2/temp-access-credentials"
    assert req.headers["authorization"] == "Bearer cftoken"
    assert _json.loads(req.content) == {"bucket": "simp-ws", "parentAccessKeyId": "PARENTKEY",
                                        "permission": "object-read-write", "ttlSeconds": 900, "prefixes": ["users/u1/"]}
    assert c["access_key"] == "TMPKEY" and c["secret_key"] == "TMPSECRET" and c["session_token"] == "TMPTOKEN"
    assert c["prefix"] == "users/u1/" and c["bucket"] == "simp-ws" and 0 < c["expires_in"] <= 900
    assert workspace.check_config({"plugins": {"sandbox": "simp_server.sandboxes.e2b:E2BSandbox"},
                                   "workspace": {"store": "s3", "mount_scope": "r2"}}) is None
    with pytest.raises(SystemExit, match="R2 does not have"):
        await st.restore("u1", datetime.now(timezone.utc))

    st.cf_transport = httpx.MockTransport(lambda req: httpx.Response(403, json={
        "success": False, "errors": [{"code": 10000, "message": "Authentication error"}], "messages": [], "result": None}))
    with pytest.raises(RuntimeError, match="Authentication error"):
        await st.mount_creds("u1")


def test_r2_missing_token_or_account(tmp_path, monkeypatch):
    monkeypatch.delenv("R2_API_TOKEN", raising=False)
    keys = {"S3_ACCESS_KEY_ID": "k", "S3_SECRET_ACCESS_KEY": "s"}
    with pytest.raises(SystemExit, match="R2_API_TOKEN"):
        workspace.S3Store(_r2_settings(tmp_path), keys)
    with pytest.raises(SystemExit, match="CF_TOK"):
        workspace.S3Store(_r2_settings(tmp_path, cf_token_env="CF_TOK"), keys)
    with pytest.raises(SystemExit, match="cf_account_id"):
        workspace.S3Store(_r2_settings(tmp_path, cf_account_id=""), keys | {"R2_API_TOKEN": "t"})
    with pytest.raises(SystemExit, match="604800"):
        workspace.S3Store(_r2_settings(tmp_path, mount_creds_ttl_s=10**6), keys | {"R2_API_TOKEN": "t"})
