"""Coding layer: file/shell tools, the system prompt, and project context files (AGENTS.md / CLAUDE.md)."""

from __future__ import annotations

import datetime
import os
import re
import zoneinfo

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


def clean_locale(locale, timezone) -> tuple[str | None, str | None]:
    """Client-supplied values go into the prompt: keep only a BCP-47-ish tag and a real zoneinfo name."""
    if not (isinstance(locale, str) and len(locale) <= 35 and re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", locale)):
        locale = None
    try:
        zoneinfo.ZoneInfo(timezone) if isinstance(timezone, str) and 0 < len(timezone) <= 64 else 1 / 0
    except Exception:
        timezone = None
    return locale, timezone


def clean_location(location) -> str | None:
    """Client-supplied {lat, lon} (or a stored "lat,lon" string) -> "lat,lon" rounded to 1 decimal (~10 km), else None."""
    try:
        if isinstance(location, str):
            lat, lon = (float(x) for x in location.split(","))
        else:
            lat, lon = location["lat"], location["lon"]
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
                return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):  # NaN fails these too
            return None
        return f"{round(lat, 1)},{round(lon, 1)}"
    except Exception:
        return None


def system_prompt(tools: list, cwd: str, context: tuple[str, str] | None = None,
                  locale: str | None = None, timezone: str | None = None, location=None) -> str:
    # tools are described to the model in the request's tool schemas, so they are not repeated here
    out = (
        "You are Simp, a friendly and helpful agent that helps the user get anything done.\n\n"
        "Be concise. Use tools that interact with the environment (files, shell) only when the request needs them.\n\n"
    )
    if context:
        out += f"# Project Context\n\n## {context[0]}\n\n{context[1]}\n\n"
    locale, timezone = clean_locale(locale, timezone)
    if timezone:
        out += f"User timezone: {timezone}\n"
    if location := clean_location(location):
        out += f"User location (approx., shared by the user): {location.replace(',', ', ')}\n"
    today = datetime.datetime.now(zoneinfo.ZoneInfo(timezone)).date() if timezone else datetime.date.today()
    return out + f"Current date: {today}\nCurrent working directory: {cwd}"


__all__ = ["TOOLS", "make_tools", "CONTEXT_FILES", "load_context_file", "system_prompt", "clean_locale", "clean_location"]
