# 09 Part 3 · Execution environment

**Goal:** Give tools one safe place to touch files and run commands.

**Builds on:** [05 Agent loop](05-agent-loop.md#toolcontext-what-a-tool-gets) (tool context), [06 Events and abort](06-events-abort.md) (Stop) · **Previous:** [08 Hooks and approval](08-hooks-approval.md) · **Next:** [10 Coding tools](10-coding-tools.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent["agent ★ ExecutionEnv / LocalEnv (this chapter)"] --> coding --> session --> plugins --> testing
```

**IN:** a path or a command · **OUT:** text, bytes, entries, or `(exit code, output)`

Take the running example: the user asks "What is in README.md?". In Part 2 the loop could call a tool, but the tool had nothing real to work with. To answer, a `read` tool must open `README.md` on disk; later a `bash` tool must run commands like `pytest`. This chapter builds the [execution environment](glossary.md#execution-environment): the one object, `ctx.env` in the [tool context](glossary.md#tool-context) from [05](05-agent-loop.md#toolcontext-what-a-tool-gets), that every tool in [10](10-coding-tools.md) uses to do that work.

Big picture of Part 3: [part-3-coding](09-0-part-3-coding.md).

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/agent/env.py` — `ExecutionEnv`, `LocalEnv`, `run_kill`
- `packages/simp_agent/src/simp_agent/testing/env_conformance.py` — `EnvConformance`, a test suite any env must pass
- `packages/simp_agent/tests/test_env.py` — the tests for `LocalEnv`

## Problem

If each tool touches the disk with `open()` and runs commands with `subprocess` on its own, there is no single place to swap. Later the server runs each session inside a Docker container ([24](24-docker-sandbox.md)), and with ten tools calling `subprocess` we would change ten tools. So we put one object between the tools and the world; the server then swaps that one object, and no tool changes. A first, naive try at that object shows four more things it must get right.

## Naive version

So every tool will ask one object, the env, instead of touching the disk itself. What must the env be able to do? Look at our story: the agent must read `README.md`, write `NOTES.md` and run `pytest`. Every coding tool in [10](10-coding-tools.md) comes down to one of these three: **read a file, write a file, run a command**. So the env needs three methods. The simplest way to write them is to call Python's own tools directly: `open()` to read and write a file, `subprocess` to run a command, with no checks and nothing else:

```text
CLASS NaiveEnv(root):                       // root = the project folder the tools may use
    FUNCTION read_file(path):   RETURN open root + "/" + path and read it
    FUNCTION write_file(path, text):   open root + "/" + path and write text
    FUNCTION exec(command, cwd, timeout):
        p = START command in a shell
        p.wait(timeout)                     // blocks until p ends or timeout passes
        IF timeout passed: p.kill(); RETURN (None, "")
        RETURN (exit code, output)
```

It works for the happy case. To see where it breaks, look at where an env call runs. Python's [event loop](glossary.md#event-loop) runs on one thread. The [agent loop](05-agent-loop.md) runs inside it, together with the task that watches for Stop ([06](06-events-abort.md)) and the sending of events to the UI. The agent loop calls a tool, and the tool calls the env:

```text
event loop (one thread)
└─ agent_loop → tool → env
                        ├─ read_file / write_file → open() → disk
                        └─ exec("pytest") → new process: sh (p) → pytest → test server (port 8000)
```

Every tool goes through the env, so whatever the env gets wrong, every tool gets wrong. `NaiveEnv` gets four things wrong, at four places on this path:

- **env → disk: a path can leave the project.** The env is the one place that can check a path, but `NaiveEnv` just joins `root + "/" + path` and opens it. If the model asks `read_file("../.ssh/id_rsa")` (by mistake, or because a file told it to), `..` walks up out of the project, and the tool reads the user's secret SSH key, which then goes into the history and to the model provider. `write_file("../.bashrc", …)` could even change files outside the project. A *symlink* (a file that points to another place) can do the same.
- **env waits: the whole agent freezes.** `pytest` runs in its own process, but `NaiveEnv` waits for it with `p.wait()`. That wait holds the event loop's one thread for the whole minute, so nothing else can run: no events reach the UI, and Stop does nothing. (A plain `open()` holds the thread too, only for a shorter time.) A wait that is `await`ed would let the event loop run the other jobs in the meantime.
- **env → process: a timeout leaves processes running and loses the output.** On timeout, `NaiveEnv` kills only `p`, the shell. Killing a parent does not kill its children, so `pytest` and the test server keep running, and the next `pytest` run fails because port 8000 is still taken. Also, `NaiveEnv` reads the output only when the command ends, so on timeout it returns `""`: the model never sees the lines `pytest` already printed, such as which tests failed.
- **env → disk: a missing folder makes write fail.** `NaiveEnv` writes only to folders that already exist. So when the model saves its notes with `write_file("notes/NOTES.md", …)` and `notes/` does not exist yet, the write fails, and the model must make the folder and try again: a wasted turn.

## Real design

We follow two real requests from the running example, top-down: the model calls `read`, then `bash`. Each piece (contract, helper, class) comes in when the request needs it.

### Step 1: the tool asks `ctx.env`

The model sends the tool call `read(path="README.md")`. `run_tool` ([05](05-agent-loop.md)) runs the `read` tool and gives it a tool context. The tool does not open the file itself. It calls `await ctx.env.read_file(path)`. So the first question is: where does `ctx.env` come from? The tool never builds its own env. The host (CLI, server, eval runner) picks which env to pass in `LoopConfig.env`. If the host gives none, the default is `LocalEnv()`. The loop puts it into each tool's context: `ToolContext(cancel, config.env, config.cwd, on_update)`.

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`LoopConfig`, `agent_loop`)

```mermaid
flowchart LR
    Host["Host: CLI / server / evals"] -- "env=" --> LoopConfig
    LoopConfig -- "ToolContext.env" --> Tools["Tools (ch 10): read, write, edit, bash, ..."]
    Tools --> Env{"ExecutionEnv"}
    Env --> Local["LocalEnv (this machine)"]
    Env --> Docker["DockerEnv (ch 24)"]
```

[DockerEnv](24-docker-sandbox.md) is the second env, built in Part 5; here it only shows that a second one can exist.

#### The contract: `ExecutionEnv`

The tool does not know if `ctx.env` is a `LocalEnv` or a `DockerEnv`. To call it anyway, we need a contract: a list of methods every env has. `ExecutionEnv` is a `typing.Protocol`: any object with these methods counts, no need to inherit.

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

`ExecutionEnv` says what an env can do; `LocalEnv` and `DockerEnv` are how one kind of machine does it.

### Step 2: `LocalEnv` reads and writes files without freezing

The tool calls `ctx.env.read_file("README.md")`. By default, `ctx.env` is a `LocalEnv`, the env for the machine Python runs on. It fixes two breaks from the list.

**The freeze.** `NaiveEnv` called `open()` on the event loop's one thread, so that thread was busy until the disk answered. `LocalEnv` hands the disk work to a helper thread with `asyncio.to_thread`, and `await`s it. While it waits, the event loop's thread is free, so events still reach the UI and Stop is still heard:

```text
FUNCTION read_file(path):
    RETURN await (read text of _path(path)) in a helper thread
```

**The missing folder.** Before writing, `LocalEnv` makes every missing parent folder, so `write_file("notes/NOTES.md", …)` makes `notes/` first and does not fail:

```text
FUNCTION write_bytes(path, data):
    in a helper thread: make the missing parent folders, then write data
```

`write_file` only turns the text into bytes and calls `write_bytes`. `list`, `read_bytes` and `write_bytes` work the same way (see the real code).

Real code: [packages/simp_agent/src/simp_agent/agent/env.py](../../packages/simp_agent/src/simp_agent/agent/env.py) (`LocalEnv.read_file`, `write_bytes`)

Every method starts with `_path(path)`. What does it do with `"README.md"` before the disk is touched?

### Step 3: `_path` checks the path

`LocalEnv` takes one optional argument, `root`: the folder the tools may use. With no root (the `LoopConfig` default), `_path` returns the path as it is, so a relative path depends on the folder Python runs in; that is why the tools in [10](10-coding-tools.md) join it to `ctx.cwd` first.

This step fixes "env → disk: a path can leave the project". [Path safety](glossary.md#path-safety) means: when `LocalEnv` has a `root`, a file path can never point outside it.

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

Now the result goes back. If `_path` is happy, the text of `README.md` returns to the tool, the tool returns it to `run_tool`, and the model reads it in the next turn. What happens to an error? The tool does not catch it. `run_tool` ([05](05-agent-loop.md)) turns any exception into an error tool result. So the model sees `PermissionError: path escapes root: ../secret` and can try another path. The loop does not crash.

### Step 4: a second request, `bash`

Reading a file is short. Now the model calls `bash(command="pytest")`. The `bash` tool calls `ctx.env.exec(...)`. This call can be long, print a lot, and the user may press Stop. What does `exec` do with it? This step fixes "env waits: the whole agent freezes" for commands, and the lost output from "env → process: a timeout leaves processes running and loses the output".

`exec(command, cwd, timeout, cancel, on_output)` runs a shell command. While it runs, output streams out. Three things can end it:

1. **It finishes.** We return `(exit code, all output)`.
2. **The user presses Stop.** The `cancel` event (from the tool context) is set.
3. **The timeout passes.**

In cases 2 and 3 we kill the command and return `(None, output so far)`. `None` means "we killed it"; a real exit code would be a lie, because the command never finished. Example: `echo start; sleep 30` with timeout 2 gives `(None, "start\n")`, so the model still learns how far it got.

```text
FUNCTION exec(command, cwd, timeout, cancel, on_output = none):
    proc = START command in a shell, in cwd,
           stderr merged into stdout,             // one stream, in the order it came
           in a NEW process group                 // so one kill reaches all children
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

How to read it. stderr is merged into stdout so the model sees errors next to the line that caused them. Bad bytes are replaced, not raised, because one odd byte from a program must not crash the tool. `on_output` is what the `bash` tool passes as `ctx.on_update` ([05](05-agent-loop.md#toolcontext-what-a-tool-gets)), so each chunk becomes a `tool_execution_update` event for the UI.

The end is the same race as `_stream` in [06](06-events-abort.md), plus a timeout. Two things are new. After the kill we still wait for `run`: the output pipe closes only when every process in the group is dead, so this wait reads the last bytes. And every chunk is kept in `chunks`, so even after a kill the partial output returns.

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
        P-->>E: last bytes, then pipe closes
        E-->>T: (None, output so far)
    end
```

### Step 5: Stop kills the whole group

This step fixes the rest of "env → process: a timeout leaves processes running": the children that stay alive after the shell is killed. `exec` called `run_kill(proc.pid)` when Stop or the timeout won. Why a group, and not just the process? Look at the tree from the naive version: `sh` (p) starts `pytest`, which starts the test server. If we kill only `sh`, `pytest` and the test server live on, and the server still holds port 8000.

So we start the shell with `start_new_session=True`. Now the shell and every child it starts share one **process group**, whose id is the shell's PID. A [process-group kill](glossary.md#process-group-kill) sends `SIGKILL` (a kill signal that cannot be caught) to the whole group at once. `run_kill(pgid)` does this; `pgid` is the process group id, which is why `exec` passes `proc.pid`.

Real code: [packages/simp_agent/src/simp_agent/agent/env.py](../../packages/simp_agent/src/simp_agent/agent/env.py) (`run_kill`)

> **Detail (OS):** `run_kill` calls `os.killpg(pgid, 9)` up to 100 times, 20 ms apart (about 2 s max). Why repeat? A child may be forked at the moment the first signal goes out, and miss it. It stops when `killpg` raises `ProcessLookupError` (group empty) or, on macOS, `PermissionError` (only zombies left: dead processes whose exit code nobody has read yet).

### Step 6: the rules every env must pass

We followed one `read` and one `bash` call through `LocalEnv`. How do we know a second env, like `DockerEnv`, does the same? The types say *which* methods exist, not *how* they must behave. For that there is `EnvConformance` in the `testing` [layer](glossary.md#layer): one shared test class that checks path safety, exec output, cancel, and the group kill. Any env passes it by giving one fixture, `make_env(root)`. `DockerEnv` uses it in [24](24-docker-sandbox.md).

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

The most interesting check is the process-group kill. `self.run` is a small helper in the suite: it calls `env.exec` with the root as `cwd` and a fresh cancel event.

```text
TEST test_exec_timeout_kills_tree(env):
    t = now
    (code, text) = run in env, timeout 2 s:
        "echo start; (sleep 6; sleep 1; echo late > late.txt) & sleep 30"
    CHECK code is None AND "start" is in text
    CHECK less than 10 s passed
    UNTIL 8 s after t:                          // slack for a busy event loop
        CHECK late.txt does not exist           // background child was killed too
        WAIT 0.1 s
```

Real code: [packages/simp_agent/src/simp_agent/testing/env_conformance.py](../../packages/simp_agent/src/simp_agent/testing/env_conformance.py) (`test_exec_timeout_kills_tree`)

The command starts a background child that would write `late.txt` after 7 seconds, then sleeps 30. The timeout is 2 seconds. The test checks: we got `None` and the early output `start`, we returned quickly, and for 8 seconds `late.txt` never appears. With the naive `p.kill()`, the background child would live and write the file.

No [FakeProvider](04-label-test.md) here: the env has nothing to do with models. It is tested on its own.

```bash
uv run pytest packages/simp_agent/tests/test_env.py
```

## Why this way

> **One object between tools and the world.** Tools call `ctx.env`, never `open()` or `subprocess`.
>
> **A Protocol, plus a test suite as the real rules.** Types say *which* methods exist. `EnvConformance` says *how* they must behave (path safety, kill tree, partial output). A new env proves itself by passing it.
>
> **Kill the group, not the process.** A coding agent runs builds, tests and servers that start children. Only a process-group kill, repeated until empty, really stops them.
>
> **Path safety has a clear limit.** `LocalEnv`'s root stops bad file paths, not shell commands. Isolation for commands is a separate job ([24](24-docker-sandbox.md)).

## Exercises

1. `test_containment` already checks the symlink `dirlink/secret`. Remove `resolve()` from `_path` in your copy and run it. Which bad paths still fail, and which now pass through? Why?
2. In `exec`, change the call to `run_kill` into a plain `os.kill` of the one process. Run `test_exec_timeout_kills_tree`. It fails. Explain why.
3. Write a `ReadOnlyEnv` that wraps another env and refuses `write_file`. Which `EnvConformance` tests can it still pass?

## Recap

- The [execution environment](glossary.md#execution-environment) (`ExecutionEnv`) is a Protocol of six async methods: `read_file`, `write_file`, `read_bytes`, `write_bytes`, `list`, `exec`. Tools reach it as `ctx.env`; the host picks it via `LoopConfig.env` (default `LocalEnv()`).
- `LocalEnv` runs file IO in a thread (`asyncio.to_thread`), makes parent folders on write, and sorts `list`.
- [Path safety](glossary.md#path-safety): with a `root`, `_path` resolves `..` and symlinks, then raises `PermissionError` if the path leaves the root. Files only; `exec` is not checked.
- `exec` streams output through `on_output`, races finish / cancel / timeout, and returns `(None, output so far)` when killed.
- [Process-group kill](glossary.md#process-group-kill): `start_new_session=True` + `run_kill` sends `SIGKILL` to the group until it is empty, so background children die too.
- `EnvConformance` is one shared test suite; `LocalEnv` and `DockerEnv` both pass it.

**Builds on:** [05 Agent loop](05-agent-loop.md#toolcontext-what-a-tool-gets) (tool context), [06 Events and abort](06-events-abort.md) (Stop) · **Previous:** [08 Hooks and approval](08-hooks-approval.md) · **Next:** [10 Coding tools](10-coding-tools.md) — `read`, `write`, `edit`, `ls`, `grep`, `find` and `bash`, all built on `ctx.env`.
