"""Skills per user: the server's library (apps/server/skill_library) is a catalog; adding a skill copies its folder into
the user's own skill store. The agent only sees that store.

Storage: the workspace store under the pseudo id "<user_id>.skills" (local: <workspaces>/<id>.skills/, S3:
users/<id>.skills/), one tar per skill (<name>.tar): loading a user is one GET per skill, not one per file: beside the workspace, so not in the Files panel, the quota or the sandbox's /work.
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
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from simp_agent.plugins.skills import front

from .sandboxes.toolset import SKILLS_DIR

LIBRARY = Path(__file__).parents[2] / "skill_library"  # apps/server/skill_library
DEFAULT = ("docx", "pdf", "pptx", "xlsx")
SEEDED = ".seeded"  # marker file in the user's store: DEFAULT was copied once (removing them later sticks)
MAX_SKILL_BYTES = 5 * 1024 * 1024  # an imported skill folder, all files
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
    def __init__(self, store, lib: dict[str, dict] | None = None):
        self.store, self.lib = store, library() if lib is None else lib
        self.cache: dict[str, dict[str, dict]] = dict()  # user -> name -> meta + files
        self.locks: dict[str, asyncio.Lock] = dict()

    @staticmethod
    def sid(user_id: str) -> str:
        return f"{user_id}.skills"

    def source(self, user_id: str) -> _Source:
        return _Source(self, user_id)

    async def _files(self, user_id: str, folder: str = "") -> dict[str, bytes]:
        """Every file under folder in the user's store (relative paths)."""
        out, sid = dict(), self.sid(user_id)
        try:
            entries = await self.store.list(sid, folder)
        except FileNotFoundError:
            return out
        for e in entries:
            p = posixpath.join(folder, e["name"]) if folder else e["name"]
            if e["is_dir"]:
                out |= {posixpath.join(e["name"], k): v for k, v in (await self._files(user_id, p)).items()}
            else:
                out[e["name"]] = await self.store.read(sid, p)
        return out

    async def load(self, user_id: str) -> dict[str, dict]:
        """The user's skills (cached); a new user gets DEFAULT first."""
        if user_id in self.cache:
            return self.cache[user_id]
        async with self.locks.setdefault(user_id, asyncio.Lock()):
            if user_id in self.cache:
                return self.cache[user_id]
            sid, skills = self.sid(user_id), dict()
            try:
                top = {e["name"]: e for e in await self.store.list(sid, "")}
            except FileNotFoundError:
                top = dict()
            if SEEDED not in top:
                new = [n for n in DEFAULT if n in self.lib]
                await asyncio.gather(*(self._write(user_id, n, self.lib[n]["files"]) for n in new))
                top |= {f"{n}.tar": {"name": f"{n}.tar", "is_dir": False} for n in new}
                await self.store.write(sid, SEEDED, b"1")
            async def one(n: str, e: dict) -> None:
                if e["is_dir"] and NAME.fullmatch(n):  # stored file by file (v0.15.0): read once, keep as one tar
                    files = await self._files(user_id, n)
                    if "SKILL.md" in files:
                        await self._write(user_id, n, files)
                elif n.endswith(".tar") and NAME.fullmatch(n[:-4]):
                    n, files = n[:-4], _untar(await self.store.read(sid, n))
                else:
                    return
                if "SKILL.md" in files:
                    skills[n] = {**_meta(files["SKILL.md"].decode(errors="replace"), n), "files": files}
            await asyncio.gather(*(one(n, e) for n, e in top.items()))
            self.cache[user_id] = skills
            return skills

    async def _write(self, user_id: str, name: str, files: dict[str, bytes]) -> None:
        sid = self.sid(user_id)
        await self.store.write(sid, f"{name}.tar", _tar({f"{name}/{p}": d for p, d in files.items()}, name))
        try:  # an old file-by-file copy
            await self.store.delete(sid, name)
        except (FileNotFoundError, PermissionError):
            pass

    async def add(self, user_id: str, name: str) -> None:
        """Copy a library skill into the user's store (again = update to the library's version). LookupError: unknown."""
        if name not in self.lib:
            raise LookupError(f"no library skill {name!r}")
        await self.load(user_id)
        await self._write(user_id, name, self.lib[name]["files"])
        self.cache[user_id][name] = {k: v for k, v in self.lib[name].items()}

    async def add_files(self, user_id: str, name: str, files: dict[str, bytes]) -> None:
        """Import a skill folder from elsewhere (a zip). ValueError: not a skill / too big / bad paths."""
        if not NAME.fullmatch(name):
            raise ValueError("skill name: lowercase letters, digits and '-'")
        if "SKILL.md" not in files:
            raise ValueError("a skill needs SKILL.md at its top")
        if sum(len(v) for v in files.values()) > MAX_SKILL_BYTES:
            raise ValueError("skill too big (5 MB max)")
        for p in files:
            pp = PurePosixPath(p)
            if pp.is_absolute() or ".." in pp.parts:
                raise ValueError(f"bad path in skill: {p}")
        await self.load(user_id)
        await self._write(user_id, name, files)
        self.cache[user_id][name] = {**_meta(files["SKILL.md"].decode(errors="replace"), name), "files": files}

    async def remove(self, user_id: str, name: str) -> None:
        skills = await self.load(user_id)
        if name not in skills:
            raise LookupError(f"no skill {name!r}")
        for key in (f"{name}.tar", name):
            try:
                await self.store.delete(self.sid(user_id), key)
            except FileNotFoundError:
                pass
        del skills[name]

    async def zip(self, user_id: str, name: str) -> bytes:
        """A skill as <name>/... in a zip: the user's copy, else the library's."""
        s = (await self.load(user_id)).get(name) or self.lib.get(name)
        if s is None:
            raise LookupError(f"no skill {name!r}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p, data in sorted(s["files"].items()):
                z.writestr(f"{name}/{p}", data)
        return buf.getvalue()

    def version(self, user_id: str) -> str:
        """Hash of the user's cached skills: changes when they add, update or remove one."""
        h = hashlib.sha256()
        for n, s in sorted(self.cache.get(user_id, dict()).items()):
            for p, data in sorted(s["files"].items()):
                h.update(f"{n}/{p}\0".encode() + hashlib.sha256(data).digest())
        return h.hexdigest()[:16]

    def tar(self, user_id: str) -> bytes:
        return _tar({f"{n}/{p}": d for n, s in self.cache.get(user_id, dict()).items() for p, d in s["files"].items()})

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


def unzip_skill(data: bytes) -> tuple[str, dict[str, bytes]]:
    """(name, files) from a zip holding one skill: <name>/SKILL.md... or SKILL.md at the top (name from its front
    matter). ValueError when it isn't one."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("not a zip file") from None
    names = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n]
    if sum(z.getinfo(n).file_size for n in names) > MAX_SKILL_BYTES:
        raise ValueError("skill too big (5 MB max)")
    tops, top = {n.split("/", 1)[0] for n in names if "/" in n}, ""
    if "SKILL.md" not in names and len(tops) == 1 and f"{next(iter(tops))}/SKILL.md" in names:
        top = next(iter(tops))
        files = {n[len(top) + 1:]: z.read(n) for n in names if n.startswith(top + "/")}
    else:
        files = {n: z.read(n) for n in names}
    if "SKILL.md" not in files:
        raise ValueError("no SKILL.md in the zip")
    name = str(front(files["SKILL.md"].decode(errors="replace")).get("name") or top).strip().lower()
    name = re.sub(r"[^a-z0-9-]+", "-", name).strip("-")[:64]
    if not NAME.fullmatch(name or ""):
        raise ValueError("the skill needs a name (front matter `name:`)")
    return name, files


def _tar(files: dict[str, bytes], strip: str = "") -> bytes:
    """files {path: bytes} as a tar; strip: drop that leading folder (a skill's own tar holds paths inside it)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for p, data in sorted(files.items()):
            info = tarfile.TarInfo(p[len(strip) + 1:] if strip else p)
            info.size, info.mode = len(data), 0o755 if p.endswith((".py", ".sh", ".js")) else 0o644
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _untar(data: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        return {m.name: t.extractfile(m).read() for m in t.getmembers() if m.isfile()
                and not PurePosixPath(m.name).is_absolute() and ".." not in PurePosixPath(m.name).parts}
