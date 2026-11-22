"""Skills: instruction folders (SKILL.md + scripts) baked into the sandbox template at /opt/simp/skills.

Every skill starts enabled; a user turns one off on the Crafts page (store.skill_off). The prompt names only the
enabled ones with their SKILL.md path, so the agent reads the full instructions only when a task needs them."""

from pathlib import Path

from .sandboxes.toolset import SKILLS_DIR

ROOT = Path(__file__).parents[2] / "skills"  # apps/server/skills


def _front(text: str) -> dict:
    """The `key: value` lines between the leading `---` fences."""
    if not text.startswith("---\n"):
        return dict()
    head = text[4:].split("\n---", 1)[0]
    out = dict()
    for line in head.splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith(" "):
            out[k.strip()] = v.strip().strip('"')
    return out


def load(root: Path = ROOT) -> list[dict]:
    """[{name, label, description}] for each <root>/<name>/SKILL.md, sorted by label."""
    out = []
    for f in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
        m = _front(f.read_text())
        name = m.get("name") or f.parent.name
        out.append({"name": name, "label": m.get("label") or name, "description": m.get("description", "")})
    return sorted(out, key=lambda s: s["label"].lower())


def prompt_section(skills: list[dict], off: set[str]) -> str:
    on = [s for s in skills if s["name"] not in off]
    if not on:
        return ""
    lines = "\n".join(f"- {s['name']}: {s['description']} Read {SKILLS_DIR}/{s['name']}/SKILL.md" for s in on)
    return ("Skills: tested instructions and scripts for common file tasks. Before starting a task a skill covers, "
            "read its SKILL.md once and follow it. Its folder is read-only: run its scripts by full path "
            f"(python {SKILLS_DIR}/<skill>/scripts/x.py) from your working folder, and write output there.\n{lines}")
