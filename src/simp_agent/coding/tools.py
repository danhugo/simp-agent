"""Coding layer: read / write / edit / bash tools. Paths are relative to ctx.cwd; all IO goes through ctx.env."""

from __future__ import annotations

import math
import os
import shlex
import time

from ..agent import AgentTool
from .truncate import MAX_LINES, head, tail, truncate_head


def _obj(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _path(ctx, path: str) -> str:
    return os.path.join(ctx.cwd, path)  # absolute paths stay as is


async def read(args: dict, ctx) -> str:
    lines = (await ctx.env.read_file(_path(ctx, args["path"]))).splitlines()
    start = max(args.get("offset", 1), 1) - 1
    end = start + args.get("limit", MAX_LINES)
    out, info = truncate_head("\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines[start:end], start)))
    end = min(end, len(lines), start + info["kept_lines"])
    if end < len(lines):
        out += f"\n[{len(lines) - end} more lines; use offset={end + 1} to continue]"
    return out


async def write(args: dict, ctx) -> str:
    await ctx.env.write_file(_path(ctx, args["path"]), args["content"])
    return f"Wrote {len(args['content'])} chars to {args['path']}"


async def edit(args: dict, ctx) -> str:
    """Every edit matches the ORIGINAL text exactly once; overlaps are an error; then all apply (pi edit.ts)."""
    edits = args.get("edits") or []
    if "old_text" in args:
        edits = [{"old_text": args["old_text"], "new_text": args.get("new_text", "")}, *edits]
    if not edits:
        raise ValueError("Give old_text/new_text or edits")
    p = _path(ctx, args["path"])
    text = await ctx.env.read_file(p)
    spans = []
    for i, e in enumerate(edits):
        n = text.count(e["old_text"]) if e["old_text"] else 0
        if n != 1:
            raise ValueError(f"edits[{i}].old_text must match exactly once in {args['path']}, found {n} matches")
        start = text.index(e["old_text"])
        spans.append((start, start + len(e["old_text"]), e["new_text"]))
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1]:
            raise ValueError("Edits overlap; merge them into one edit")
    for start, end, new in reversed(spans):
        text = text[:start] + new + text[end:]
    await ctx.env.write_file(p, text)
    return f"Successfully replaced {len(spans)} block(s) in {args['path']}."


async def list_dir(ctx, path: str) -> list:
    """env.list_dir if the env has one, else `ls -1Ap`. Dirs end with "/"."""
    if hasattr(ctx.env, "list_dir"):
        return await ctx.env.list_dir(path)
    code, out = await ctx.env.exec(f"ls -1Ap {shlex.quote(path)}", ctx.cwd, None, ctx.cancel)
    if code != 0:
        raise OSError(out.strip() or f"ls failed: {path}")
    return [x for x in out.splitlines() if x]


async def ls(args: dict, ctx) -> str:
    names = sorted(await list_dir(ctx, _path(ctx, args.get("path", "."))), key=str.lower)
    limit = args.get("limit", 500)
    out = "\n".join(names[:limit]) or "(empty directory)"
    if len(names) > limit:
        out += f"\n[{limit} of {len(names)} entries shown; raise limit for more]"
    return head(out)


async def _run(ctx, primary: list, fallback: list) -> tuple[int | None, str]:
    """Run primary argv; if the program is missing (exit 127), run fallback."""
    code, out = await ctx.env.exec(shlex.join(primary), ctx.cwd, None, ctx.cancel)
    if code == 127:
        code, out = await ctx.env.exec(shlex.join(fallback), ctx.cwd, None, ctx.cancel)
    return code, out


def _limited(code, out: str, limit: int, empty: str) -> str:
    if code not in (0, 1):
        raise RuntimeError(out.strip() or f"exit code {code}")
    lines = [x for x in out.splitlines() if x]
    text = "\n".join(lines[:limit]) or empty
    if len(lines) > limit:
        text += f"\n[{limit} results limit reached; refine the pattern or raise limit]"
    return head(text)


async def grep(args: dict, ctx) -> str:
    path = args.get("path", ".")
    rg = ["rg", "--line-number", "--with-filename", "--no-heading", "--color=never"]
    gr = ["grep", "-rn"]
    if args.get("ignore_case"):
        rg.append("-i"); gr.append("-i")
    if args.get("literal"):
        rg.append("-F"); gr.append("-F")
    else:
        gr.append("-E")
    if args.get("context"):
        rg.append(f"-C{int(args['context'])}"); gr.append(f"-C{int(args['context'])}")
    if args.get("glob"):
        rg += ["--glob", args["glob"]]; gr.append(f"--include={args['glob']}")
    code, out = await _run(ctx, [*rg, "-e", args["pattern"], path], [*gr, "-e", args["pattern"], path])
    return _limited(code, out, args.get("limit", 100), "No matches found")


async def find(args: dict, ctx) -> str:
    path = args.get("path", ".")
    code, out = await _run(ctx, ["fd", "--glob", "--color=never", "--hidden", args["pattern"], path],
                           ["find", path, "-name", args["pattern"]])
    return _limited(code, out, args.get("limit", 1000), "No files found")


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
            return tail(f"{out}\n[exit code: {code}]")
        if ctx.cancel.is_set():
            return tail(f"{out}\n[Command interrupted by the user after {_elapsed(time.monotonic() - start)}]")
        return tail(f"{out}\n[Command timed out after {timeout:g} seconds]")

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
        AgentTool("edit", "Replace exact text in a file. Each old_text must match the original file exactly once. "
                          "Use edits for several non-overlapping changes in one call.",
                  _obj({"path": _p("string", "File path, relative to cwd or absolute"),
                        "old_text": _p("string", "Exact text to replace; must match exactly once"),
                        "new_text": _p("string", "Replacement text"),
                        "edits": {"type": "array", "description": "Several replacements, all matched against the original file",
                                  "items": _obj({"old_text": _p("string", "Exact text to replace; must match exactly once"),
                                                 "new_text": _p("string", "Replacement text")},
                                                ["old_text", "new_text"])}}, ["path"]), edit),
        AgentTool("bash", "Run a shell command in cwd. Returns stdout+stderr (the tail if long) and exit code. "
                          "Optional timeout in seconds; no timeout by default.",
                  _obj({"command": _p("string", "Shell command to run"),
                        "timeout": _p("number", "Timeout in seconds (optional, no default timeout)")}, ["command"]),
                  make_bash(bash_max_timeout_s)),
        AgentTool("grep", "Search file contents (ripgrep, respects .gitignore). Returns file:line: text.",
                  _obj({"pattern": _p("string", "Regex (or literal text if literal=true)"),
                        "path": _p("string", "Dir or file to search (default cwd)"),
                        "glob": _p("string", "Only files matching this glob, e.g. '*.py'"),
                        "ignore_case": _p("boolean", "Case-insensitive search"),
                        "literal": _p("boolean", "Treat pattern as plain text"),
                        "context": _p("integer", "Lines of context around each match"),
                        "limit": _p("integer", "Max output lines (default 100)")}, ["pattern"]), grep),
        AgentTool("find", "Find files by glob name pattern (fd, respects .gitignore).",
                  _obj({"pattern": _p("string", "Glob for file names, e.g. '*.py'"),
                        "path": _p("string", "Dir to search (default cwd)"),
                        "limit": _p("integer", "Max results (default 1000)")}, ["pattern"]), find),
        AgentTool("ls", "List a directory, sorted. Dirs end with '/'. Includes dotfiles.",
                  _obj({"path": _p("string", "Dir to list (default cwd)"),
                        "limit": _p("integer", "Max entries (default 500)")}, []), ls),
    ]


TOOLS = make_tools()

