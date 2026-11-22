"""Skills: instruction folders (SKILL.md + scripts) baked into the sandbox template at /opt/simp/skills.

The core plugin (simp_agent.plugins.Skills) lists the enabled ones in the prompt and loads SKILL.md on demand
(load_skill) or when the user picks one. Text is read here on the server; scripts run in the sandbox.
Every skill starts enabled; a user turns one off on the Crafts page (store.skill_off)."""

from pathlib import Path

from simp_agent.plugins import DirSkillSource, Skills

from .sandboxes.toolset import SKILLS_DIR

ROOT = Path(__file__).parents[2] / "skills"  # apps/server/skills


def source(root: Path = ROOT) -> DirSkillSource:
    return DirSkillSource(root, SKILLS_DIR)


def plugin(src: DirSkillSource, enabled) -> Skills:
    return Skills(src, enabled)
