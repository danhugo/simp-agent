"""Workspace store slot (design 2026-11-16 step 2): where a user's files live. `[workspace] store = "local" | "s3"`.

The Files panel goes through the store, never through the sandbox (browsing never starts compute). Sandboxes see the
same files at /work: Docker bind-mounts a LocalStore dir; with S3Store the sandbox FUSE-mounts the user's prefix
using `mount_creds(user_id)` (scoped to users/<user_id>/ when the store supports STS AssumeRole, e.g. AWS S3, MinIO).

Paths are relative to the user's workspace ("a/b.txt", "/work/a/b.txt" or "."); escaping it raises PermissionError,
a missing file FileNotFoundError, like LocalEnv."""

from __future__ import annotations

import asyncio
import json
import os
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
        p = self._env(user_id)._path(rel(path) or ".")
        await asyncio.to_thread(p.unlink)

    async def mount_creds(self, user_id: str) -> dict | None:
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
        await asyncio.to_thread(self.s3.delete_object, Bucket=self.bucket, Key=self.key(user_id, path))

    async def mount_creds(self, user_id: str) -> dict:
        """What a FUSE mount in the user's sandbox needs: endpoint, bucket, prefix and a credential for that prefix."""
        prefix = self.prefix(user_id)
        out = {"endpoint": self.mount_endpoint, "bucket": self.bucket, "prefix": prefix, "region": self.region}
        if self.scope == "none":
            return out | {"access_key": self.access_key, "secret_key": self.secret_key, "session_token": ""}
        policy = {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": [f"arn:aws:s3:::{self.bucket}"],
             "Condition": {"StringLike": {"s3:prefix": [prefix, prefix + "*"]}}},
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
             "Resource": [f"arn:aws:s3:::{self.bucket}/{prefix}*"]}]}
        c = (await asyncio.to_thread(self.sts.assume_role, RoleArn=self.role_arn, RoleSessionName=f"simp-{user_id}"[:64],
                                     Policy=json.dumps(policy), DurationSeconds=self.creds_ttl))["Credentials"]
        return out | {"access_key": c["AccessKeyId"], "secret_key": c["SecretAccessKey"], "session_token": c["SessionToken"]}

    async def restore(self, user_id: str, at: datetime, path: str = "") -> list[str]:
        """Put every object under the user's prefix (or under `path` in it) back to its version at time `at`: objects
        changed since are overwritten with the old version, objects created since (or deleted at `at`) are deleted.
        Old versions stay (versioning), so a restore can itself be undone. Returns the keys it changed."""
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
    if mount not in ("bind", "fuse"):
        return f'[sandbox] mount must be "bind" or "fuse", not {mount!r}'
    if mount == "fuse" and store != "s3":
        return '[sandbox] mount = "fuse" needs [workspace] store = "s3" (it mounts the bucket)'
    if mount == "bind" and store == "s3" and kind == "docker":
        return '[workspace] store = "s3" with Docker needs [sandbox] mount = "fuse" (a bind mount needs a local dir)'
    if kind == "e2b" and mount != "fuse":
        return '[sandbox] kind = "e2b" needs mount = "fuse"'
    return None


def sandbox_kind(settings: dict) -> str:
    path = settings.get("plugins", dict()).get("sandbox", "")
    return "e2b" if path.endswith(":E2BSandbox") else "docker" if path.endswith(":DockerSandbox") else "local"
