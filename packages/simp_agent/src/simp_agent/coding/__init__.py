"""Coding layer: file/shell tools, the system prompt, and project context files (AGENTS.md / CLAUDE.md)."""

from __future__ import annotations

import datetime
import os

from .tools import TOOLS, make_tools

CONTEXT_FILES = ["AGENTS.override.md", "AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD"]  # pi resource-loader.ts


async def load_context_file(env, cwd: str) -> tuple[str, str] | None:
    """First context file found in cwd -> (path, text). Reads through env, so it works on any ExecutionEnv.
    ponytail: cwd only, no parent dirs or ~/.pi-style global file."""
    for name in CONTEXT_FILES:
        path = os.path.join(cwd, name)
        try:
            return path, await env.read_file(path)
        except OSError:
            continue
    return None


def system_prompt(tools: list, cwd: str, context: tuple[str, str] | None = None) -> str:
    tool_list = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    out = (
        "You are an expert coding assistant. You help the user by reading files, running commands, "
        "editing code, and writing new files.\n\n"
        f"Available tools:\n{tool_list}\n\n"
        "Be concise. Use read before edit. Paths are relative to the working directory.\n\n"
    )
    if context:
        out += f"# Project Context\n\n## {context[0]}\n\n{context[1]}\n\n"
    return out + f"Current date: {datetime.date.today()}\nCurrent working directory: {cwd}"


__all__ = ["TOOLS", "make_tools", "CONTEXT_FILES", "load_context_file", "system_prompt"]
