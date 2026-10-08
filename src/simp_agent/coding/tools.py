"""Coding layer: read / write / edit / bash tools. Paths are relative to ctx.cwd; all IO goes through ctx.env."""

from __future__ import annotations

import math
import os
import time

from ..agent import AgentTool

MAX_LINES = 2000
MAX_BYTES = 50_000


def _truncate(text: str) -> str:
    if len(text) <= MAX_BYTES:
        return text
    return text[:MAX_BYTES] + f"\n[truncated: {len(text) - MAX_BYTES} more chars]"


def _obj(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _path(ctx, path: str) -> str:
    return os.path.join(ctx.cwd, path)  # absolute paths stay as is


async def read(args: dict, ctx) -> str:
    lines = (await ctx.env.read_file(_path(ctx, args["path"]))).splitlines()
    start = max(args.get("offset", 1), 1) - 1
    end = start + args.get("limit", MAX_LINES)
    out = "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines[start:end], start))
    if end < len(lines):
        out += f"\n[{len(lines) - end} more lines; use offset={end + 1}]"
    return _truncate(out)


async def write(args: dict, ctx) -> str:
    await ctx.env.write_file(_path(ctx, args["path"]), args["content"])
    return f"Wrote {len(args['content'])} chars to {args['path']}"


async def edit(args: dict, ctx) -> str:
    p = _path(ctx, args["path"])
    text = await ctx.env.read_file(p)
    n = text.count(args["old_text"])
    if n != 1:
        raise ValueError(f"old_text must match exactly once in {args['path']}, found {n} matches")
    await ctx.env.write_file(p, text.replace(args["old_text"], args["new_text"]))
    return f"Edited {args['path']}"


def _tail(text: str) -> str:  # bash: the end of the output matters most
    if len(text) <= MAX_BYTES:
        return text
    return f"[truncated: first {len(text) - MAX_BYTES} chars dropped]\n" + text[-MAX_BYTES:]


def _elapsed(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}m{sec:02d}s" if m else f"{sec}s"


def make_bash(max_timeout_s: float | None = None):
    """No default timeout (pi bash.ts). max_timeout_s: the host's cap; a bigger or missing timeout is clamped to it."""

    async def bash(args: dict, ctx) -> str:
        timeout = args.get("timeout")
        if timeout is not None and not (math.isfinite(timeout) and timeout > 0):
            raise ValueError(f"timeout must be a positive number of seconds, got {timeout}")
        if max_timeout_s is not None:
            timeout = min(timeout or max_timeout_s, max_timeout_s)
        start = time.monotonic()
        code, out = await ctx.env.exec(args["command"], ctx.cwd, timeout, ctx.cancel, ctx.on_update)
        if code is not None:
            return _tail(f"{out}\n[exit code: {code}]")
        if ctx.cancel.is_set():
            return _tail(f"{out}\n[Command interrupted by the user after {_elapsed(time.monotonic() - start)}]")
        return _tail(f"{out}\n[Command timed out after {timeout:g} seconds]")

    return bash


def _p(type_: str, description: str) -> dict:
    return {"type": type_, "description": description}


def make_tools(bash_max_timeout_s: float | None = None) -> list:
    return [
        AgentTool("read", "Read a text file. Output has line numbers. Use offset/limit for big files.",
                  _obj({"path": _p("string", "File path, relative to cwd or absolute"),
                        "offset": _p("integer", "First line to read, 1-based (default 1)"),
                        "limit": _p("integer", f"Max lines to read (default {MAX_LINES})")}, ["path"]), read),
        AgentTool("write", "Create or overwrite a file. Makes parent dirs.",
                  _obj({"path": _p("string", "File path, relative to cwd or absolute"),
                        "content": _p("string", "Full new file content")}, ["path", "content"]), write),
        AgentTool("edit", "Replace old_text with new_text in a file. old_text must match exactly once.",
                  _obj({"path": _p("string", "File path, relative to cwd or absolute"),
                        "old_text": _p("string", "Exact text to replace; must match exactly once"),
                        "new_text": _p("string", "Replacement text")}, ["path", "old_text", "new_text"]), edit),
        AgentTool("bash", "Run a shell command in cwd. Returns stdout+stderr (the tail if long) and exit code. "
                          "Optional timeout in seconds; no timeout by default.",
                  _obj({"command": _p("string", "Shell command to run"),
                        "timeout": _p("number", "Timeout in seconds (optional, no default timeout)")}, ["command"]),
                  make_bash(bash_max_timeout_s)),
    ]


TOOLS = make_tools()

