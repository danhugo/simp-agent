"""Coding layer: read / write / edit / bash tools. Paths are relative to ctx.cwd; all IO goes through ctx.env."""

from __future__ import annotations

import base64
import io
import hashlib
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


def _seen(ctx, path: str, text: str) -> None:
    """Remember the content hash of a file this session read or wrote (edit's change check)."""
    ctx.state.setdefault("read_hash", dict())[path] = hashlib.sha256(text.encode()).hexdigest()


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
MAX_IMAGE_BYTES = 5_000_000  # providers reject bigger pictures
MAX_RUN_IMAGES = 6  # pictures sent in one LLM call (each is sent once, then dropped)


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_TYPES


MAX_IMAGE_SIDE = 2000  # longer side after shrinking: plenty for the model to read text, far under every limit


def shrink_image(data: bytes) -> bytes | None:
    """A JPEG under MAX_IMAGE_BYTES (longest side <= MAX_IMAGE_SIDE), or None without Pillow or for unreadable data."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im.seek(0)  # gif/webp: first frame
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, "white")  # JPEG has no alpha: transparent parts go white
        flat.paste(im, mask=im.getchannel("A"))
        side, quality = MAX_IMAGE_SIDE, 85
        while True:
            pic = flat.copy()
            pic.thumbnail((side, side))
            out = io.BytesIO()
            pic.save(out, "JPEG", quality=quality, optimize=True)
            if out.tell() <= MAX_IMAGE_BYTES or side <= 256:
                return out.getvalue()
            side, quality = int(side * 0.7), max(60, quality - 10)
    except Exception:
        return None


async def load_image(env, path: str) -> str:
    data = await env.read_bytes(path)
    mime = IMAGE_TYPES[os.path.splitext(path)[1].lower()]
    if len(data) > MAX_IMAGE_BYTES:
        small = shrink_image(data)
        if small is None or len(small) > MAX_IMAGE_BYTES:
            raise ValueError(f"{os.path.basename(path)} is {len(data) // 1_000_000} MB; pictures over "
                             f"{MAX_IMAGE_BYTES // 1_000_000} MB can't be viewed (shrink it first, e.g. with Pillow)")
        data, mime = small, "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


LOOK_SYSTEM = ("You look at pictures for an assistant and answer its question about them. Pictures are numbered in "
               "the order given. Answer per picture under a heading with its file name, e.g. '## slide-01.jpg'. Be "
               "compact and exact: copy text and numbers as shown; say plainly if something is broken, cut off, "
               "overlapping or unreadable.")
LOOK_QUESTION = "Describe each picture in detail: layout, all text, colors, and anything broken or cut off."
MAX_LOOK = 10  # pictures per read call


async def look(paths: list, question: str | None, ctx) -> str:
    """Pictures never enter the chat: one helper call (ctx.state["look"]: (system, text, data URLs) -> text) looks at
    all of them and only its answer, headed by file name, comes back. Read again after a change: always the file now."""
    notes, names, urls = list(), list(), list()
    for name in paths[:MAX_LOOK]:
        try:
            urls.append(await load_image(ctx.env, _path(ctx, name)))
            names.append(name)
        except Exception as e:  # missing, too big: the others are still looked at
            notes.append(f"Skipped {name}: {e}")
    notes += [f"Skipped {n}: at most {MAX_LOOK} pictures per read" for n in paths[MAX_LOOK:]]
    if names:
        helper = ctx.state.get("look")
        text = ("Pictures, in order: " + ", ".join(f"{i + 1}) {n}" for i, n in enumerate(names))
                + f"\n\nQuestion: {question or LOOK_QUESTION}")
        try:
            if helper is None:
                raise RuntimeError("no model here can view images")
            notes.append(await helper(LOOK_SYSTEM, text, urls))
        except Exception as e:  # no vision model, provider refused, empty reply: say so, never retry
            notes.append(f"Could not view {', '.join(names)}: {e}")
    return "\n".join(notes)


MAX_TEXT_FILES = 10  # text files per read call


async def read(args: dict, ctx) -> str:
    """One file, or several: text files come back one after another under their name, pictures go to look()."""
    paths = args.get("paths") or ([args["path"]] if args.get("path") else [])
    if not paths:
        raise ValueError("give path (or paths for several files)")
    images, texts = [x for x in paths if is_image(x)], [x for x in paths if not is_image(x)]
    if len(paths) == 1 and texts:
        return await _read_text(texts[0], args, ctx)
    parts = list()
    for name in texts[:MAX_TEXT_FILES]:
        try:
            body = await _read_text(name, args, ctx)
        except Exception as e:  # missing, blocked: the others are still read
            body = f"Error: {e}"
        parts.append(f"==> {name} <==\n{body}")
    parts += [f"Skipped {n}: at most {MAX_TEXT_FILES} text files per read" for n in texts[MAX_TEXT_FILES:]]
    if images:
        parts.append(await look(images, args.get("prompt"), ctx))
    return "\n\n".join(parts)


async def _read_text(name: str, args: dict, ctx) -> str:
    p = _path(ctx, name)
    text = await ctx.env.read_file(p)
    _seen(ctx, p, text)
    lines = text.splitlines()
    start = max(args.get("offset", 1), 1) - 1
    end = start + args.get("limit", MAX_LINES)
    if stub := _same_read(ctx, p, start, end, text, name):
        return stub
    out, info = truncate_head("\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines[start:end], start)))
    end = min(end, len(lines), start + info["kept_lines"])
    if end < len(lines):
        out += f"\n[{len(lines) - end} more lines; use offset={end + 1} to continue]"
    return out


MAX_SAME_READ = 4  # the Nth read of the same unchanged lines is refused


def _same_read(ctx, p: str, start: int, end: int, text: str, name: str) -> str | None:
    """A short note instead of the content when these lines were read before and the file has not changed.
    3rd read: also a loop warning; 4th: refused. Compaction clears ctx.state["reads"] (the old content is gone)."""
    reads = ctx.state.setdefault("reads", dict())
    h = hashlib.sha256(text.encode()).hexdigest()
    prev_h, n = reads.get((p, start, end), (None, 0))
    n = n + 1 if prev_h == h else 1
    reads[(p, start, end)] = (h, n)
    if n == 1:
        return None
    if n >= MAX_SAME_READ:
        raise ValueError(f"BLOCKED: you have read these lines of {name} {n} times and the file has not changed. "
                         "Stop re-reading it: use the content above and continue with the task.")
    note = (f"{name} has not changed since you read these lines; the content is still above in this conversation. "
            "Use it instead of reading again.")
    if n >= 3:
        note += " You keep re-reading it: if you are stuck in a loop, stop reading and continue with the task."
    return note


async def write(args: dict, ctx) -> str:
    await ctx.env.write_file(_path(ctx, args["path"]), args["content"])
    _seen(ctx, _path(ctx, args["path"]), args["content"])
    return f"Wrote {len(args['content'])} chars to {args['path']}"


EDIT_FAILS_NUDGE = 3  # from this many failed edits in a row on one file, the error says to change approach


async def edit(args: dict, ctx) -> str:
    """Counts failed edits per file in a row; from the 3rd, the error tells the model to stop retrying variations."""
    p = _path(ctx, args["path"])
    fails = ctx.state.setdefault("edit_fails", dict())
    try:
        out = await _edit(args, ctx)
    except ValueError as e:
        n = fails[p] = fails.get(p, 0) + 1
        if n >= EDIT_FAILS_NUDGE:
            raise ValueError(f"{e}\nThis is failed edit #{n} in a row on {args['path']}. Stop retrying variations of "
                             "the same old_text. Either read the file again, use a longer and more unique old_text, "
                             "or rewrite the whole file with write.") from None
        raise
    fails.pop(p, None)
    return out


async def _edit(args: dict, ctx) -> str:
    """Every edit matches the ORIGINAL text exactly once; overlaps are an error; then all apply (pi edit.ts)."""
    edits = args.get("edits") or []
    if "old_text" in args:
        edits = [{"old_text": args["old_text"], "new_text": args.get("new_text", "")}, *edits]
    if not edits:
        raise ValueError("Give old_text/new_text or edits")
    p = _path(ctx, args["path"])
    text = await ctx.env.read_file(p)
    # content hash, not mtime (unreliable on FUSE mounts): another session or a command may have changed the file.
    # An edit without a prior read in this session is allowed.
    seen = ctx.state.get("read_hash", dict()).get(p)
    if seen and seen != hashlib.sha256(text.encode()).hexdigest():
        raise ValueError(f"{args['path']} changed since you last read it; read it again before editing")
    spans = []
    for i, e in enumerate(edits):
        if not e["old_text"]:
            raise ValueError(f"edits[{i}].old_text is empty")
        n = text.count(e["old_text"])
        if n == 0:
            raise ValueError(f"edits[{i}].old_text not found in {args['path']}. It must match the file exactly, "
                             "including whitespace and newlines; read the file again if unsure of its current text.")
        if n > 1:
            at, idx = [], -1
            while (idx := text.find(e["old_text"], idx + 1)) != -1 and len(at) < 10:
                if (line := str(text.count("\n", 0, idx) + 1)) not in at:
                    at.append(line)
            raise ValueError(f"edits[{i}].old_text matches {n} places in {args['path']} (lines {', '.join(at)}). "
                             "It must match exactly once: add surrounding lines to make it unique.")
        start = text.index(e["old_text"])
        spans.append((start, start + len(e["old_text"]), e["new_text"]))
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1]:
            raise ValueError("Edits overlap; merge them into one edit")
    for start, end, new in reversed(spans):
        text = text[:start] + new + text[end:]
    await ctx.env.write_file(p, text)
    _seen(ctx, p, text)
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


def _search_path(args: dict) -> str:
    path = args.get("path", ".")
    if path.startswith("-"):  # would be read as an option (rg --pre=, find -delete)
        raise ValueError(f"path must not start with '-': {path} (use ./{path})")
    return path


async def grep(args: dict, ctx) -> str:
    path = _search_path(args)
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
    code, out = await _run(ctx, [*rg, "-e", args["pattern"], "--", path], [*gr, "-e", args["pattern"], "--", path])
    return _limited(code, out, args.get("limit", 100), "No matches found")


async def find(args: dict, ctx) -> str:
    path = _search_path(args)
    code, out = await _run(ctx, ["fd", "--glob", "--color=never", "--hidden", "--", args["pattern"], path],
                           ["find", path, "-name", args["pattern"]])
    return _limited(code, out, args.get("limit", 1000), "No files found")


def _elapsed(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}m{sec:02d}s" if m else f"{sec}s"


BASH_TIMEOUT_S = 180  # default: a hung command must not hold the whole run
BASH_MAX_TIMEOUT_S = 600


def make_bash(max_timeout_s: float | None = BASH_MAX_TIMEOUT_S, default_s: float = BASH_TIMEOUT_S):
    """Missing timeout -> default_s; max_timeout_s (None: no cap) clamps any timeout."""

    async def bash(args: dict, ctx) -> str:
        timeout = args.get("timeout")
        if timeout is not None and not (math.isfinite(timeout) and timeout > 0):
            raise ValueError(f"timeout must be a positive number of seconds, got {timeout}")
        timeout = timeout or default_s
        if max_timeout_s is not None:
            timeout = min(timeout, max_timeout_s)
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


def make_tools(bash_max_timeout_s: float | None = BASH_MAX_TIMEOUT_S) -> list:
    return [
        AgentTool("read", "Read a text file (output has line numbers; use offset/limit for big files), or look at "
                          "images (png, jpg, webp, gif): a helper looks at them and answers per file. To check several "
                          "pictures or files, pass them together in paths. Read again after a change to see the new version. "
                          "Use this instead of cat/head/tail in bash.",
                  _obj({"path": _p("string", "File path, relative to cwd or absolute"),
                        "paths": {"type": "array", "items": {"type": "string"},
                                  "description": f"Several files at once, instead of path: up to {MAX_TEXT_FILES} text files "
                                                 f"and {MAX_LOOK} images (offset/limit apply to each text file)"},
                        "prompt": _p("string", "Images only: what to check, e.g. 'does any title wrap or overlap?'. "
                                               "Omit for a full description."),
                        "offset": _p("integer", "First line to read, 1-based (default 1)"),
                        "limit": _p("integer", f"Max lines to read (default {MAX_LINES})")}, []), read, parallel=True),
        AgentTool("write", "Create or overwrite a file. Makes parent dirs.",
                  _obj({"path": _p("string", "File path, relative to cwd or absolute"),
                        "content": _p("string", "Full new file content")}, ["path", "content"]), write),
        AgentTool("edit", "Replace exact text in a file. Read the file first: each old_text must match the original file exactly once. "
                          "Use edits for several non-overlapping changes in one call.",
                  _obj({"path": _p("string", "File path, relative to cwd or absolute"),
                        "old_text": _p("string", "Exact text to replace; must match exactly once"),
                        "new_text": _p("string", "Replacement text"),
                        "edits": {"type": "array", "description": "Several replacements, all matched against the original file",
                                  "items": _obj({"old_text": _p("string", "Exact text to replace; must match exactly once"),
                                                 "new_text": _p("string", "Replacement text")},
                                                ["old_text", "new_text"])}}, ["path"]), edit),
        AgentTool("bash", "Run a shell command in cwd. Returns stdout+stderr (the tail if long) and exit code. "
                          f"Timeout {BASH_TIMEOUT_S}s by default, max {BASH_MAX_TIMEOUT_S}s; it returns as soon as the "
                          "command finishes, so give slow builds or tests a generous timeout. Do not use it for "
                          "cat/head/tail/grep/find/ls: use read, grep, find and ls.",
                  _obj({"command": _p("string", "Shell command to run"),
                        "timeout": _p("number", f"Timeout in seconds (default {BASH_TIMEOUT_S}, max {BASH_MAX_TIMEOUT_S})")}, ["command"]),
                  make_bash(bash_max_timeout_s)),
        AgentTool("grep", "Search file contents (ripgrep, respects .gitignore). Returns file:line: text. "
                          "Use this instead of grep/rg in bash. Prefer one broad search, e.g. alternation (a|b|c), "
                          "over several narrow ones.",
                  _obj({"pattern": _p("string", "Regex (or literal text if literal=true)"),
                        "path": _p("string", "Dir or file to search (default cwd)"),
                        "glob": _p("string", "Only files matching this glob, e.g. '*.py'"),
                        "ignore_case": _p("boolean", "Case-insensitive search"),
                        "literal": _p("boolean", "Treat pattern as plain text"),
                        "context": _p("integer", "Lines of context around each match"),
                        "limit": _p("integer", "Max output lines (default 100)")}, ["pattern"]), grep, parallel=True),
        AgentTool("find", "Find files by glob name pattern (fd, respects .gitignore). Use this instead of find in bash.",
                  _obj({"pattern": _p("string", "Glob for file names, e.g. '*.py'"),
                        "path": _p("string", "Dir to search (default cwd)"),
                        "limit": _p("integer", "Max results (default 1000)")}, ["pattern"]), find, parallel=True),
        AgentTool("ls", "List a directory, sorted. Dirs end with '/'. Includes dotfiles. Use this instead of ls in bash.",
                  _obj({"path": _p("string", "Dir to list (default cwd)"),
                        "limit": _p("integer", "Max entries (default 500)")}, []), ls, parallel=True),
    ]


TOOLS = make_tools()

