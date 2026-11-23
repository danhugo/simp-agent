"""Skills: instruction folders (<name>/SKILL.md + scripts) the agent loads only when a task needs them.

Two ways in:
- explicit: the app passes session.prompt(text, skills=["pptx"]); SKILL.md is attached to that turn (no tool call);
- agent-chosen: the prompt lists name + description of each enabled skill; the model calls load_skill(name).
Both put the text in a hidden user message (meta) headed `[Skill: <name> · <path>]`, so compaction can list loaded
skills; the tool result itself is one line (like Claude Code's Skill tool)."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol

from ..agent import AgentTool
from ..agent.compaction import SKILL_HEADER, loaded_skills  # noqa: F401 (re-export)
from ..ai import UserMessage

def front(text: str) -> dict:
    """The `key: value` lines between the leading `---` fences."""
    if not text.startswith("---\n"):
        return dict()
    out = dict()
    for line in text[4:].split("\n---", 1)[0].splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith(" "):
            out[k.strip()] = v.strip().strip('"')
    return out


class SkillSource(Protocol):
    """list() -> [{name, label, description, dir}]; dir is where the folder sits for the agent's shell (sandbox path)."""

    def list(self) -> list[dict]: ...
    async def read(self, name: str, path: str = "SKILL.md") -> str: ...


class DirSkillSource:
    """<root>/<name>/SKILL.md on this machine. sandbox_dir: where the same folders are for the agent's shell."""

    def __init__(self, root: str | Path, sandbox_dir: str | None = None):
        self.root = Path(root).expanduser()
        self.sandbox_dir = sandbox_dir or str(self.root)

    def list(self) -> list[dict]:
        out = list()
        for f in sorted(self.root.glob("*/SKILL.md")) if self.root.is_dir() else []:
            m = front(f.read_text())
            name = m.get("name") or f.parent.name
            out.append({"name": name, "label": m.get("label") or name, "description": m.get("description", ""),
                        "dir": f"{self.sandbox_dir}/{f.parent.name}"})
        return sorted(out, key=lambda s: s["label"].lower())

    async def read(self, name: str, path: str = "SKILL.md") -> str:
        folder = next((self.root / PurePosixPath(s["dir"]).name for s in self.list() if s["name"] == name), None)
        if folder is None:
            raise FileNotFoundError(f"no skill {name!r}")
        return (folder / path).read_text()


def safe_path(path: str) -> str:
    p = PurePosixPath(path or "SKILL.md")
    if p.is_absolute() or ".." in p.parts:
        raise PermissionError(f"path must stay inside the skill folder: {path}")
    return str(p)


class Skills:
    """source: where skills come from. enabled: fn() -> set of names allowed now (None = all), read every turn."""

    name = "skills"

    def __init__(self, source: SkillSource, enabled: Callable[[], set[str]] | None = None):
        self.source, self.enabled = source, enabled

    def available(self) -> list[dict]:
        on = self.enabled() if self.enabled else None
        return [s for s in self.source.list() if on is None or s["name"] in on]

    def setup(self, api, config: dict) -> None:
        api.add_prompt_section(self.name, self.prompt, 6)
        api.register_tool(AgentTool(
            "load_skill", "Load a skill's instructions (SKILL.md), or another file in its folder that SKILL.md names. "
            "Call it before starting a task that a listed skill covers.",
            {"type": "object", "properties": {
                "name": {"type": "string", "description": "skill name from the Skills list"},
                "path": {"type": "string", "description": "file inside the skill folder (default SKILL.md)"}},
             "required": ["name"]},
            self._load))

    def prompt(self, ctx=None) -> str:
        on = self.available()
        if not on:
            return ""
        lines = "\n".join(f"- {s['name']}: {s['description']}" for s in on)
        return ("# Skills\nTested instructions and scripts for common tasks. When a task fits a skill, call "
                "load_skill(name) first and follow it. A skill's folder is read-only: run its scripts by the full path "
                f"it gives, work in your own folder.\n{lines}")

    async def text(self, name: str, path: str = "SKILL.md") -> str:
        """Header + file text, with `scripts/` made absolute (SKILL.md files call them relative to their folder)."""
        s = next((s for s in self.available() if s["name"] == name), None)
        if s is None:
            have = ", ".join(x["name"] for x in self.available()) or "none"
            raise LookupError(f"no enabled skill {name!r} (enabled: {have})")
        path = safe_path(path)
        raw = await self.source.read(name, path)
        if raw.startswith("---\n") and "\n---" in raw[4:]:  # frontmatter is for the catalog, not the model
            raw = raw[4:].split("\n---", 1)[1].lstrip("-").lstrip("\n")
        body = re.sub(r"(?<![\w/.])scripts/", f"{s['dir']}/scripts/", raw)
        return f"[Skill: {name} · {path}]\nFolder: {s['dir']} (read-only)\n\n{body}"

    async def _load(self, args, ctx) -> str:
        path = args.get("path") or "SKILL.md"
        ctx.messages.append(UserMessage(await self.text(args["name"], path), meta=True))
        return f"Launching skill: {args['name']}" + ("" if path == "SKILL.md" else f" ({path})")

    async def before_agent_start(self, payload: dict) -> dict:
        """Explicit picks (session.prompt(..., skills=[...])): attach each SKILL.md to this turn."""
        msgs = [UserMessage(await self.text(n), meta=True) for n in dict.fromkeys(payload.get("skills") or [])]
        return {"messages": msgs}
