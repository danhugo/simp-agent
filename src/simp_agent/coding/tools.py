"""Coding layer: read / write / edit / bash tools. Paths are relative to ctx.cwd; all IO goes through ctx.env."""

from __future__ import annotations

import os

from .agent import AgentTool

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


async def bash(args: dict, ctx) -> str:
    code, out = await ctx.env.exec(args["command"], ctx.cwd, args.get("timeout", 120), ctx.cancel, ctx.on_update)
    return _truncate(f"{out}\n[exit code: {code}]")


TOOLS = [
    AgentTool("read", "Read a text file. Output has line numbers. Use offset/limit for big files.",
              _obj({"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["path"]), read),
    AgentTool("write", "Create or overwrite a file. Makes parent dirs.",
              _obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]), write),
    AgentTool("edit", "Replace old_text with new_text in a file. old_text must match exactly once.",
              _obj({"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
                   ["path", "old_text", "new_text"]), edit),
    AgentTool("bash", "Run a shell command in cwd. Returns stdout+stderr and exit code.",
              _obj({"command": {"type": "string"}, "timeout": {"type": "number"}}, ["command"]), bash),
]
