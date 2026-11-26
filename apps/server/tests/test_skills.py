import io
import zipfile

import pytest

from simp_server import skills
from simp_server.user_skills import LIBRARY, UserSkills, library, unzip_skill
from simp_server.workspace import LocalStore


def mgr(tmp_path, lib=None):
    return UserSkills(LocalStore({"data_dir": str(tmp_path)}), lib)


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
    assert "python /opt/simp/skills/xlsx/scripts/recalc.py" in text and "python scripts/" not in text
    assert (tmp_path / "workspaces" / "u1.skills" / "xlsx.tar").exists()  # one object per skill, beside the workspace


async def test_add_remove_stick_across_restarts(tmp_path):
    lib = {"a": {"name": "a", "label": "A", "description": "d", "version": "1", "source": "", "license": "",
                 "files": {"SKILL.md": b"---\nname: a\n---\nhi", "scripts/x.py": b"print(1)"}}}
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


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


async def test_import_zip_and_download(tmp_path):
    m = mgr(tmp_path, {})
    name, files = unzip_skill(zipped({"my-skill/SKILL.md": "---\nname: My Skill\n---\nbody", "my-skill/a.txt": "x"}))
    assert name == "my-skill" and set(files) == {"SKILL.md", "a.txt"}
    await m.add_files("u1", name, files)
    z = zipfile.ZipFile(io.BytesIO(await m.zip("u1", "my-skill")))
    assert sorted(z.namelist()) == ["my-skill/SKILL.md", "my-skill/a.txt"]
    for bad in (zipped({"x.txt": "no skill"}), b"not a zip"):
        with pytest.raises(ValueError):
            unzip_skill(bad)
    with pytest.raises(ValueError):
        await m.add_files("u1", "evil", {"SKILL.md": b"x", "../up.txt": b"x"})


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
    names = zipfile.ZipFile  # noqa
    import tarfile
    t = tarfile.open(fileobj=io.BytesIO(puts[0][1]))
    assert "xlsx/scripts/recalc.py" in t.getnames()
    await m.remove("u1", "pdf")
    await m.to_sandbox(box, root_sh, put)
    assert len(cmds) == 2
    assert LIBRARY.name == "skill_library"


async def test_old_file_by_file_copy_becomes_one_tar(tmp_path):
    store = LocalStore({"data_dir": str(tmp_path)})
    await store.write("u1.skills", ".seeded", b"1")
    await store.write("u1.skills", "a/SKILL.md", b"---\nname: a\n---\nhi")
    await store.write("u1.skills", "a/scripts/x.py", b"print(1)")
    m = UserSkills(store, {})
    assert set((await m.load("u1"))["a"]["files"]) == {"SKILL.md", "scripts/x.py"}
    assert (tmp_path / "workspaces" / "u1.skills" / "a.tar").exists() and not (tmp_path / "workspaces" / "u1.skills" / "a").exists()
    assert set((await UserSkills(store, {}).load("u1"))["a"]["files"]) == {"SKILL.md", "scripts/x.py"}
