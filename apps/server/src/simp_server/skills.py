"""Skills: instruction folders (SKILL.md + scripts). Each user has their own (user_skills.py); the core plugin
(simp_agent.plugins.Skills) lists the enabled ones in the prompt and loads SKILL.md on demand (load_skill) or when the
user picks one. Text is read on the server; scripts run in the sandbox at SKILLS_DIR.
Every skill starts enabled; a user turns one off on the Crafts page (store.skill_off)."""

from simp_agent.plugins import Skills

from .sandboxes.toolset import SKILLS_DIR  # noqa: F401  (re-exported)


def plugin(src, enabled) -> Skills:
    return Skills(src, enabled)
