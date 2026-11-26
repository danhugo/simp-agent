"""Skills per user: the server's library (apps/server/skill_library) is a catalog; adding a skill copies its folder into
the user's own skill store. The agent only sees that store.

Storage: the server's disk, <data_dir>/skills/<user_id>/<name>/ (only the server reads skills; it writes them into the
sandbox itself), so loading is a local read. v0.15.0 kept them in the workspace store under "<user_id>.skills": a
user with nothing on disk yet gets those copied over once (and deleted there).
In the sandbox: the user's skills are written (as root, read-only for the agent) to SKILLS_DIR before a command runs,
whenever they changed since the sandbox last got them (box.skills_ver).
New users start with DEFAULT (the office skills). Enable/disable stays as before (store.skill_off)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import posixpath
import re
import shlex
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from simp_agent.plugins.skills import front

from .sandboxes.toolset import SKILLS_DIR

LIBRARY = Path(__file__).parents[2] / "skill_library"  # apps/server/skill_library
DEFAULT = ("docx", "pdf", "pptx", "xlsx")
SEEDED = ".seeded"  # marker file in the user's store: DEFAULT was copied once (removing them later sticks)
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _meta(text: str, folder: str) -> dict:
    m = front(text)
    return {"name": folder, "label": m.get("label") or m.get("name") or folder, "description": m.get("description", ""),
            "version": str(m.get("version", "1")), "source": m.get("source", ""), "license": m.get("license", "")}


def library(root: Path = LIBRARY) -> dict[str, dict]:
    """name -> meta + files {relative path: bytes}, read once at startup."""
    out = dict()
    for f in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
        d = f.parent
        files = {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()
                 and "__pycache__" not in p.parts}
        out[d.name] = {**_meta(f.read_text(), d.name), "files": files}
    return out


class _Source:
    """DirSkillSource surface (list / read) over one user's cached skills, for the Skills plugin."""

    def __init__(self, mgr: "UserSkills", user_id: str):
        self.mgr, self.user_id = mgr, user_id

    def list(self) -> list[dict]:
        skills = self.mgr.cache.get(self.user_id, dict())
        return sorted(({**{k: v for k, v in s.items() if k != "files"}, "dir": f"{SKILLS_DIR}/{n}"}
                       for n, s in skills.items()), key=lambda s: s["label"].lower())

    async def read(self, name: str, path: str = "SKILL.md") -> str:
        s = (await self.mgr.load(self.user_id)).get(name)
        if s is None or path not in s["files"]:
            raise FileNotFoundError(f"no {path} in skill {name!r}")
        return s["files"][path].decode(errors="replace")


class UserSkills:
    def __init__(self, root: Path, lib: dict[str, dict] | None = None, legacy=None):
        """root: <data_dir>/skills. legacy: the workspace store v0.15.0 kept skills in (moved here on first load)."""
        self.root, self.store, self.lib = Path(root), legacy, library() if lib is None else lib
        self.cache: dict[str, dict[str, dict]] = dict()  # user -> name -> meta + files
        self.locks: dict[str, asyncio.Lock] = dict()

    @staticmethod
    def sid(user_id: str) -> str:  # the legacy store's pseudo user
        return f"{user_id}.skills"

    def source(self, user_id: str) -> _Source:
        return _Source(self, user_id)

    def _dir(self, user_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
            raise ValueError(f"bad user id {user_id!r}")
        return self.root / user_id

    async def _legacy_files(self, user_id: str, folder: str = "") -> dict[str, bytes]:
        out, sid = dict(), self.sid(user_id)
        try:
            entries = await self.store.list(sid, folder)
        except FileNotFoundError:
            return out
        for e in entries:
            p = posixpath.join(folder, e["name"]) if folder else e["name"]
            if e["is_dir"]:
                out |= {posixpath.join(e["name"], k): v for k, v in (await self._legacy_files(user_id, p)).items()}
            else:
                out[e["name"]] = await self.store.read(sid, p)
        return out

    async def _from_legacy(self, user_id: str) -> bool:
        """Copy skills from the v0.15.0 store to disk, then drop them there. True when the user had some."""
        if self.store is None:
            return False
        try:
            top = await self.store.list(self.sid(user_id), "")
        except Exception:
            return False
        if not top:
            return False
        for e in top:
            if e["is_dir"] and NAME.fullmatch(e["name"]):
                files = await self._legacy_files(user_id, e["name"])
                if "SKILL.md" in files:
                    self._write(user_id, e["name"], files)
        (self._dir(user_id) / SEEDED).write_bytes(b"1")
        for e in top:
            try:
                await self.store.delete(self.sid(user_id), e["name"])
            except Exception:
                pass
        return True

    def _read_all(self, user_id: str) -> dict[str, dict]:
        out = dict()
        for d in sorted(self._dir(user_id).iterdir()):
            if d.is_dir() and NAME.fullmatch(d.name) and (d / "SKILL.md").is_file():
                files = {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*"))
                         if p.is_file() and not p.is_symlink()}
                out[d.name] = {**_meta(files["SKILL.md"].decode(errors="replace"), d.name), "files": files}
        return out

    async def load(self, user_id: str) -> dict[str, dict]:
        """The user's skills (cached); a new user gets DEFAULT first."""
        if user_id in self.cache:
            return self.cache[user_id]
        async with self.locks.setdefault(user_id, asyncio.Lock()):
            if user_id in self.cache:
                return self.cache[user_id]
            d = self._dir(user_id)
            if not (d / SEEDED).exists():
                d.mkdir(parents=True, exist_ok=True)
                if not await self._from_legacy(user_id):
                    for n in DEFAULT:
                        if n in self.lib:
                            self._write(user_id, n, self.lib[n]["files"])
                    (d / SEEDED).write_bytes(b"1")
            self.cache[user_id] = await asyncio.to_thread(self._read_all, user_id)
            return self.cache[user_id]

    def _write(self, user_id: str, name: str, files: dict[str, bytes]) -> None:
        """Replace the skill's folder: written beside it, then swapped in."""
        d = self._dir(user_id)
        tmp, old = d / f".{name}.new", d / f".{name}.old"
        for x in (tmp, old):
            shutil.rmtree(x, ignore_errors=True)
        for p, data in files.items():
            f = tmp / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        if (d / name).exists():
            (d / name).rename(old)
        tmp.rename(d / name)
        shutil.rmtree(old, ignore_errors=True)

    async def add(self, user_id: str, name: str) -> None:
        """Copy a library skill into the user's store (again = update to the library's version). LookupError: unknown."""
        if name not in self.lib:
            raise LookupError(f"no library skill {name!r}")
        await self.load(user_id)
        await asyncio.to_thread(self._write, user_id, name, self.lib[name]["files"])
        self.cache[user_id][name] = {k: v for k, v in self.lib[name].items()}

    async def remove(self, user_id: str, name: str) -> None:
        skills = await self.load(user_id)
        if name not in skills:
            raise LookupError(f"no skill {name!r}")
        await asyncio.to_thread(shutil.rmtree, self._dir(user_id) / name, True)
        del skills[name]

    def version(self, user_id: str) -> str:
        """Hash of the user's cached skills: changes when they add, update or remove one."""
        h = hashlib.sha256()
        for n, s in sorted(self.cache.get(user_id, dict()).items()):
            for p, data in sorted(s["files"].items()):
                h.update(f"{n}/{p}\0".encode() + hashlib.sha256(data).digest())
        return h.hexdigest()[:16]

    def tar(self, user_id: str) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            for n, s in sorted(self.cache.get(user_id, dict()).items()):
                for p, data in sorted(s["files"].items()):
                    info = tarfile.TarInfo(f"{n}/{p}")
                    info.size, info.mode = len(data), 0o755 if p.endswith((".py", ".sh", ".js")) else 0o644
                    t.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    async def to_sandbox(self, box, root_sh, put) -> None:
        """Write the user's skills into the sandbox at SKILLS_DIR when they changed since it last got them.
        root_sh(cmd) runs as root; put(path, data) writes a file as the agent's user. Read-only for the agent."""
        await self.load(box.user_id)
        ver = self.version(box.user_id)
        if getattr(box, "skills_ver", None) == ver:
            return
        tmp = "/tmp/.simp-skills.tar"
        await put(tmp, self.tar(box.user_id))
        d = shlex.quote(SKILLS_DIR)
        code, out = await root_sh(f"mkdir -p {d} && find {d} -mindepth 1 -delete && tar -xf {tmp} -C {d} --no-same-owner "
                                  f"&& chmod -R a+rX,go-w {d} && rm -f {tmp}")
        if code != 0:
            raise RuntimeError(f"could not install skills in the sandbox: {out.strip()[:200]}")
        box.skills_ver = ver

