"""Skills per user: the server's library (apps/server/skill_library) is a catalog; adding a skill copies it into the
user's own skill store. The agent only sees that store.

Storage: the user's R2, beside their workspace under "<user_id>.skills/" (not in Files, not in the quota):
  skills.json           the catalogue: name -> label, description, version, ..., hash (of the files)
  <name>.tar.gz         one object per skill (one GET to load it, one PUT to add or update it)
The server keeps only the small catalogues in RAM; a skill's files come from the library when its hash matches the
library's copy (most users), else from its tar in R2, through a small cache bounded in bytes.
In the sandbox: the skills are written (as root, read-only for the agent) to SKILLS_DIR when the sandbox starts work and
whenever they changed; adding, updating or removing one pushes it to a running sandbox at once (push()).
Moved here once on first load: skills on the server's disk (<data_dir>/skills/<user_id>/, v0.15.x) and the per-file
copies v0.15.0 kept in the same R2 prefix. New users start with DEFAULT. Enable/disable stays in store.skill_off."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import json
import re
import shlex
import shutil
import tarfile
from collections import OrderedDict
from pathlib import Path

from simp_agent.plugins.skills import front

from .sandboxes.toolset import SKILLS_DIR

LIBRARY = Path(__file__).parents[2] / "skill_library"  # apps/server/skill_library
DEFAULT = ("docx", "pdf", "pptx", "xlsx")
CATALOG = "skills.json"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
CACHE_BYTES = 64 << 20  # skill files kept in RAM (beyond the library's own), least recently used dropped first


def _meta(text: str, folder: str) -> dict:
    m = front(text)
    return {"name": folder, "label": m.get("label") or m.get("name") or folder, "description": m.get("description", ""),
            "version": str(m.get("version", "1")), "source": m.get("source", ""), "license": m.get("license", "")}


def files_hash(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for p, data in sorted(files.items()):
        h.update(p.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()[:16]


def pack(files: dict[str, bytes], prefix: str = "") -> bytes:
    """A reproducible tar (fixed mtimes, no owners); gzipped when prefix is empty (the R2 object)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for p, data in sorted(files.items()):
            info = tarfile.TarInfo(prefix + p)
            info.size, info.mode = len(data), 0o755 if p.endswith((".py", ".sh", ".js")) else 0o644
            t.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()
    return gzip.compress(raw, mtime=0) if not prefix else raw


def unpack(blob: bytes) -> dict[str, bytes]:
    out = dict()
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob)), mode="r") as t:
        for m in t.getmembers():
            if m.isfile() and not m.name.startswith(("/", "..")) and "/../" not in m.name:
                out[m.name] = t.extractfile(m).read()
    return out


def library(root: Path = LIBRARY) -> dict[str, dict]:
    """name -> meta + files {relative path: bytes} + hash, read once at startup."""
    out = dict()
    for f in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
        d = f.parent
        files = {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()
                 and "__pycache__" not in p.parts}
        out[d.name] = {**_meta(f.read_text(), d.name), "files": files, "hash": files_hash(files)}
    return out


class _Source:
    """DirSkillSource surface (list / read) over one user's skills, for the Skills plugin."""

    def __init__(self, mgr: "UserSkills", user_id: str):
        self.mgr, self.user_id = mgr, user_id

    def list(self) -> list[dict]:
        skills = self.mgr.catalogs.get(self.user_id, dict())
        return sorted(({**s, "dir": f"{SKILLS_DIR}/{n}"} for n, s in skills.items()), key=lambda s: s["label"].lower())

    async def read(self, name: str, path: str = "SKILL.md") -> str:
        if name not in await self.mgr.load(self.user_id):
            raise FileNotFoundError(f"no skill {name!r}")
        files = await self.mgr.files(self.user_id, name)
        if path not in files:
            raise FileNotFoundError(f"no {path} in skill {name!r}")
        return files[path].decode(errors="replace")


class UserSkills:
    def __init__(self, store, lib: dict[str, dict] | None = None, disk: Path | None = None):
        """store: the workspace store (R2; LocalStore in tests). disk: <data_dir>/skills, where v0.15.x kept skills
        (moved to the store on first load)."""
        self.store, self.disk, self.lib = store, Path(disk) if disk else None, library() if lib is None else lib
        self.catalogs: dict[str, dict[str, dict]] = dict()  # user -> name -> meta + hash (small)
        self.blobs: OrderedDict[str, dict[str, bytes]] = OrderedDict()  # hash -> files, not from the library
        self.locks: dict[str, asyncio.Lock] = dict()
        self.push = None  # async (user_id) -> None: install into the user's running sandbox now (set by create_app)

    @staticmethod
    def sid(user_id: str) -> str:  # the store's pseudo user holding the skills
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
            raise ValueError(f"bad user id {user_id!r}")
        return f"{user_id}.skills"

    def source(self, user_id: str) -> _Source:
        return _Source(self, user_id)

    # ---- the store ---------------------------------------------------------------------------------------------------

    async def _save_catalog(self, user_id: str, cat: dict[str, dict]) -> None:
        await self.store.write(self.sid(user_id), CATALOG, json.dumps({"skills": cat}, ensure_ascii=False).encode())

    async def _put(self, user_id: str, name: str, files: dict[str, bytes]) -> dict:
        """Store one skill; returns its catalogue entry."""
        h = files_hash(files)
        lib = self.lib.get(name)
        if not (lib and lib.get("hash") == h):  # not the library's copy: keep its files at hand
            self._remember(h, files)
        await self.store.write(self.sid(user_id), f"{name}.tar.gz", await asyncio.to_thread(pack, files))
        meta = _meta(files["SKILL.md"].decode(errors="replace"), name)
        return {**meta, "hash": h}

    def _remember(self, h: str, files: dict[str, bytes]) -> None:
        self.blobs[h] = files
        self.blobs.move_to_end(h)
        total = sum(sum(len(v) for v in f.values()) for f in self.blobs.values())
        while total > CACHE_BYTES and len(self.blobs) > 1:
            _, old = self.blobs.popitem(last=False)
            total -= sum(len(v) for v in old.values())

    async def files(self, user_id: str, name: str) -> dict[str, bytes]:
        """A skill's files: the library's when they match, else the cache, else its tar from the store (one GET)."""
        meta = (await self.load(user_id))[name]
        lib = self.lib.get(name)
        if lib and lib.get("hash") == meta["hash"]:
            return lib["files"]
        if meta["hash"] in self.blobs:
            self.blobs.move_to_end(meta["hash"])
            return self.blobs[meta["hash"]]
        files = await asyncio.to_thread(unpack, await self.store.read(self.sid(user_id), f"{name}.tar.gz"))
        self._remember(meta["hash"], files)
        return files

    # ---- moving older stores in ----------------------------------------------------------------------------------------

    def _from_disk(self, user_id: str) -> dict[str, dict[str, bytes]] | None:
        """v0.15.x: <data_dir>/skills/<user_id>/<name>/... (None: nothing there)."""
        d = self.disk / user_id if self.disk else None
        if d is None or not d.is_dir():
            return None
        out = dict()
        for sk in sorted(d.iterdir()):
            if sk.is_dir() and NAME.fullmatch(sk.name) and (sk / "SKILL.md").is_file():
                out[sk.name] = {p.relative_to(sk).as_posix(): p.read_bytes() for p in sorted(sk.rglob("*"))
                                if p.is_file() and not p.is_symlink()}
        return out

    async def _from_per_file(self, user_id: str, entries: list[dict]) -> dict[str, dict[str, bytes]] | None:
        """v0.15.0: every file its own object, "<user>.skills/<name>/<path>" (None: nothing there)."""
        if not any(e["is_dir"] for e in entries) and not any(e["name"] == ".seeded" for e in entries):
            return None
        out, sid = dict(), self.sid(user_id)

        async def walk(folder: str) -> dict[str, bytes]:
            got = dict()
            for e in await self.store.list(sid, folder):
                p = f"{folder}/{e['name']}"
                if e["is_dir"]:
                    got |= {f"{e['name']}/{k}": v for k, v in (await walk(p)).items()}
                else:
                    got[e["name"]] = await self.store.read(sid, p)
            return got
        for e in entries:
            if e["is_dir"] and NAME.fullmatch(e["name"]):
                files = await walk(e["name"])
                if "SKILL.md" in files:
                    out[e["name"]] = files
        return out

    async def load(self, user_id: str) -> dict[str, dict]:
        """The user's catalogue (cached in RAM): name -> meta + hash. A new user gets DEFAULT first."""
        if user_id in self.catalogs:
            return self.catalogs[user_id]
        async with self.locks.setdefault(user_id, asyncio.Lock()):
            if user_id in self.catalogs:
                return self.catalogs[user_id]
            sid = self.sid(user_id)
            try:
                cat = json.loads(await self.store.read(sid, CATALOG))["skills"]
            except FileNotFoundError:
                cat = await self._first_load(user_id)
            self.catalogs[user_id] = cat
            return cat

    async def _first_load(self, user_id: str) -> dict[str, dict]:
        sid = self.sid(user_id)
        try:
            entries = await self.store.list(sid, "")
        except FileNotFoundError:
            entries = []
        old = await asyncio.to_thread(self._from_disk, user_id)
        per_file = await self._from_per_file(user_id, entries) if old is None else None
        source = old if old is not None else per_file
        if source is None:
            source = {n: self.lib[n]["files"] for n in DEFAULT if n in self.lib}
        cat = dict()
        for n, files in source.items():
            cat[n] = await self._put(user_id, n, files)
        await self._save_catalog(user_id, cat)
        if per_file is not None:  # the per-file copies, now packed
            for e in entries:
                if e["is_dir"] or e["name"] == ".seeded":
                    try:
                        await self.store.delete(sid, e["name"])
                    except Exception:
                        pass
        if old is not None:
            await asyncio.to_thread(shutil.rmtree, self.disk / user_id, True)
        return cat

    # ---- what the web app calls ----------------------------------------------------------------------------------------

    async def add(self, user_id: str, name: str) -> None:
        """Copy a library skill into the user's store (again = update to the library's version). LookupError: unknown."""
        if name not in self.lib:
            raise LookupError(f"no library skill {name!r}")
        cat = dict(await self.load(user_id))
        cat[name] = await self._put(user_id, name, self.lib[name]["files"])
        await self._save_catalog(user_id, cat)
        self.catalogs[user_id] = cat
        await self._push(user_id)

    async def remove(self, user_id: str, name: str) -> None:
        cat = dict(await self.load(user_id))
        if name not in cat:
            raise LookupError(f"no skill {name!r}")
        del cat[name]
        await self._save_catalog(user_id, cat)
        self.catalogs[user_id] = cat
        try:
            await self.store.delete(self.sid(user_id), f"{name}.tar.gz")
        except Exception:
            pass
        await self._push(user_id)

    async def _push(self, user_id: str) -> None:
        """Into the user's sandbox now if it is running; a stopped one gets them when it next starts work."""
        if self.push is not None:
            try:
                await self.push(user_id)
            except Exception:
                pass  # the next command installs them anyway

    # ---- the sandbox -------------------------------------------------------------------------------------------------

    def version(self, user_id: str) -> str:
        """Changes when the user adds, updates or removes a skill."""
        cat = self.catalogs.get(user_id, dict())
        return hashlib.sha256(json.dumps(sorted((n, s["hash"]) for n, s in cat.items())).encode()).hexdigest()[:16]

    async def tar(self, user_id: str) -> bytes:
        """Every skill of the user in one tar, <name>/<path> (what the sandbox untars)."""
        parts = [pack(await self.files(user_id, n), f"{n}/") for n in sorted(await self.load(user_id))]
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w") as t:
            for part in parts:
                with tarfile.open(fileobj=io.BytesIO(part), mode="r") as src:
                    for m in src.getmembers():
                        t.addfile(m, src.extractfile(m))
        return out.getvalue()

    async def to_sandbox(self, box, root_sh, put) -> None:
        """Write the user's skills into the sandbox at SKILLS_DIR when they changed since it last got them.
        root_sh(cmd) runs as root; put(path, data) writes a file as the agent's user. Read-only for the agent."""
        await self.load(box.user_id)
        ver = self.version(box.user_id)
        if getattr(box, "skills_ver", None) == ver:
            return
        # parallel tool calls (and a push from the web app) each come here: one installs, the others wait and then
        # find it done (two at once deleted and untarred over each other: "tar: docx/LICENSE.txt: Cannot open")
        lock = box.__dict__.setdefault("skills_lock", asyncio.Lock())
        async with lock:
            ver = self.version(box.user_id)
            if getattr(box, "skills_ver", None) == ver:
                return
            tmp = "/tmp/.simp-skills.tar"
            await put(tmp, await self.tar(box.user_id))
            d = shlex.quote(SKILLS_DIR)
            code, out = await root_sh(f"mkdir -p {d} && find {d} -mindepth 1 -delete && tar -xf {tmp} -C {d} "
                                      f"--no-same-owner && chmod -R a+rX,go-w {d} && rm -f {tmp}")
            if code != 0:
                raise RuntimeError(f"could not install skills in the sandbox: {out.strip()[:200]}")
            box.skills_ver = ver
