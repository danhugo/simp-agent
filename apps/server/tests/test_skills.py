from simp_server import skills


def test_bundled_skills_have_label_and_description():
    got = {s["name"]: s for s in skills.source().list()}
    assert set(got) >= {"pptx", "docx", "xlsx", "pdf"}
    assert got["pptx"]["label"] == "PowerPoint" and got["pdf"]["description"]
    assert got["pptx"]["dir"] == "/opt/simp/skills/pptx"
    assert all("Claude" not in (skills.ROOT / n / "SKILL.md").read_text() for n in got)


async def test_bundled_skill_scripts_get_sandbox_paths():
    """SKILL.md calls scripts relative to its folder; the agent works in /work, so load_skill makes them absolute."""
    text = await skills.plugin(skills.source(), None).text("xlsx")
    assert text.startswith("[Skill: xlsx · SKILL.md]")
    assert "python /opt/simp/skills/xlsx/scripts/recalc.py" in text and "python scripts/" not in text
