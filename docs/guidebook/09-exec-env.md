# 09 Part 3 · Execution environment

**Goal:** Give tools one safe place to touch files and run commands.

**Builds on:** [08 Hooks and approval](08-hooks-approval.md) · **Next:** [10 Coding tools](10-coding-tools.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent["agent ★ ExecutionEnv / LocalEnv (this chapter)"] --> coding --> session --> plugins --> testing
```

**Builds:** blocks 5, 6 · **IN:** a path or a command · **OUT:** text, bytes, entries, or `(exit code, output)`

Tools need one place to touch files and run commands. That place is the [execution environment](glossary.md#execution-environment): the `env` field of the [tool context](glossary.md#tool-context) from [05](05-agent-loop.md#toolcontext-what-a-tool-gets). All tools in [10](10-coding-tools.md) go through it.

Big picture of Part 3: [part-3-coding](09-0-part-3-coding.md).

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/agent/env.py` — `ExecutionEnv`, `LocalEnv`, `run_kill`
- `packages/simp_agent/src/simp_agent/testing/env_conformance.py` — `EnvConformance`, a test suite any env must pass
- `packages/simp_agent/tests/test_env.py` — the tests for `LocalEnv`

## Problem

A coding agent must touch the disk and run shell commands. If each tool does this on its own, with `open()` and `subprocess`, we get four problems:

1. **No single place to swap.** Later the server runs each session inside a Docker container ([24](24-docker-sandbox.md)). If ten tools each call `subprocess`, we must change ten tools. We want to change **one object**.
2. **Bad paths.** The model may ask to read `../../home/me/.ssh/id_rsa`. Nothing stops it.
3. **The loop freezes.** The agent loop is `async`: one event loop runs everything, one step at a time. A plain `open().read()` on a big file, or a `subprocess.run()` that takes a minute, blocks the event loop. The **Stop** button from [06](06-events-abort.md) cannot even be heard.
4. **Commands that never die.** `npm run dev &` starts a child process in the background. If we kill only the shell, the child lives on, long after the user pressed Stop.

## Naive version

```text
CLASS NaiveEnv(root):
    FUNCTION read_file(path):
        RETURN open root + "/" + path and read it      // blocks the loop
    FUNCTION write_file(path, text):
        open root + "/" + path and write text          // fails if the folder is missing
    FUNCTION exec(command, cwd, timeout):
        p = START command in a shell
        WAIT for p to end, at most timeout              // blocks the loop
        IF timeout passed:
            KILL p                                      // kills the shell only
            RETURN (None, "")                           // output so far is lost
        RETURN (exit code, output)
```

Where it breaks:

- **Paths leave the root.** `read_file("../secret")` reads outside the root. So does a symlink inside the root that points out.
- **It blocks.** No events go out, no Stop is heard.
- **No cancel.** Only a timeout. The user's Stop ([abort](glossary.md#abort)) cannot end a running command.
- **Children survive.** `p.kill()` kills the shell. `sleep 30 &` inside it keeps running.
- **Output is lost.** On timeout we return `""`. The model never learns how far the command got.
- **No folders.** `write_file("src/new/a.py", ...)` fails if `src/new` does not exist.

The sections below fix each break once.

## Real design

### One object for all tools

A tool never builds its own env. It uses `ctx.env`. The host (CLI, server, eval runner) picks which env to pass in `LoopConfig.env`. If the host gives none, the default is `LocalEnv()`. The loop puts it into each tool's context: `ToolContext(cancel, config.env, config.cwd, on_update)`.

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`LoopConfig`, `agent_loop`)

```mermaid
flowchart LR
    Host["Host: CLI / server / evals"] -- "env=" --> LoopConfig
    LoopConfig -- "ToolContext.env" --> Tools["Tools (ch 10): read, write, edit, bash, ..."]
    Tools --> Env{"ExecutionEnv"}
    Env --> Local["LocalEnv (this machine)"]
    Env --> Docker["DockerEnv (ch 24)"]
```

So to move all commands into Docker, the server swaps one object. No tool changes.

### `LocalEnv`: this machine

`LocalEnv` is the only env in the core library. It works on the machine where Python runs. It takes one optional argument, `root`: the folder the tools may use. With no root (the `LoopConfig` default), paths are used as they are.

File methods are thin. Each sends the slow disk work to a thread with `asyncio.to_thread`, so the event loop keeps running and Stop is still heard:

```text
FUNCTION read_file(path):
    RETURN WAIT for (read text of _path(path)) in a thread

FUNCTION write_file(path, text):
    WAIT for write_bytes(path, text as bytes)     // one write path

FUNCTION write_bytes(path, data):
    p = _path(path)
    IN a thread:
        MAKE all missing parent folders of p      // "src/new/a.py" makes "src/new" first
        WRITE data to p

FUNCTION list(path):
    IN a thread:
        FOR EACH entry in folder _path(path), sorted by name:
            ADD {name, is_dir, size} to out       // size is 0 for a folder
        RETURN out
```

Real code: [packages/simp_agent/src/simp_agent/agent/env.py](../../packages/simp_agent/src/simp_agent/agent/env.py) (`LocalEnv.read_file`, `write_file`, `write_bytes`, `list`)

Why these choices:

- `write_file` calls `write_bytes`, so there is one write path to check.
- Making parent folders means the model needs no "make folder" tool.
- `list` sorts by name, so the output is the same every time (good for tests and for the model).
- Bytes as well as text: text for code, bytes for images and the server's file download ([20](20-server-run.md)).

Every method starts with `_path(path)`. That is the next section.

### Path safety

[Path safety](glossary.md#path-safety) means: when `LocalEnv` has a `root`, a file path can never point outside it. This book uses only this one name for the idea.

A string check like `".." in path` is not enough: it misses symlinks and absolute paths. So `_path` first turns the path into its real, full form with `resolve()` (this removes `..` **and** follows symlinks), and only then asks "is this still inside the root?":

| Asked path | After `resolve()` | Result |
|---|---|---|
| `a/b.txt` | `<root>/a/b.txt` | ok |
| `../secret` | `<parent>/secret` | `PermissionError` |
| `link` (symlink to `<parent>/secret`) | `<parent>/secret` | `PermissionError` |
| `/etc/passwd` (absolute) | `/etc/passwd` (`root / "/etc/passwd"` drops the root) | `PermissionError` |

```text
FUNCTION _path(path):
    IF there is no root: RETURN path as it is
    root = resolve(root)
    p = resolve(root + path)
    IF p is not inside root: RAISE PermissionError "path escapes root: <path>"
    RETURN p
```

Real code: [packages/simp_agent/src/simp_agent/agent/env.py](../../packages/simp_agent/src/simp_agent/agent/env.py) (`LocalEnv._path`)

**Path safety is for files only.** `exec` does not check paths, so `cat ../secret` through bash still works on `LocalEnv`. Real isolation for commands is the Docker sandbox in [24](24-docker-sandbox.md). And with no root, every path is trusted. That is fine for a CLI on your own machine.

What happens to the error? The tool does not catch it. `run_tool` ([05](05-agent-loop.md)) turns any exception into an error tool result. So the model sees `PermissionError: path escapes root: ../secret` and can try another path. The loop does not crash.

### `exec`: run, stream, stop

`exec(command, cwd, timeout, cancel, on_output)` runs a shell command. While it runs, output streams out. Three things can end it:

1. **It finishes.** We return `(exit code, all output)`.
2. **The user presses Stop.** The `cancel` event (from the tool context) is set.
3. **The timeout passes.**

In cases 2 and 3 we kill the command and return `(None, output so far)`. `None` means "we killed it". Example: `echo start; sleep 30` with timeout 2 gives `(None, "start\n")`, so the model still learns how far it got.

```text
FUNCTION exec(command, cwd, timeout, cancel, on_output = none):
    proc = START command in a shell, in cwd,
           stderr merged into stdout,             // one stream, in the order it came
           in a NEW process group                 // see next section
    chunks = empty list

    FUNCTION pump():
        WHILE data = read next 4096 bytes of output:
            text = decode data                    // bad bytes become "�", no error
            ADD text to chunks
            IF on_output is given: WAIT for on_output(text)   // live output for the UI
        WAIT for proc to exit

    run  = START pump() as a task
    stop = START a task that WAITS for cancel to be set
    WAIT for the first of (run, stop), at most timeout
    STOP the stop task
    IF run is not done:                           // Stop or timeout
        WAIT for run_kill(proc.pid)
        WAIT for run                              // read the last bytes
        RETURN (None, all chunks joined)
    RETURN (proc exit code, all chunks joined)
```

Real code: [packages/simp_agent/src/simp_agent/agent/env.py](../../packages/simp_agent/src/simp_agent/agent/env.py) (`LocalEnv.exec`)

We keep every chunk in `chunks`, so even after a kill we can return what came so far.

```mermaid
sequenceDiagram
    participant T as Tool (bash)
    participant E as LocalEnv.exec
    participant P as Shell + children
    T->>E: exec(cmd, cwd, timeout, cancel, on_output)
    E->>P: start (new process group)
    loop while output comes
        P-->>E: 4 KB chunk
        E-->>T: on_output(text)
    end
    alt command ends
        E-->>T: (exit_code, output)
    else timeout or cancel
        E->>P: kill the whole group
        E-->>T: (None, output so far)
    end
```

### Process-group kill

The story: bash starts `npm test`, which starts `node`. If we kill only bash, `node` lives on and still holds port 3000.

So we start the shell with `start_new_session=True`. Now the shell and every child it starts share one **process group**, whose id is the shell's PID. A [process-group kill](glossary.md#process-group-kill) sends `SIGKILL` (a kill signal that cannot be caught) to the whole group at once. `run_kill(pgid)` does this.

Real code: [packages/simp_agent/src/simp_agent/agent/env.py](../../packages/simp_agent/src/simp_agent/agent/env.py) (`run_kill`)

> **Detail (OS):** `run_kill` calls `os.killpg(pgid, 9)` up to 100 times, 20 ms apart (about 2 s max). Why repeat? A child may be forked at the moment the first signal goes out, and miss it. It stops when `killpg` raises `ProcessLookupError` (group empty) or, on macOS, `PermissionError` (only zombies left: dead processes whose exit code nobody has read yet).

### The contract: `ExecutionEnv`

Now we can name all six methods. `ExecutionEnv` is a `typing.Protocol`: any object with these methods counts, no need to inherit.

```text
ExecutionEnv (all async):
    read_file(path)          -> text
    write_file(path, text)
    read_bytes(path)         -> bytes
    write_bytes(path, data)
    list(path)               -> list of {name, is_dir, size}
    exec(command, cwd, timeout, cancel, on_output = none) -> (exit_code or None, output)
```

Real code: [packages/simp_agent/src/simp_agent/agent/env.py](../../packages/simp_agent/src/simp_agent/agent/env.py) (`ExecutionEnv`)

The types say *which* methods exist, not *how* they must behave. For that there is `EnvConformance` in the `testing` [layer](glossary.md#layer): one shared test class that checks path safety, exec output, cancel, and the group kill. Any env passes it by giving one fixture, `make_env(root)`. `DockerEnv` uses it in [24](24-docker-sandbox.md).

Real code: [packages/simp_agent/src/simp_agent/testing/env_conformance.py](../../packages/simp_agent/src/simp_agent/testing/env_conformance.py) (`EnvConformance`)

## Test

`packages/simp_agent/tests/test_env.py` has two direct tests and a 4-line class that pulls in the whole suite:

```text
CLASS TestLocalEnvConformance(EnvConformance):
    FIXTURE make_env:
        RETURN a function: root -> LocalEnv(root)
```

Real code: [packages/simp_agent/tests/test_env.py](../../packages/simp_agent/tests/test_env.py) (`TestLocalEnvConformance`)

That is all `LocalEnv` needs to run the whole suite. The server does the same for Docker in `apps/server/tests/test_docker_sandbox.py` (`TestDockerEnvConformance`).

The most interesting check is the process-group kill:

```text
TEST test_exec_timeout_kills_tree(env):
    t = now
    (code, text) = run in env, timeout 2 s:
        "echo start; (sleep 6; sleep 1; echo late > late.txt) & sleep 30"
    CHECK code is None AND "start" is in text
    CHECK less than 10 s passed
    UNTIL 8 s after t:                          // slack for a loaded event loop
        CHECK late.txt does not exist           // background child was killed too
        WAIT 0.1 s
```

Real code: [packages/simp_agent/src/simp_agent/testing/env_conformance.py](../../packages/simp_agent/src/simp_agent/testing/env_conformance.py) (`test_exec_timeout_kills_tree`)

(`self.run` is a small helper in the suite: it calls `env.exec` with the root as `cwd` and a fresh cancel event.) The command starts a background child that would write `late.txt` after 7 seconds, then sleeps 30. The timeout is 2 seconds. The test checks: we got `None` and the early output `start`, we returned quickly, and for 8 seconds `late.txt` never appears. With the naive `p.kill()`, the background child would live and write the file.

No [FakeProvider](04-label-test.md) here: the env has nothing to do with models. It is tested on its own.

```bash
uv run pytest packages/simp_agent/tests/test_env.py
```

## Why this way

> **One object between tools and the world.** Tools call `ctx.env`, never `open()` or `subprocess`. To move all commands into Docker, the server swaps one object; no tool changes.
>
> **A Protocol, plus a test suite as the real rules.** Types say *which* methods exist. `EnvConformance` says *how* they must behave (path safety, kill tree, partial output). A new env proves itself by passing it.
>
> **Kill the group, not the process.** A coding agent runs builds, tests and servers that start children. Only a process-group kill, repeated until empty, really stops them.
>
> **Path safety has a clear limit.** `LocalEnv`'s root stops bad file paths, not shell commands. Isolation for commands is a separate job ([24](24-docker-sandbox.md)).

## Exercises

1. Make a symlink `dirlink` inside the root that points to a folder outside it. Write a test that `read_file("dirlink/secret")` raises `PermissionError`.
2. In `exec`, change the call to `run_kill` into a plain `os.kill` of the one process. Run `test_exec_timeout_kills_tree`. It fails. Explain why.
3. Write a `ReadOnlyEnv` that wraps another env and refuses `write_file`. Which `EnvConformance` tests can it still pass?

## Recap

- The [execution environment](glossary.md#execution-environment) (`ExecutionEnv`) is a Protocol of six async methods: `read_file`, `write_file`, `read_bytes`, `write_bytes`, `list`, `exec`. Tools reach it as `ctx.env`; the host picks it via `LoopConfig.env` (default `LocalEnv()`).
- `LocalEnv` runs file IO in a thread (`asyncio.to_thread`), makes parent folders on write, and sorts `list`.
- [Path safety](glossary.md#path-safety): with a `root`, `_path` resolves `..` and symlinks, then raises `PermissionError` if the path leaves the root. Files only; `exec` is not checked.
- `exec` streams output through `on_output`, races finish / cancel / timeout, and returns `(None, output so far)` when killed.
- [Process-group kill](glossary.md#process-group-kill): `start_new_session=True` + `run_kill` sends `SIGKILL` to the group until it is empty, so background children die too.
- `EnvConformance` is one shared test suite; `LocalEnv` and `DockerEnv` both pass it.

**Builds on:** [08 Hooks and approval](08-hooks-approval.md) · **Next:** [10 Coding tools](10-coding-tools.md) — `read`, `write`, `edit`, `ls`, `grep`, `find` and `bash`, all built on `ctx.env`.
