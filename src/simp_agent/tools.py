"""Coding layer: read / write / edit / bash tools. Paths are relative to cwd."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .agent import AgentTool

MAX_LINES = 2000
MAX_BYTES = 50_000


def _truncate(text: str) -> str:
    if len(text) <= MAX_BYTES:
        return text
    return text[:MAX_BYTES] + f"\n[truncated: {len(text) - MAX_BYTES} more chars]"


def _obj(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


async def read(args: dict, cancel: asyncio.Event) -> str:
    lines = Path(args["path"]).read_text().splitlines()
    start = max(args.get("offset", 1), 1) - 1
    end = start + args.get("limit", MAX_LINES)
    out = "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines[start:end], start))
    if end < len(lines):
        out += f"\n[{len(lines) - end} more lines; use offset={end + 1}]"
    return _truncate(out)


async def write(args: dict, cancel: asyncio.Event) -> str:
    p = Path(args["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"])
    return f"Wrote {len(args['content'])} chars to {p}"


async def edit(args: dict, cancel: asyncio.Event) -> str:
    p = Path(args["path"])
    text = p.read_text()
    n = text.count(args["old_text"])
    if n != 1:
        raise ValueError(f"old_text must match exactly once in {p}, found {n} matches")
    p.write_text(text.replace(args["old_text"], args["new_text"]))
    return f"Edited {p}"


async def bash(args: dict, cancel: asyncio.Event) -> str:
    proc = await asyncio.create_subprocess_shell(
        args["command"], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True
    )
    run = asyncio.ensure_future(proc.communicate())
    stop = asyncio.ensure_future(cancel.wait())
    done, _ = await asyncio.wait({run, stop}, timeout=args.get("timeout", 120), return_when=asyncio.FIRST_COMPLETED)
    stop.cancel()
    if run not in done:
        os.killpg(proc.pid, 9)
        await run
        raise RuntimeError("command aborted" if cancel.is_set() else f"command timed out after {args.get('timeout', 120)}s")
    out = run.result()[0].decode(errors="replace")
    return _truncate(f"{out}\n[exit code: {proc.returncode}]")


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
