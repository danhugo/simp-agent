# 10 Part 3 · Coding tools

**Goal:** Build read, write, edit, ls, grep, find and bash.

**Builds on:** [09 Execution environment](09-exec-env.md) · **Next:** [11 The system prompt](11-system-prompt.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent --> coding["coding ★ tools.py / truncate.py (this chapter)"] --> session --> plugins --> testing
```

In [05](05-agent-loop.md#tools-agenttool) we built the [agent tool](glossary.md#agent-tool) type and `run_tool`. In [09](09-exec-env.md) we built the [execution environment](glossary.md#execution-environment), the one object that touches files and runs commands. Now we join the two: seven real tools that a coding agent needs. Each tool is a short `async` function that takes `(args, ctx)` and returns a string. Each one does its IO through `ctx.env` and nothing else.

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/coding/tools.py` — the seven tools and `make_tools`
- `packages/simp_agent/src/simp_agent/coding/truncate.py` — `truncate_head`, `truncate_tail`, `head`, `tail`
- `packages/simp_agent/tests/test_tools.py`, `packages/simp_agent/tests/test_bash.py` — the tests

## Problem

The loop from [05](05-agent-loop.md) can call tools, but it has none. To fix a bug, a model must be able to:

1. **look around** — list folders, find files by name, search text in files;
2. **read** a file;
3. **change** a file — write a new one, or edit part of an old one;
4. **run** things — tests, builds, `git`.

Each tool also has a hidden enemy: **size**. A model has a limited [context](glossary.md#context). One `cat` of a log file or one `grep` over `node_modules` can return megabytes. If we send all of it back, the next model call fails or costs a lot. So every tool must cut its output, and must **tell the model** that it cut, and how to get the rest.

## Naive version

```python
import subprocess

async def read(args, ctx):
    return open(args["path"]).read()

async def write(args, ctx):
    open(args["path"], "w").write(args["content"])
    return "ok"

async def edit(args, ctx):
    text = open(args["path"]).read()
    text = text.replace(args["old_text"], args["new_text"])
    open(args["path"], "w").write(text)
    return "ok"

async def bash(args, ctx):
    p = subprocess.run(args["command"], shell=True, capture_output=True, text=True)
    return p.stdout + p.stderr
```

Where it breaks:

- **It skips `ctx.env`.** It uses `open` and `subprocess` directly, so all the work of [09](09-exec-env.md) is lost: no fence, no Docker swap, a frozen event loop, no Stop.
- **Paths are relative to the Python process,** not to the session's working folder `ctx.cwd`.
- **`read` returns the whole file.** A 5 MB file fills the context.
- **`edit` replaces every match.** If `old_text` is `x = 1` and the file has it three times, all three change. If it has it zero times, the tool says "ok" and nothing happens. The model thinks it worked.
- **`bash` keeps the start of the output.** For a test run, the important part (the failures, the summary) is at the **end**.
- **`bash` hides the exit code,** so the model cannot tell pass from fail.

## Real design

### The shape of every tool

All tools live in `coding/tools.py`. Two tiny helpers set the pattern:

```python
def _obj(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _path(ctx, path: str) -> str:
    return os.path.join(ctx.cwd, path)  # absolute paths stay as is
```

- `_obj` builds the JSON schema for a tool's arguments. `additionalProperties: False` tells the model not to invent extra fields.
- `_path` makes a path relative to `ctx.cwd`. If the model gives an absolute path, `os.path.join` keeps it as is. The fence is **not** here: it is in the env ([path safety](glossary.md#path-safety), [09](09-exec-env.md#path-safety)). A tool only joins; the env decides if the path is allowed.

Errors are plain exceptions. A tool raises `ValueError`, `OSError` or `RuntimeError` with a clear message, and `run_tool` ([05](05-agent-loop.md#tools-agenttool)) turns it into an error tool result. So the tools never build error objects by hand.

### Truncation: `truncate_head` and `truncate_tail`

All tools share one cutting rule, in `coding/truncate.py`:

```python
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
```

[Truncation](glossary.md#truncation) keeps **whole lines** under **two** limits: at most 2000 lines and at most 50 KB. Two limits, because one is not enough: 2000 short lines are fine, but 10 lines of minified JavaScript can be 1 MB. The `+ 1` counts the newline between lines. A half line is never kept, so the model never sees a broken line.

There are two directions:

```python
def truncate_head(text, max_lines=MAX_LINES, max_bytes=MAX_BYTES):
    """Keep the first lines (read, ls, grep, find)."""
    kept = _cut(text.split("\n"), max_lines, max_bytes)
    return "\n".join(kept), _info(text, kept)


def truncate_tail(text, max_lines=MAX_LINES, max_bytes=MAX_BYTES):
    """Keep the last lines (bash: the end of the output matters most)."""
    kept = _cut(text.split("\n")[::-1], max_lines, max_bytes)[::-1]
    return "\n".join(kept), _info(text, kept)
```

`truncate_tail` just reverses the lines, cuts, and reverses back. Both return the text and an info dict: `truncated`, `total_lines`, `total_bytes`, `kept_lines`.

The tools do not call these two directly (except `read`). They call two small wrappers that also add a **note for the model**:

```python
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
```

The note is the important part. A model that sees "showing first 2000 of 9000 lines" knows the answer is not complete and can ask again in a narrower way. A model that sees a silent cut thinks it saw everything. Note also the odd case in `head`: if the very first line is over 50 KB, zero lines fit, so `head` says so and suggests `head -c`.

```mermaid
flowchart LR
    out["tool output"] --> which{"which tool?"}
    which -- "read, ls, grep, find" --> H["keep first lines<br/>note at the end"]
    which -- "bash" --> T["keep last lines<br/>note at the start"]
```

### `read`

```python
async def read(args: dict, ctx) -> str:
    lines = (await ctx.env.read_file(_path(ctx, args["path"]))).splitlines()
    start = max(args.get("offset", 1), 1) - 1
    end = start + args.get("limit", MAX_LINES)
    out, info = truncate_head("\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines[start:end], start)))
    end = min(end, len(lines), start + info["kept_lines"])
    if end < len(lines):
        out += f"\n[{len(lines) - end} more lines; use offset={end + 1} to continue]"
    return out
```

Step by step:

1. Read the whole file through the env, split into lines.
2. `offset` is 1-based (line 1 is the first line), because the model sees 1-based numbers. Values below 1 become 1.
3. Take at most `limit` lines (default 2000), and put the line number and a tab before each one. The numbers let the model say "line 42" and then come back with `offset=42`.
4. Cut with `truncate_head`, so the 50 KB limit also holds.
5. Work out where we **really** stopped: the end of the slice, the end of the file, or where the byte limit cut — we stop at the first of these three.
6. If lines are left, add a **continue hint**: `[N more lines; use offset=M to continue]`. This is not a generic "truncated" note; it tells the model the exact next call.

### `write`

```python
async def write(args: dict, ctx) -> str:
    await ctx.env.write_file(_path(ctx, args["path"]), args["content"])
    return f"Wrote {len(args['content'])} chars to {args['path']}"
```

One line of work. The env already makes parent folders ([09](09-exec-env.md#localenv-this-machine)), so the tool description can promise "Makes parent dirs." The result is short on purpose: the model already knows the content it sent; echoing it back would only waste context.

### `edit`

`edit` changes part of a file. It is the most careful tool, because a wrong edit silently breaks code.

```python
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
```

The rules, and why:

- **Two ways to call it.** One change: `old_text` + `new_text`. Many changes in one file: an `edits` list. Both can be given; the single one goes first. Many small edits in one call save turns.
- **Each `old_text` must match exactly once.** Zero matches means the model's memory of the file is wrong (maybe it changed). Two or more means the tool cannot know which one is meant. Both are errors with the count in the message, so the model can fix its call: add more lines of context to make the match unique, or `read` the file again. An empty `old_text` counts as zero matches.
- **All edits match the original text.** We find every span first, in the file **before** any change. So edit 2 does not depend on what edit 1 did. The model can plan all edits from one `read`.
- **Overlaps are an error.** After sorting the spans by start, if one starts before the previous one ends, two edits touch the same text. There is no safe answer, so the tool asks the model to merge them.
- **Apply from the back.** We replace spans from the last to the first. A change near the end does not move the positions of spans before it, so the saved positions stay true.
- **All or nothing.** Every check runs before the one `write_file`. If any edit is bad, the file is not touched.

```mermaid
flowchart TD
    A["read original file"] --> B["for each edit: count old_text"]
    B -- "not exactly 1" --> E1["error: found N matches"]
    B -- "all exactly 1" --> C["sort spans; any overlap?"]
    C -- yes --> E2["error: edits overlap"]
    C -- no --> D["replace from last span to first"] --> W["write file once"]
```

### `ls`

```python
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
```

`list_dir` uses an env method called `list_dir` if the env has one. `LocalEnv` from [09](09-exec-env.md) does not (its method is named `list`), so in practice it runs `ls -1Ap` through `ctx.env.exec`: one name per line (`-1`), dotfiles but not `.` and `..` (`-A`), a `/` after folders (`-p`). Running through `exec` means the same code works in a Docker env ([24](24-docker-sandbox.md)). The path goes through `shlex.quote`, so a name with spaces or `;` cannot break the command.

`ls` sorts case-insensitively, keeps `limit` entries (default 500), says how many were hidden, and finally passes through `head` for the byte limit. An empty folder says `(empty directory)` instead of an empty string, so the model does not wonder if the tool failed.

### `grep` and `find`

Both search tools follow the same plan: build an argv, try a fast modern program, fall back to the classic one.

```python
async def _run(ctx, primary: list, fallback: list) -> tuple[int | None, str]:
    """Run primary argv; if the program is missing (exit 127), run fallback."""
    code, out = await ctx.env.exec(shlex.join(primary), ctx.cwd, None, ctx.cancel)
    if code == 127:
        code, out = await ctx.env.exec(shlex.join(fallback), ctx.cwd, None, ctx.cancel)
    return code, out
```

Exit code 127 is what a shell returns for "command not found". So: `rg` (ripgrep) if installed, else `grep`; `fd` if installed, else `find`. The fast tools respect `.gitignore`, so they skip `node_modules` and build folders. The fallbacks work everywhere, but do not skip those folders. `shlex.join` quotes every argument, so a pattern like `it's "x"` reaches the program as one safe argument.

The output goes through one shared helper:

```python
def _limited(code, out: str, limit: int, empty: str) -> str:
    if code not in (0, 1):
        raise RuntimeError(out.strip() or f"exit code {code}")
    lines = [x for x in out.splitlines() if x]
    text = "\n".join(lines[:limit]) or empty
    if len(lines) > limit:
        text += f"\n[{limit} results limit reached; refine the pattern or raise limit]"
    return head(text)
```

For `grep` and `rg`, exit code 1 means "no matches", not "error". So 0 and 1 are both fine, and anything else (a bad regex, a missing folder) is raised. No results gives a clear text (`No matches found` / `No files found`). Too many results gives a note that asks the model to narrow the search.

One more guard, for both tools:

```python
def _search_path(args: dict) -> str:
    path = args.get("path", ".")
    if path.startswith("-"):  # would be read as an option (rg --pre=, find -delete)
        raise ValueError(f"path must not start with '-': {path} (use ./{path})")
    return path
```

Quoting stops the shell from reading the path as code, but the **program** can still read it as an option. A path of `--pre=evil` makes `rg` run a program; `-delete` makes `find` delete files. So a path may not start with `-`.

`grep` maps its arguments to flags for both programs.
The mapping is: `ignore_case` → `-i`, `literal` → `-F` (else plain `grep` gets `-E` for extended regex, like `rg`), `context` → `-C<n>`, `glob` → `--glob` or `--include=`. The pattern goes after `-e` and the path after `--`, so neither can be read as a flag. Default limit: 100 lines.

`find` runs `fd --glob --color=never --hidden -- <pattern> <path>`, or `find <path> -name <pattern>`. Default limit: 1000 files.

### `bash`

```python
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
```

`bash` is a **factory**: `make_bash` returns the tool function, and the function remembers one setting, `max_timeout_s`.

- **Timeout.** By default there is none: a long build is fine, and the user can press Stop ([06](06-events-abort.md)). The model may pass its own `timeout`; it must be a finite number above 0. The **host** (the program that runs the agent) may set `max_timeout_s`, a hard cap. Then a missing or bigger timeout becomes the cap. The model cannot raise it. At this commit the CLI reads it from the `bash_max_timeout_s` setting ([19](19-cli.md)); `None` means no cap.
- **All the hard work is in `exec`.** Streaming, cancel, timeout and the [process-group kill](glossary.md#process-group-kill) were built in [09](09-exec-env.md#exec-run-stream-stop). `bash` just passes `ctx.cancel` and `ctx.on_update` through, so the user sees output live while it runs.
- **Three endings, each with a note.** `exec` returns a code when the command finished, so we add `[exit code: N]` — the model needs it to know pass from fail. It returns `None` when killed; then `ctx.cancel` tells us if the user stopped it (`interrupted by the user after 1s`) or the timeout did (`timed out after 0.5 seconds`). In every case the output **so far** is kept.
- **`tail`, not `head`.** For tests and builds, the end of the output holds the result. The note goes at the **start**, where the cut happened.

### `make_tools`: names, descriptions, schemas

```python
def make_tools(bash_max_timeout_s: float | None = None) -> list:
    return [
        AgentTool("read", "Read a text file. Output has line numbers. Use offset/limit for big files.",
                  _obj({"path": _p("string", "File path, relative to cwd or absolute"),
                        "offset": _p("integer", "First line to read, 1-based (default 1)"),
                        "limit": _p("integer", f"Max lines to read (default {MAX_LINES})")}, ["path"]), read),
        ...
    ]


TOOLS = make_tools()
```

`make_tools` wraps each function in an `AgentTool` with a name, a one-line description and a schema. The order is `read, write, edit, bash, grep, find, ls`. **Every** argument has a description. The model only sees these strings, never the code, so they are part of the tool's behaviour: "must match exactly once", "no timeout by default", "Dirs end with '/'". `TOOLS` is the default list with no bash cap. The host passes `bash_max_timeout_s` when it wants one. The same descriptions also go into the system prompt in [11](11-system-prompt.md).

## Test

The tests call tools the way the loop does: through `run_tool` with a real `ToolContext`.

```python
async def call(tmp_path, name, env=None, **args):
    async def upd(text):
        pass

    c = ToolContext(asyncio.Event(), env or LocalEnv(), str(tmp_path), upd)
    return await run_tool(make_tools(), ToolCall("c", name, args), c)
```

**Truncation and the read hint** (`test_tools.py`):

```python
async def test_read_offset_hint(tmp_path):
    (tmp_path / "f").write_text("\n".join("x" * 100 for _ in range(1000)))
    r = await call(tmp_path, "read", path="f")
    assert "use offset=" in r.content and "to continue" in r.content and len(r.content.encode()) < 60_000
```

1000 lines of 100 bytes is about 100 KB: under the line limit, over the byte limit. The test checks that the byte limit wins and that the model gets the continue hint.

**Search fallback without installing anything.** To test "if `rg` is missing, use `grep`", we need a machine with no `rg`. `FakeEnv` (in `simp_agent.testing`) is a `LocalEnv` that records every command in `cmds`, returns exit 127 for programs listed in `missing`, and returns fixed output for programs in `canned`:

```python
async def test_grep_fallback(tmp_path):
    (tmp_path / "a.txt").write_text("hello world\nnope\nit's \"q\"\n")
    env = FakeEnv(missing=("rg",))
    r = await call(tmp_path, "grep", env=env, pattern="hello w")
    assert env.cmds[1].startswith("grep -rn") and r.content.endswith("a.txt:1:hello world")
    ...
    assert (await call(tmp_path, "grep", env=env, pattern="zzz")).content == "No matches found"
```

The first command (`rg`) "fails" with 127, the second one is real `grep`. The same trick tests `find` with `fd` missing, and `test_grep_rg_argv_quoting` uses `canned` to check that `it's "x"` is quoted correctly.

**Abort kills the whole tree and keeps output** (`test_bash.py`):

```python
async def test_abort_kills_tree_and_keeps_output(tmp_path):
    cancel = asyncio.Event()
    pidfile = tmp_path / "pid"
    # child shell + grandchild sleep; the grandchild writes its pid
    cmd = f"echo line1; echo line2; sh -c 'sleep 60 & echo $! > {pidfile}; wait'"
    task = asyncio.ensure_future(call(tmp_path, cancel, command=cmd))
    while not pidfile.exists() or not pidfile.read_text().strip():
        await asyncio.sleep(0.05)
    await asyncio.sleep(1.1)
    cancel.set()
    r = await asyncio.wait_for(task, 5)
    assert "line1" in r.content and "line2" in r.content
    assert "interrupted by the user after 1s" in r.content
    await asyncio.sleep(0.1)
    assert not alive(int(pidfile.read_text()))
```

(This file has its own `call` helper that always calls `bash`.) It checks all three promises at once: the early output is kept, the note says who stopped it and when, and the grandchild `sleep` is dead. Other tests in the file check that bad timeouts (`0`, `-1`, `inf`) are errors and that `max_timeout_s` clamps a model's `timeout=120000` down to 0.5 seconds.

No [FakeProvider](02-fake-provider.md) here: tools do not call models. The `edit` match rules (zero, one, many matches) are tested in `test_core.py` (`test_edit_matches`), next to the loop tests of [05](05-agent-loop.md).

```bash
uv run pytest packages/simp_agent/tests/test_tools.py packages/simp_agent/tests/test_bash.py
```

> **Why this way**
>
> **Small functions over one env.** Each tool is a plain `async` function that does IO only through `ctx.env`. Swap the env and every tool moves to Docker with no change.
>
> **Output is for a model, so every cut is announced.** Truncation keeps whole lines under a line and a byte limit, and always says what was cut and how to get more (`offset=`, "refine the pattern", `head -c`). Head for files and searches, tail for commands.
>
> **Edit is strict on purpose.** Exactly one match, all against the original, no overlaps, all or nothing. A loud error the model can fix is better than a quiet wrong edit.
>
> **Use the fast tool if it is there, never require it.** `rg` and `fd` when installed, `grep` and `find` when not, picked by exit code 127.

## Exercises

1. Call `edit` with an `old_text` that appears twice in the file. Read the error. Why does the tool refuse instead of changing the first match?
2. Use `FakeEnv(missing=("fd",))` and run `find`. Check which command was run instead (the fallback).
3. Run `bash` with `timeout=0.2` on `sleep 5`. Read the last line of the result.

## Recap

- Seven tools in `coding/tools.py`: `read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`. Each is `async (args, ctx) -> str`, does IO only through `ctx.env`, and raises plain exceptions that `run_tool` turns into error results.
- `_path` joins paths to `ctx.cwd`; the fence is in the env, not the tool.
- [Truncation](glossary.md#truncation) (`coding/truncate.py`) keeps whole lines under 2000 lines and 50 KB. `head` keeps the start (read, ls, grep, find); `tail` keeps the end (bash). Both add a note.
- `read` adds line numbers and an `offset=` hint. `write` relies on the env to make folders.
- `edit` needs each `old_text` to match the original exactly once, rejects overlaps, applies from the back, and writes once.
- `grep` / `find` try `rg` / `fd`, fall back to `grep` / `find` on exit 127, quote with `shlex`, and refuse paths starting with `-`.
- `bash` has no default timeout, an optional host cap (`make_bash(max_timeout_s)`), keeps the tail, and always says how it ended.
- `make_tools(bash_max_timeout_s)` builds the `AgentTool` list; `TOOLS` is the default.

**Builds on:** [09 Execution environment](09-exec-env.md) · **Next:** [11 The system prompt](11-system-prompt.md) — tell the model about these tools and the project.
