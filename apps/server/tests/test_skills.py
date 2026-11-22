from simp_server import skills


def test_bundled_skills_have_label_and_description():
    got = {s["name"]: s for s in skills.load()}
    assert set(got) >= {"pptx", "docx", "xlsx", "pdf"}
    assert got["pptx"]["label"] == "PowerPoint" and got["pdf"]["description"]
    assert all("Claude" not in (skills.ROOT / n / "SKILL.md").read_text() for n in got)


def test_prompt_lists_only_enabled_skills_with_their_path():
    s = skills.load()
    text = skills.prompt_section(s, {"docx"})
    assert "/opt/simp/skills/pptx/SKILL.md" in text and "docx" not in text
    assert skills.prompt_section(s, {x["name"] for x in s}) == ""


def test_load_reads_front_matter(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "SKILL.md").write_text('---\nname: a\nlabel: Alpha\ndescription: "Does a."\n---\nbody')
    assert skills.load(tmp_path) == [{"name": "a", "label": "Alpha", "description": "Does a."}]
    assert skills.load(tmp_path / "missing") == []
