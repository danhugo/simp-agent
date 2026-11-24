"""Workspace sync ([sandbox] mount = "sync"): /work is the sandbox's own disk; the bucket keeps the durable copy.

Why: an s3fs mount sends every open/read/write/ls to the bucket over HTTP (~1.7 s per small write on E2B + R2).
Measured 2026-11-25 (Mac -> R2 dev): pulling a workspace as one tar is ~4 s for 1000-3000 files, a diff push after a
tool call 0.7-1.5 s; per-file pulls grow with the file count (7 s / 21 s), full re-pushes 14-31 s.

The server does all bucket I/O; the sandbox holds no bucket credential. Inside the sandbox one small Python script
scans /work, tars changes and extracts what the server sends. A manifest in the sandbox (/tmp/.simp-sync) maps every
file to (size, mtime_ns, etag of the bucket copy):
- pull (new sandbox): list the prefix; files whose etag matches the snapshot index come from the snapshot (one GET),
  the rest one GET each. Extract, write the manifest.
- push (after a tool call, in the background; before pause/kill, waited for): files whose size/mtime changed are tarred
  in the sandbox and PUT one by one (the Files panel reads single files); files gone from /work are deleted. Over the
  workspace quota, nothing new is uploaded.
- reconcile (after a Files panel write/delete, before the next tool call): bucket files whose etag differs from the
  manifest are written into /work; files deleted in the panel are deleted in /work. A file changed on both sides: the
  panel's copy wins, the sandbox's is kept as <name>.conflict-<time>.
- snapshot (at pause/kill): every manifest file still unchanged on disk, as one tar.gz + index next to the prefix
  (<prefix>.sync/, outside the user's files: not in the Files panel, not counted by the quota).

Ponytail: tars are built in memory (fine for MB-sized workspaces; stream through temp files when that becomes GB)."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

log = logging.getLogger("simp_server")

STATE = "/tmp/.simp-sync"
POOL = ThreadPoolExecutor(16, thread_name_prefix="wsync")

SCRIPT = r'''
import json, os, stat, sys, tarfile
W, S = os.environ.get("SIMP_WORK", "/work"), os.environ.get("SIMP_SYNC", "/tmp/.simp-sync")
MAN = S + "/manifest.json"
os.makedirs(S, exist_ok=True)

def load():
    try:
        return json.load(open(MAN))
    except FileNotFoundError:
        return {}

def save(m):
    with open(MAN + ".tmp", "w") as f:
        json.dump(m, f)
    os.replace(MAN + ".tmp", MAN)

def scan():
    out = {}
    for d, _, files in os.walk(W):
        for f in files:
            p = os.path.join(d, f)
            try:
                st = os.lstat(p)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(st.st_mode):
                out[os.path.relpath(p, W)] = [st.st_size, st.st_mtime_ns]
    return out

def target(rel):
    """A path under W that no symlink leads out of (the agent can make symlinks in /work)."""
    p = os.path.normpath(os.path.join(W, rel))
    if os.path.isabs(rel) or not p.startswith(W + "/") or not os.path.realpath(os.path.dirname(p)).startswith(os.path.realpath(W)):
        raise ValueError("unsafe path: " + rel)
    return p

def tar(paths, out):
    with tarfile.open(out, "w:gz", compresslevel=1) as tf:
        for p in paths:
            try:
                tf.add(os.path.join(W, p), arcname=p, recursive=False)
            except FileNotFoundError:
                pass

def stamp(m, p, etag):
    st = os.lstat(os.path.join(W, p))
    m[p] = [st.st_size, st.st_mtime_ns, etag]

cmd = sys.argv[1]
if cmd == "diff":  # -> {changed: {path: [size, mtime]}, deleted: [path]}; changed files tarred to push.tgz
    m, now = load(), scan()
    changed = {p: v for p, v in now.items() if m.get(p, [None, None])[:2] != v}
    deleted = [p for p in m if p not in now]
    tar(changed, S + "/push.tgz")
    print(json.dumps({"changed": changed, "deleted": deleted}))
elif cmd == "commit":  # args: {set: {path: [size, mtime, etag]}, drop: [path]}
    a, m = json.load(open(S + "/args.json")), load()
    m.update(a["set"])
    for p in a["drop"]:
        m.pop(p, None)
    save(m)
elif cmd == "apply":  # args: {rename: {a: b}, delete: [path], keep: [path in snap.tgz], etags: {path: etag}}
    a, m = json.load(open(S + "/args.json")), load()
    for src, dst in a["rename"].items():
        if os.path.lexists(target(src)):
            os.makedirs(os.path.dirname(target(dst)), exist_ok=True)
            os.replace(target(src), target(dst))
            m.pop(src, None)
    for p in a["delete"]:
        try:
            os.remove(target(p))
        except (FileNotFoundError, IsADirectoryError):
            pass
        m.pop(p, None)
    for name, only in (("snap.tgz", set(a["keep"])), ("pull.tgz", None)):
        if not os.path.exists(S + "/" + name):
            continue
        with tarfile.open(S + "/" + name) as tf:
            for mem in tf:
                if not mem.isfile() or only is not None and mem.name not in only:
                    continue
                dst = target(mem.name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.islink(dst):
                    os.remove(dst)
                with tf.extractfile(mem) as src, open(dst + ".simp-tmp", "wb") as out:
                    out.write(src.read())
                os.replace(dst + ".simp-tmp", dst)
        os.remove(S + "/" + name)
    for p, e in a["etags"].items():
        try:
            stamp(m, p, e)
        except FileNotFoundError:
            m.pop(p, None)
    save(m)
elif cmd == "snapshot":  # every file whose disk copy is the bucket copy -> snap-out.tgz; prints {path: etag}
    m, now = load(), scan()
    idx = {p: v[2] for p, v in m.items() if now.get(p) == v[:2]}
    tar(idx, S + "/snap-out.tgz")
    print(json.dumps(idx))
'''
_B64 = base64.b64encode(SCRIPT.encode()).decode()


def script_cmd(*args: str) -> str:
    return f"mkdir -p {STATE} && echo {_B64} | base64 -d > {STATE}/sync.py && python3 {STATE}/sync.py " + " ".join(args)


class Port(Protocol):
    """How the sync reaches one sandbox: a shell command as the sandbox user, and whole-file put/get."""

    async def sh(self, command: str, timeout: float = 300) -> tuple[int | None, str]: ...
    async def put(self, path: str, data: bytes) -> None: ...
    async def get(self, path: str) -> bytes: ...


class SyncError(RuntimeError):
    pass


def _etag(v: str) -> str:
    return (v or "").strip('"')


class WorkSync:
    """One per user box. lock: one sync at a time; web_dirty: the Files panel changed the bucket since the last
    reconcile; full: the last push skipped uploads (workspace quota)."""

    def __init__(self, store, user_id: str, quota=None):
        self.store, self.user_id, self.quota = store, user_id, quota
        self.lock = asyncio.Lock()
        self.web_dirty = False
        self.full = False
        self.task: asyncio.Task | None = None
        self.snap_dirty = False  # pushed changes since the last snapshot

    # ---- bucket ----------------------------------------------------------------------------------------------------

    @property
    def prefix(self) -> str:
        return self.store.prefix(self.user_id)

    @property
    def snap_key(self) -> str:
        return self.prefix.rstrip("/") + ".sync/snapshot.tgz"

    async def _s3(self, fn, *a, **kw):
        return await asyncio.get_running_loop().run_in_executor(POOL, lambda: fn(*a, **kw))

    async def _list(self) -> dict[str, str]:
        """{relative path: etag} of the user's files (s3fs "dir/" markers left out)."""
        def ls():
            out = dict()
            for page in self.store.s3.get_paginator("list_objects_v2").paginate(Bucket=self.store.bucket, Prefix=self.prefix):
                for o in page.get("Contents", []):
                    rel = o["Key"][len(self.prefix):]
                    if rel and not rel.endswith("/"):
                        out[rel] = _etag(o["ETag"])
            return out
        return await self._s3(ls)

    async def _get(self, rel: str) -> bytes | None:
        try:
            return await self._s3(lambda: self.store.s3.get_object(Bucket=self.store.bucket, Key=self.prefix + rel)["Body"].read())
        except self.store.s3.exceptions.NoSuchKey:
            return None

    async def _put(self, key: str, data: bytes) -> str:
        r = await self._s3(self.store.s3.put_object, Bucket=self.store.bucket, Key=key, Body=data)
        return _etag(r["ETag"])

    async def _delete(self, rels: list[str]) -> None:
        for i in range(0, len(rels), 1000):
            await self._s3(self.store.s3.delete_objects, Bucket=self.store.bucket, Delete={
                "Objects": [{"Key": self.prefix + r} for r in rels[i:i + 1000]], "Quiet": True})

    # ---- sandbox ---------------------------------------------------------------------------------------------------

    async def _run(self, port: Port, *args: str) -> str:
        code, out = await port.sh(script_cmd(*args))
        if code != 0:
            raise SyncError(f"workspace sync {args[0]} failed ({code}): {out.strip()[-500:]}")
        return out

    async def _args(self, port: Port, obj: dict) -> None:
        await port.put(f"{STATE}/args.json", json.dumps(obj).encode())

    async def _manifest(self, port: Port) -> dict:
        try:
            return json.loads(await port.get(f"{STATE}/manifest.json"))
        except FileNotFoundError:
            return dict()

    # ---- operations (callers hold self.lock) -----------------------------------------------------------------------

    async def _reconcile(self, port: Port, use_snapshot: bool) -> dict:
        """Bring /work up to date with the bucket (see module doc). -> counts."""
        t0 = time.monotonic()
        self.web_dirty = False  # first: a panel write during this reconcile sets it again
        remote = await self._list()
        man = await self._manifest(port)
        local = json.loads(await self._run(port, "diff")) if man else {"changed": dict(), "deleted": list()}
        stale = [p for p, e in remote.items() if (man.get(p) or [None] * 3)[2] != e]
        gone = [p for p in man if p not in remote and p not in local["changed"]]  # deleted in the panel
        stamp = time.strftime("%Y%m%d-%H%M%S")
        rename = {p: f"{p}.conflict-{stamp}" for p in stale if p in local["changed"]}  # changed on both sides
        keep: list[str] = list()
        if use_snapshot and stale:
            try:
                idx = json.loads((await self._s3(lambda: self.store.s3.get_object(
                    Bucket=self.store.bucket, Key=self.snap_key[:-4] + ".json")["Body"].read())).decode())
                keep = [p for p in stale if idx.get(p) == remote[p]]
                if keep:
                    snap = await self._s3(lambda: self.store.s3.get_object(Bucket=self.store.bucket, Key=self.snap_key)["Body"].read())
                    await port.put(f"{STATE}/snap.tgz", snap)
            except self.store.s3.exceptions.NoSuchKey:
                keep = list()
        fetch = [p for p in stale if p not in set(keep)]
        got = await asyncio.gather(*(self._get(p) for p in fetch))
        if fetch:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=1) as tf:
                for p, data in zip(fetch, got):
                    if data is None:  # deleted since the listing
                        continue
                    ti = tarfile.TarInfo(p)
                    ti.size, ti.mtime = len(data), int(time.time())
                    tf.addfile(ti, io.BytesIO(data))
            await port.put(f"{STATE}/pull.tgz", buf.getvalue())
        if stale or gone or rename:
            await self._args(port, {"rename": rename, "delete": gone, "keep": keep,
                                    "etags": {p: remote[p] for p, d in zip(fetch, got) if d is not None} | {p: remote[p] for p in keep}})
            await self._run(port, "apply")
        if not man and not stale:
            await self._args(port, {"set": dict(), "drop": list()})
            await self._run(port, "commit")  # an empty manifest: an empty workspace is synced too
        n = {"snapshot": len(keep), "fetched": len(fetch), "deleted": len(gone), "conflicts": len(rename),
             "s": round(time.monotonic() - t0, 2)}
        if stale or gone:
            log.info("workspace reconcile %s", n, extra={"user": self.user_id})
        return n

    async def _push(self, port: Port) -> dict:
        t0 = time.monotonic()
        d = json.loads(await self._run(port, "diff"))
        changed, deleted = d["changed"], d["deleted"]
        if not changed and not deleted:
            return {"put": 0, "deleted": 0}
        man = await self._manifest(port) if changed else dict()
        added = sum(v[0] - (man.get(p) or [0])[0] for p, v in changed.items())
        if changed and self.quota is not None and added > 0 and not await self.quota.fits(self.user_id, added):
            self.full = True
            log.warning("workspace full: %d changed files not saved", len(changed), extra={"user": self.user_id})
            changed = dict()
        else:
            self.full = False
        sets: dict[str, list] = dict()
        if changed:
            data = await port.get(f"{STATE}/push.tgz")
            with tarfile.open(fileobj=io.BytesIO(data)) as tf:
                items = [(m.name, tf.extractfile(m).read()) for m in tf.getmembers() if m.isfile()]
            etags = await asyncio.gather(*(self._put(self.prefix + p, b) for p, b in items))
            sets = {p: [*changed[p], e] for (p, _), e in zip(items, etags) if p in changed}
        if deleted:
            await self._delete(deleted)
        await self._args(port, {"set": sets, "drop": deleted})
        await self._run(port, "commit")
        self.snap_dirty = True
        if self.quota is not None:
            self.quota.touch(self.user_id)
        n = {"put": len(sets), "deleted": len(deleted), "s": round(time.monotonic() - t0, 2)}
        log.info("workspace push %s", n, extra={"user": self.user_id})
        return n

    async def _snapshot(self, port: Port) -> None:
        if not self.snap_dirty:
            return
        idx = json.loads(await self._run(port, "snapshot"))
        data = await port.get(f"{STATE}/snap-out.tgz")
        await port.sh(f"rm -f {STATE}/snap-out.tgz")
        await self._put(self.snap_key, data)
        await self._put(self.snap_key[:-4] + ".json", json.dumps(idx).encode())  # after the tar: index never ahead
        self.snap_dirty = False

    # ---- what the boxes call ---------------------------------------------------------------------------------------

    async def pull(self, port: Port) -> dict:
        """A new sandbox: fill the empty /work from the snapshot and the bucket."""
        async with self.lock:
            self.snap_dirty = False
            return await self._reconcile(port, use_snapshot=True)

    async def before_call(self, port: Port) -> None:
        """Before a tool call: take the Files panel's changes in (only when there were some)."""
        if self.web_dirty:
            async with self.lock:
                if self.web_dirty:
                    await self._reconcile(port, use_snapshot=False)

    def push_soon(self, port: Port) -> None:
        """After a tool call: push in the background; one more push follows if one is already running."""
        async def run():
            try:
                async with self.lock:
                    if self.web_dirty:
                        await self._reconcile(port, use_snapshot=False)
                    await self._push(port)
            except Exception as e:
                log.warning("workspace push failed (retried after the next tool call): %s", e, extra={"user": self.user_id})
        prev = self.task

        async def chain():
            if prev is not None:
                await asyncio.gather(prev, return_exceptions=True)
            await run()
        if prev is not None and not prev.done() and getattr(prev, "simp_queued", False):
            return  # a push is already queued after the running one: it will see these changes too
        self.task = asyncio.ensure_future(chain())
        self.task.simp_queued = prev is not None and not prev.done()

    async def flush(self, port: Port, snapshot: bool = True) -> None:
        """Before pause/kill/stop: wait for a background push, push the rest, then the snapshot. Raises on failure
        (the caller logs it: the files since the last good push are then only in the sandbox)."""
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)
        async with self.lock:
            if self.web_dirty:
                await self._reconcile(port, use_snapshot=False)
            await self._push(port)
            if snapshot:
                await self._snapshot(port)
