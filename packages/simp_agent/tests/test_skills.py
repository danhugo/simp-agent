import pytest

from simp_agent.agent.compaction import CompactionEntry, loaded_skills
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, ToolResultMessage, UserMessage
from simp_agent.plugins import DirSkillSource, Skills
from simp_agent.session import AgentSession
from simp_agent.testing import FakeProvider

DONE = AssistantMessage([TextContent("ok")])


@pytest.fixture
def root(tmp_path):
    for name, desc in (("pptx", "Use when making slides."), ("xlsx", "Use for spreadsheets.")):
        (tmp_path / name / "scripts").mkdir(parents=True)
        (tmp_path / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\n---\nRun `python scripts/x.py out` then ./scripts/y.py.\n")
    (tmp_path / "pptx" / "REFERENCE.md").write_text("more")
    (tmp_path / "secret.txt").write_text("no")
    return tmp_path


def plugin(root, enabled=None):
    return Skills(DirSkillSource(root, "/opt/simp/skills"), enabled)


async def started(p, stream=None):
    s = AgentSession(Model(), [], stream_fn=stream or FakeProvider(DONE), system_prompt="s", plugins=[p])
    await s.start()
    return s


async def test_catalog_lists_only_enabled(root):
    s = await started(plugin(root, lambda: {"xlsx"}))
    text = await s._build_prompt()
    assert "- xlsx: Use for spreadsheets." in text and "pptx" not in text
    assert any(t.name == "load_skill" for t in s.agent.tools)


async def test_no_section_when_none_enabled(root):
    s = await started(plugin(root, lambda: set()))
    assert "Skills" not in await s._build_prompt()


async def test_load_skill_header_and_absolute_scripts(root):
    out = await plugin(root).text("pptx")
    assert out.startswith("[Skill: pptx · SKILL.md]\nFolder: /opt/simp/skills/pptx (read-only)")
    assert "python /opt/simp/skills/pptx/scripts/x.py" in out
    assert "./scripts/y.py" in out  # already relative to something explicit: left alone
    assert "description:" not in out and "---" not in out  # frontmatter is for the catalog only
    assert await plugin(root).text("pptx", "REFERENCE.md") != ""


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd", "scripts/../../secret.txt"])
async def test_load_skill_path_must_stay_inside(root, path):
    with pytest.raises(PermissionError):
        await plugin(root).text("pptx", path)


async def test_load_skill_unknown_or_disabled(root):
    with pytest.raises(LookupError, match="enabled: xlsx"):
        await plugin(root, lambda: {"xlsx"}).text("pptx")


async def test_explicit_pick_attached_before_first_llm_call(root):
    stream = FakeProvider(DONE)
    s = await started(plugin(root), stream)
    await s.prompt("make a deck", skills=["pptx", "pptx"])
    sent = [m for m in stream.messages[0] if isinstance(m, UserMessage)]
    skill = [m for m in sent if m.content.startswith("[Skill: pptx · SKILL.md]")]
    assert len(skill) == 1 and skill[0].meta  # hidden from the chat UI
    sent = [m.content for m in sent]
    assert "make a deck" in sent


def test_loaded_skills_from_tool_results_and_picks():
    msgs = [UserMessage("[Skill: pptx · SKILL.md]\nx"), UserMessage("hi [Skill: no · x]"),
            AssistantMessage([ToolCall("c", "load_skill", {"name": "xlsx"})], stop_reason="tool_use"),
            ToolResultMessage("c", "load_skill", "[Skill: xlsx · SKILL.md]\ny")]
    assert loaded_skills(msgs) == ["pptx", "xlsx"]


async def test_compaction_keeps_short_note_of_loaded_skills():
    stream = FakeProvider(AssistantMessage([TextContent("SUM")]), DONE)
    s = AgentSession(Model(context_window=10000), [], stream_fn=stream, system_prompt="s")
    s.compaction.reserve_tokens, s.compaction.keep_recent_tokens = 1000, 5000
    s.agent.messages = [UserMessage("[Skill: pptx · SKILL.md]\n" + "x" * 16000),
                        AssistantMessage([TextContent("y" * 16000)]),
                        UserMessage("new" + "z" * 16000),
                        AssistantMessage([TextContent("w" * 16000)], usage={"input": 9000, "output": 100})]
    await s.prompt("next")
    entry = next(m for m in s.messages if isinstance(m, CompactionEntry))
    assert entry.skills == ["pptx"] and "<loaded-skills>\npptx\n</loaded-skills>" in entry.summary


async def test_load_skill_tool_result_is_one_line_and_text_follows_as_hidden_message(root):
    call = AssistantMessage([ToolCall("c1", "load_skill", {"name": "pptx"})], stop_reason="tool_use")
    stream = FakeProvider(call, DONE)
    s = await started(plugin(root), stream)
    await s.prompt("make a deck")
    sent = stream.messages[1]
    result = next(m for m in sent if isinstance(m, ToolResultMessage))
    assert result.content == "Launching skill: pptx"
    after = sent[sent.index(result) + 1]
    assert isinstance(after, UserMessage) and after.meta and after.content.startswith("[Skill: pptx · SKILL.md]")
    assert loaded_skills(sent) == ["pptx"]
