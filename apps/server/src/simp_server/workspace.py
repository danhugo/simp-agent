"""Workspace store slot (design 2026-11-16 step 2): where a user's files live. `[workspace] store = "local" | "s3"`.

The Files panel goes through the store, never through the sandbox (browsing never starts compute). Sandboxes see the
same files at /work: Docker bind-mounts a LocalStore dir; with S3Store the sandbox FUSE-mounts the user's prefix
using `mount_creds(user_id)` (scoped to users/<user_id>/: STS AssumeRole on AWS S3 / MinIO, or Cloudflare R2's
Temporary Credentials API with `mount_scope = "r2"`).

Paths are relative to the user's workspace ("a/b.txt", "/work/a/b.txt" or "."); escaping it raises PermissionError,
a missing file FileNotFoundError, like LocalEnv."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from simp_agent.agent.env import LocalEnv

KINDS = ("local", "s3")


def rel(path: str) -> str:
    """Workspace-relative POSIX key part ("" = the root). /work is the sandbox's name for the root."""
    path = str(path)
    if path == "/work" or path.startswith("/work/"):
        path = path[len("/work"):]
    elif path.startswith("/"):
        raise PermissionError(f"path escapes root: {path}")
    parts = list()
    for seg in path.split("/"):
        if seg == "..":
            if not parts:
                raise PermissionError(f"path escapes root: {path}")
            parts.pop()
        elif seg not in ("", "."):
            parts.append(seg)
    return "/".join(parts)


class LocalStore:
    """A dir per user on this server (today's workspaces dir). Only pairs with the Docker bind mount."""

    kind = "local"

    def __init__(self, settings: dict):
        s = settings.get("sandbox", dict())
        self.root = Path(s.get("workspaces_dir", Path(settings["data_dir"]) / "workspaces")).expanduser()

    def _env(self, user_id: str) -> LocalEnv:
        (self.root / user_id).mkdir(parents=True, exist_ok=True)
        return LocalEnv(str((self.root / user_id).resolve()))

    async def list(self, user_id: str, path: str) -> list[dict]:
        return await self._env(user_id).list(rel(path) or ".")

    async def read(self, user_id: str, path: str) -> bytes:
        return await self._env(user_id).read_bytes(rel(path) or ".")

    async def write(self, user_id: str, path: str, data: bytes) -> None:
        await self._env(user_id).write_bytes(rel(path) or ".", data)

    async def delete(self, user_id: str, path: str) -> None:
        """A file, or a folder with everything in it."""
        env, r = self._env(user_id), rel(path)
        if not r:
            raise PermissionError("cannot delete the workspace root")
        p = Path(env.root) / r
        if p.is_dir() and not p.is_symlink():
            if not p.resolve().is_relative_to(Path(env.root).resolve()):  # a symlinked parent
                raise PermissionError(f"path escapes root: {path}")
            await asyncio.to_thread(shutil.rmtree, p)  # rmtree never follows symlinks inside
        else:
            await asyncio.to_thread(env._unlink, r)  # O_NOFOLLOW walk, like read/write

    async def size(self, user_id: str) -> int:
        def walk():
            n = 0
            for d, _, names in os.walk(self.root / user_id):
                for f in names:
                    try:
                        n += os.lstat(os.path.join(d, f)).st_size
                    except OSError:
                        pass
            return n
        return await asyncio.to_thread(walk)

    async def mount_creds(self, user_id: str, read_only: bool = False) -> dict | None:
        return None  # bind mount: nothing to hand over

    async def restore(self, user_id: str, at: datetime, path: str = "") -> list[str]:
        raise SystemExit("workspace-restore needs [workspace] store = \"s3\" with bucket versioning")


class S3Store:
    """A prefix per user in an S3-compatible bucket (AWS S3, R2, MinIO). Keys/secret come from <data_dir>/.env or the
    process env, by the names in `access_key_env` / `secret_key_env`. Versioning must be ON (restore relies on it)."""

    kind = "s3"

    def __init__(self, settings: dict, keys: dict | None = None):
        import boto3

        w = settings["workspace"]
        keys = keys or dict()
        key = lambda n, d: keys.get(w.get(n, d)) or os.environ.get(w.get(n, d))  # noqa: E731
        self.bucket, self.endpoint = w["bucket"], w.get("endpoint")
        self.region = w.get("region", "us-east-1")
        self.prefix_tpl = w.get("prefix", "users/{user_id}/")
        self.access_key, self.secret_key = key("access_key_env", "S3_ACCESS_KEY_ID"), key("secret_key_env", "S3_SECRET_ACCESS_KEY")
        # scoped mount creds: STS AssumeRole with a session policy limited to the user's prefix. AWS needs a real
        # role_arn; MinIO accepts any. "none": hand the store key itself to the mount (dev only, see design Security).
        self.scope = w.get("mount_scope", "sts")
        self.role_arn = w.get("role_arn", "arn:aws:iam::000000000000:role/simp-mount")
        self.creds_ttl = int(w.get("mount_creds_ttl_s", 3600))
        if self.scope not in ("sts", "r2", "none"):
            raise SystemExit(f'settings: [workspace] mount_scope must be "sts", "r2" or "none", not {self.scope!r}')
        if self.scope == "r2":  # R2 has no STS: the Cloudflare API mints temp creds bound to a prefix
            self.cf_account_id = w.get("cf_account_id")
            self.cf_token = key("cf_token_env", "R2_API_TOKEN")
            self.cf_api = w.get("cf_api", "https://api.cloudflare.com/client/v4")
            self.cf_transport = None  # tests swap in an httpx.MockTransport
            if not self.cf_account_id or not self.cf_token:
                raise SystemExit('[workspace] mount_scope = "r2" needs [workspace] cf_account_id and a Cloudflare API '
                                 f'token in <data_dir>/.env as {w.get("cf_token_env", "R2_API_TOKEN")} '
                                 '(or set cf_token_env)')
            if not 0 < self.creds_ttl <= 604800:
                raise SystemExit("[workspace] mount_creds_ttl_s must be 1..604800 (R2 temporary credentials max 7 days)")
        # the endpoint as seen from inside a sandbox (Docker Desktop: the host is host.docker.internal)
        self.mount_endpoint = w.get("mount_endpoint") or (self.endpoint or "").replace("127.0.0.1", "host.docker.internal").replace(
            "localhost", "host.docker.internal")
        opts = dict(endpoint_url=self.endpoint, region_name=self.region,
                    aws_access_key_id=self.access_key, aws_secret_access_key=self.secret_key)
        self.s3, self.sts = boto3.client("s3", **opts), boto3.client("sts", **opts)

    def prefix(self, user_id: str) -> str:
        return self.prefix_tpl.format(user_id=user_id)

    def key(self, user_id: str, path: str) -> str:
        return self.prefix(user_id) + rel(path)

    async def list(self, user_id: str, path: str) -> list[dict]:
        base = self.key(user_id, path).rstrip("/")
        base = base + "/" if base != self.prefix(user_id).rstrip("/") else self.prefix(user_id)

        def ls():
            out, pages = dict(), self.s3.get_paginator("list_objects_v2")
            for page in pages.paginate(Bucket=self.bucket, Prefix=base, Delimiter="/"):
                for d in page.get("CommonPrefixes", []):
                    name = d["Prefix"][len(base):].rstrip("/")
                    out[name] = {"name": name, "is_dir": True, "size": 0}
                for o in page.get("Contents", []):
                    name = o["Key"][len(base):]
                    if name:  # "dir/" marker objects (s3fs) list as the dir itself
                        out[name] = {"name": name, "is_dir": False, "size": o["Size"]}
            if not out and base != self.prefix(user_id):
                raise FileNotFoundError(path)
            return [out[k] for k in sorted(out)]

        return await asyncio.to_thread(ls)

    async def read(self, user_id: str, path: str) -> bytes:
        k = self.key(user_id, path)

        def get():
            try:
                return self.s3.get_object(Bucket=self.bucket, Key=k)["Body"].read()
            except self.s3.exceptions.NoSuchKey:
                raise FileNotFoundError(path) from None

        return await asyncio.to_thread(get)

    async def write(self, user_id: str, path: str, data: bytes) -> None:
        if not rel(path):
            raise IsADirectoryError(path)
        await asyncio.to_thread(self.s3.put_object, Bucket=self.bucket, Key=self.key(user_id, path), Body=data)

    async def delete(self, user_id: str, path: str) -> None:
        """A file, or a folder (every key under it, and s3fs's "dir/" marker)."""
        k = self.key(user_id, path)
        if not rel(path):
            raise PermissionError("cannot delete the workspace root")

        def rm():
            keys = [k] + [o["Key"] for page in self.s3.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=k + "/") for o in page.get("Contents", [])]
            for i in range(0, len(keys), 1000):
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": x} for x in keys[i:i + 1000]],
                                                                   "Quiet": True})
        await asyncio.to_thread(rm)

    async def size(self, user_id: str) -> int:
        """Bytes under the user's prefix (current objects; R2 keeps no old versions). One request per 1000 keys."""
        def total():
            return sum(o["Size"] for page in self.s3.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=self.prefix(user_id)) for o in page.get("Contents", []))
        return await asyncio.to_thread(total)

    async def mount_creds(self, user_id: str, read_only: bool = False) -> dict:
        """What a FUSE mount in the user's sandbox needs: endpoint, bucket, prefix and a credential for that prefix.
        read_only (workspace full): the credential itself can only read, so the bucket refuses writes too."""
        prefix = self.prefix(user_id)
        out = {"endpoint": self.mount_endpoint, "bucket": self.bucket, "prefix": prefix, "region": self.region}
        if self.scope == "none":
            return out | {"access_key": self.access_key, "secret_key": self.secret_key, "session_token": ""}
        if self.scope == "r2":
            return out | await self._r2_creds(prefix, read_only)
        actions = ["s3:GetObject"] if read_only else ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        policy = {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": [f"arn:aws:s3:::{self.bucket}"],
             "Condition": {"StringLike": {"s3:prefix": [prefix, prefix + "*"]}}},
            {"Effect": "Allow", "Action": actions, "Resource": [f"arn:aws:s3:::{self.bucket}/{prefix}*"]}]}
        c = (await asyncio.to_thread(self.sts.assume_role, RoleArn=self.role_arn, RoleSessionName=f"simp-{user_id}"[:64],
                                     Policy=json.dumps(policy), DurationSeconds=self.creds_ttl))["Credentials"]
        left = (c["Expiration"] - datetime.now(c["Expiration"].tzinfo)).total_seconds() if c.get("Expiration") else self.creds_ttl
        return out | {"access_key": c["AccessKeyId"], "secret_key": c["SecretAccessKey"], "session_token": c["SessionToken"],
                      "expires_in": max(0.0, left)}  # sandboxes remount before this runs out (review M2)

    async def _r2_creds(self, prefix: str, read_only: bool = False) -> dict:
        """Cloudflare R2 Temporary Credentials API: creds limited to `prefix`, signed off the store key."""
        import httpx

        body = {"bucket": self.bucket, "parentAccessKeyId": self.access_key,
                "permission": "object-read-only" if read_only else "object-read-write",
                "ttlSeconds": self.creds_ttl, "prefixes": [prefix]}
        async with httpx.AsyncClient(timeout=30, transport=self.cf_transport) as http:
            r = await http.post(f"{self.cf_api}/accounts/{self.cf_account_id}/r2/temp-access-credentials", json=body,
                                headers={"Authorization": f"Bearer {self.cf_token}"})
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else dict()
        res = data.get("result") or dict()
        if r.status_code != 200 or not data.get("success") or not res.get("sessionToken"):
            errs = "; ".join(e.get("message", "") for e in data.get("errors", [])) or r.text[:200]
            raise RuntimeError(f"R2 temporary credentials failed (HTTP {r.status_code}): {errs}")
        # the response has no expiry: count from now, a little early so the sandbox remounts in time
        return {"access_key": res["accessKeyId"], "secret_key": res["secretAccessKey"],
                "session_token": res["sessionToken"], "expires_in": max(0.0, self.creds_ttl - 60.0)}

    async def restore(self, user_id: str, at: datetime, path: str = "") -> list[str]:
        """Put every object under the user's prefix (or under `path` in it) back to its version at time `at`: objects
        changed since are overwritten with the old version, objects created since (or deleted at `at`) are deleted.
        Old versions stay (versioning), so a restore can itself be undone. Returns the keys it changed."""
        if self.scope == "r2" or "r2.cloudflarestorage.com" in (self.endpoint or ""):
            raise SystemExit("workspace-restore needs bucket versioning, which Cloudflare R2 does not have")
        base = self.key(user_id, path) if rel(path) else self.prefix(user_id)

        def run():
            latest, at_t = dict(), dict()  # key -> newest version; key -> newest version at or before `at`
            for page in self.s3.get_paginator("list_object_versions").paginate(Bucket=self.bucket, Prefix=base):
                for v in page.get("Versions", []) + page.get("DeleteMarkers", []):
                    v["deleted"] = "Size" not in v
                    k = v["Key"]
                    if v["IsLatest"]:
                        latest[k] = v
                    if v["LastModified"] <= at and (k not in at_t or v["LastModified"] > at_t[k]["LastModified"]):
                        at_t[k] = v
            changed = list()
            for k, cur in sorted(latest.items()):
                old = at_t.get(k)
                if old is not None and (old["VersionId"] == cur["VersionId"] or not old["deleted"] and not cur["deleted"]
                                        and old["ETag"] == cur["ETag"]):
                    continue  # unchanged (or already restored: same content)
                if old is None or old["deleted"]:
                    if not cur["deleted"]:
                        self.s3.delete_object(Bucket=self.bucket, Key=k)
                        changed.append(k)
                else:
                    self.s3.copy_object(Bucket=self.bucket, Key=k,
                                        CopySource={"Bucket": self.bucket, "Key": k, "VersionId": old["VersionId"]})
                    changed.append(k)
            return changed

        return await asyncio.to_thread(run)


def make_store(settings: dict, keys: dict | None = None):
    kind = settings.get("workspace", dict()).get("store", "local")
    if kind not in KINDS:
        raise SystemExit(f"settings: [workspace] store must be one of {', '.join(KINDS)}, not {kind!r}")
    return S3Store(settings, keys) if kind == "s3" else LocalStore(settings)


def check_config(settings: dict) -> str | None:
    """Store x sandbox x mount combinations that cannot work (design "How the mount works")."""
    store = settings.get("workspace", dict()).get("store", "local")
    s = settings.get("sandbox", dict())
    kind, mount = sandbox_kind(settings), s.get("mount", "fuse" if sandbox_kind(settings) == "e2b" else "bind")
    if kind == "e2b" and store == "local":
        return ('[sandbox] kind = "e2b" with [workspace] store = "local": a cloud sandbox cannot mount a folder on this '
                'server. Move the workspaces to a bucket first ([workspace] store = "s3"), then use e2b.')
    if mount not in ("bind", "fuse", "sync"):
        return f'[sandbox] mount must be "bind", "fuse" or "sync", not {mount!r}'
    if mount in ("fuse", "sync") and store != "s3":
        return f'[sandbox] mount = "{mount}" needs [workspace] store = "s3" (the bucket holds the files)'
    if mount == "bind" and store == "s3" and kind == "docker":
        return '[workspace] store = "s3" with Docker needs [sandbox] mount = "sync" or "fuse" (a bind mount needs a local dir)'
    if kind == "e2b" and mount not in ("fuse", "sync"):
        return '[sandbox] kind = "e2b" needs mount = "sync" or "fuse"'
    if kind == "docker" and mount == "fuse" and not s.get("dev_fuse"):
        return ('[sandbox] mount = "fuse" with Docker is for tests only: the container gets CAP_SYS_ADMIN, /dev/fuse, no '
                'AppArmor and a bridge network with access to host.docker.internal (your host). Set [sandbox] '
                'dev_fuse = true to use it anyway.')
    w = settings.get("workspace", dict())
    if store == "s3" and kind != "local" and mount == "fuse" and w.get("mount_scope", "sts") == "none" and not w.get("dev_unscoped_mount"):
        return ('[workspace] mount_scope = "none" hands the store key itself (every user\'s files) to each sandbox. '
                'Dev only: set [workspace] dev_unscoped_mount = true to use it anyway.')
    return None


def sandbox_kind(settings: dict) -> str:
    path = settings.get("plugins", dict()).get("sandbox", "")
    return "e2b" if path.endswith(":E2BSandbox") else "docker" if path.endswith(":DockerSandbox") else "local"
