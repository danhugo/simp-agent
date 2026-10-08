"""Shared output truncation (pi truncate.ts): keep whole lines under both a line and a byte limit."""

from __future__ import annotations

MAX_LINES = 2000
MAX_BYTES = 50 * 1024


def _cut(lines: list, max_lines: int, max_bytes: int) -> list:
    kept, size = [], 0
    for line in lines[:max_lines]:
        size += len(line.encode()) + (1 if kept else 0)
        if size > max_bytes:
            break
        kept.append(line)
    return kept


def _info(text: str, kept: list) -> dict:
    lines = text.split("\n")
    return {"truncated": len(kept) < len(lines), "total_lines": len(lines),
            "total_bytes": len(text.encode()), "kept_lines": len(kept)}


def truncate_head(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> tuple[str, dict]:
    """Keep the first lines (read, ls, grep, find)."""
    kept = _cut(text.split("\n"), max_lines, max_bytes)
    return "\n".join(kept), _info(text, kept)


def truncate_tail(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> tuple[str, dict]:
    """Keep the last lines (bash: the end of the output matters most)."""
    kept = _cut(text.split("\n")[::-1], max_lines, max_bytes)[::-1]
    return "\n".join(kept), _info(text, kept)


def head(text: str) -> str:
    out, info = truncate_head(text)
    if info["truncated"] and not info["kept_lines"]:
        return f"[First line exceeds {MAX_BYTES // 1024}KB limit; use bash with head -c to read part of it]"
    if info["truncated"]:
        out += f"\n[Output truncated: showing first {info['kept_lines']} of {info['total_lines']} lines]"
    return out


def tail(text: str) -> str:
    out, info = truncate_tail(text)
    if info["truncated"]:
        out = f"[Output truncated: showing last {info['kept_lines']} of {info['total_lines']} lines]\n" + out
    return out
