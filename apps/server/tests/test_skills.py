import io

import pytest

from simp_server import skills
from simp_server.user_skills import LIBRARY, UserSkills, library
from simp_server.workspace import LocalStore


def store_of(tmp_path):
    return LocalStore({"data_dir": str(tmp_path)})  # stands in for R2: <workspaces>/<user>.skills/...


def mgr(tmp_path, lib=None):
    return UserSkills(store_of(tmp_path), lib, disk=tmp_path / "skills")


def one(name="a", body=b"hi", extra=None):
    files = {"SKILL.md": b"---\nname: " + name.encode() + b"\n---\n" + body, **(extra or {})}
    from simp_server.user_skills import files_hash
    return {name: {"name": name, "label": name.upper(), "description": "d", "version": "1", "source": "", "license": "",
                   "files": files, "hash": files_hash(files)}}


def test_library_skills_have_label_and_description():
    got = library()
    assert set(got) >= {"pptx", "docx", "xlsx", "pdf"}
    assert got["pptx"]["label"] == "PowerPoint" and got["pdf"]["description"]
    for n, s in got.items():
        assert s["description"] and "SKILL.md" in s["files"], n
        assert "Claude" not in s["files"]["SKILL.md"].decode(), n


async def test_new_user_gets_office_skills_with_sandbox_paths(tmp_path):
    m = mgr(tmp_path)
    mine = await m.load("u1")
    assert set(mine) == {"docx", "pdf", "pptx", "xlsx"}
    src = m.source("u1")
    assert next(s for s in src.list() if s["name"] == "pptx")["dir"] == "/opt/simp/skills/pptx"
    text = await skills.plugin(src, None).text("xlsx")
    assert text.startswith("[Skill: xlsx · SKILL.md]")
    assert 'sys.path.insert(0, "/opt/simp/skills/xlsx/scripts")' in text and "python scripts/" not in text
    got = await store_of(tmp_path).list("u1.skills", "")
    assert {e["name"] for e in got} == {"skills.json", "docx.tar.gz", "pdf.tar.gz", "pptx.tar.gz", "xlsx.tar.gz"}  # in R2
    assert not (tmp_path / "skills" / "u1").exists()  # nothing per user on the server's disk
    assert m.blobs == {}  # library copies are not held twice


async def test_add_remove_stick_across_restarts(tmp_path):
    lib = one(extra={"scripts/x.py": b"print(1)"})
    m = mgr(tmp_path, lib)
    assert await m.load("u1") == {}  # DEFAULT not in this library: nothing
    await m.add("u1", "a")
    v1 = m.version("u1")
    await m.remove("u1", "a")
    assert m.version("u1") != v1
    with pytest.raises(LookupError):
        await m.add("u1", "nope")
    await m.add("u1", "a")
    m2 = mgr(tmp_path, lib)  # a new server process reads the store
    assert set(await m2.load("u1")) == {"a"} and (await m2.source("u1").read("a", "scripts/x.py")) == "print(1)"
    await m2.remove("u1", "a")
    assert await mgr(tmp_path, lib).load("u1") == {}  # removal sticks; no re-seeding



async def test_to_sandbox_only_when_changed(tmp_path):
    m = mgr(tmp_path)
    await m.load("u1")
    cmds, puts = list(), list()

    class Box:
        user_id, skills_ver = "u1", None

    async def root_sh(c):
        cmds.append(c)
        return 0, ""

    async def put(p, data):
        puts.append((p, data))

    box = Box()
    await m.to_sandbox(box, root_sh, put)
    await m.to_sandbox(box, root_sh, put)  # unchanged: nothing sent
    assert len(cmds) == 1 and "/opt/simp/skills" in cmds[0] and "go-w" in cmds[0]
    import tarfile
    t = tarfile.open(fileobj=io.BytesIO(puts[0][1]))
    assert "xlsx/scripts/xlsx_kit.py" in t.getnames()
    await m.remove("u1", "pdf")
    await m.to_sandbox(box, root_sh, put)
    assert len(cmds) == 2
    assert LIBRARY.name == "skill_library"


async def test_v0_15_skills_move_from_the_workspace_store_once(tmp_path):
    store = store_of(tmp_path)
    await store.write("u1.skills", ".seeded", b"1")
    await store.write("u1.skills", "a/SKILL.md", b"---\nname: a\n---\nhi")
    await store.write("u1.skills", "a/scripts/x.py", b"print(1)")
    m = UserSkills(store, one("docx"), disk=tmp_path / "skills")
    got = await m.load("u1")
    assert set(got) == {"a"}  # no re-seeding
    assert (await m.source("u1").read("a", "scripts/x.py")) == "print(1)"
    assert {e["name"] for e in await store.list("u1.skills", "")} == {"skills.json", "a.tar.gz"}  # per-file copies gone
    assert set(await UserSkills(store, {}, disk=tmp_path / "skills").load("u1")) == {"a"}
    with pytest.raises(ValueError):
        await m.load("../x")


async def test_disk_skills_move_to_r2_once(tmp_path):
    d = tmp_path / "skills" / "u1" / "b" / "scripts"
    d.mkdir(parents=True)
    (d.parent / "SKILL.md").write_bytes(b"---\nname: b\n---\nmine")
    (d / "y.py").write_bytes(b"print(2)")
    m = mgr(tmp_path, one("docx"))
    assert set(await m.load("u1")) == {"b"}  # what they had, not DEFAULT
    assert not (tmp_path / "skills" / "u1").exists()  # moved off the server's disk
    fresh = mgr(tmp_path, {})  # another server process: one GET of the catalogue, one of the tar
    assert (await fresh.source("u1").read("b", "scripts/y.py")) == "print(2)"


async def test_a_skill_the_library_changed_since_comes_from_its_tar(tmp_path):
    m = mgr(tmp_path, one("a", b"v1"))
    await m.add("u1", "a")
    newer = mgr(tmp_path, one("a", b"v2"))  # the server updated its library; the user has not pressed Update
    assert (await newer.source("u1").read("a")).endswith("v1")
    assert len(newer.blobs) == 1  # their copy, cached; the library's v2 stays the library's


async def test_add_and_remove_push_to_a_running_sandbox(tmp_path):
    m = mgr(tmp_path, one("a"))
    pushed = []

    async def push(uid):
        pushed.append(uid)
    m.push = push
    await m.load("u1")
    await m.add("u1", "a")
    await m.remove("u1", "a")
    assert pushed == ["u1", "u1"]


async def test_parallel_tool_calls_install_skills_once(tmp_path):
    """Read-only tool calls run at once and each asks for the skills first: one install, the others wait."""
    import asyncio
    m = mgr(tmp_path)
    await m.load("u1")
    cmds = list()

    class Box:
        user_id, skills_ver = "u1", None

    async def root_sh(c):
        cmds.append(c)
        await asyncio.sleep(0.05)  # untarring takes a while: the other calls arrive meanwhile
        return 0, ""

    async def put(p, data):
        await asyncio.sleep(0.01)

    box = Box()
    await asyncio.gather(*(m.to_sandbox(box, root_sh, put) for _ in range(3)))
    assert len(cmds) == 1
