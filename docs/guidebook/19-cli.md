# 19 Part 5 · The CLI

**Goal:** Wrap the session in a terminal app.

**Builds on:** [18 Profiles and built-in plugins](18-profiles-plugins.md) · **Next:** [20 The server run](20-server-run.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent --> coding --> session --> plugins --> testing
    session -.used by.-> apps["apps: cli, server (+ web)"]
    style apps fill:#ffd54f,stroke:#333,stroke-width:2px
```

*This chapter builds the first app: `apps/cli` (marked). It only uses the library; the library does not know it exists.*

Big picture of Part 5: [part-5-system](19-0-part-5-system.md).

Code in this chapter (commit `2fc2776`):

- `apps/cli/src/simp_cli/__init__.py` — `JsonlStore`, `session_dir`, `LinePrinter`, `run`, `main`
- `apps/cli/src/simp_cli/repl.py` — `Repl`
- `apps/cli/src/simp_cli/components.py` — `UserMsg`, `AssistantMsg`, `ToolCall`, `Notice`, `Chat`
- `apps/cli/tests/test_cli.py`, `apps/cli/tests/test_tui.py` — the CLI tests

## Problem

Picture a real morning. You open a terminal in your project folder and type `simp-agent "write fizzbuzz.py"`. You want to see the answer appear word by word. Halfway through you see the agent pick the wrong file name, and you want to tell it so without waiting. Before it runs `bash`, you want to say yes or no. Tomorrow you want to type `simp-agent -c` and go on from where you stopped.

At the end of Part 4 we have an `AgentSession` ([13](13-session.md)) with plugins, retry, compaction and profiles ([14](14-plugins.md)–[18](18-profiles-plugins.md)). It can write `fizzbuzz.py`. But you can only use it from Python code.

A person at a terminal needs more:

- Type `simp-agent "write fizzbuzz.py"` and see the answer as it streams.
- Talk for many turns, and come back tomorrow to the same conversation.
- Type while the agent works, to steer it ([07](07-steering.md)).
- Press Ctrl-C to stop a run, without killing the program.
- Say yes or no before the agent runs `bash` or writes a file ([08](08-hooks-approval.md)).

The CLI (command-line interface: the program you run in a terminal) is the thin layer that does this. It adds no agent behaviour of its own; it only connects keys and screen to the session. It lives in `apps/cli/src/simp_cli/` (the three files are listed at the top). The CLI is the first of two front doors to the same `AgentSession`; the server in [20](20-server-run.md) is the second.

## Starting point: 18's AgentSession, called from Python

At the end of [18](18-profiles-plugins.md) we use the `AgentSession` of [13](13-session.md) like this: build it, `subscribe` to its events ([06](06-events-abort.md)), and `await session.prompt(...)`. The first idea for a CLI is to put exactly that inside an `input()` loop, with one `asyncio.run` per line:

```text
session = AgentSession(model, tools)
session.subscribe(FUNCTION(event):
    IF event is message_end of an assistant message:
        PRINT the message text)

LOOP forever:
    line = read a line from the keyboard ("> ")
    IF input ended, or line is empty or "/exit": STOP
    START a new event loop, run session.prompt(line), WAIT until it ends
```

This is a sketch, not code from the repo. It works for one fizzbuzz turn. It breaks when:

1. **Nothing streams.** You see the answer only at `message_end`. A long answer looks like a hang.
2. **You cannot type while it runs.** `input()` is not called until `asyncio.run` returns. So no steering, no follow-up.
3. **Ctrl-C kills everything.** It raises `KeyboardInterrupt` and the program dies. It does not call `session.abort()` ([06](06-events-abort.md)).
4. **Nothing is saved.** No store is passed, so no resume.
5. **No approval.** No `approve` is passed, so the agent runs `bash` with no question.
6. **Each line makes a new event loop.** `asyncio.run` is called again and again on one session. Anything async the session made in the last run (its abort event, a task still running) belonged to the old loop, so it is lost or breaks.

None of these needs a new agent. The session already has every knob; the CLI only has to wire keys, screen and disk to it.

## Real design

The real CLI fixes each break above; each section says which one. It also splits into two modes: a simple **print mode** for one task (you give the task on the command line, it runs once and exits), and a full **REPL** (read–eval–print loop: a chat screen where you type many lines) for chat.

### main: pick a mode

`apps/cli/src/simp_cli/__init__.py`:

```text
task = the -p text, or else all plain words joined
IF there is a task:
    EXIT with the code from run(task, model, args)    // print mode
load the repl module now                              // needs the `cli` extra
EXIT with the code from repl(model, args)
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `main`.

`main()` reads flags with `argparse`. If there is a task (`-p "task"` or plain words), it runs **[print mode](glossary.md#print-mode)**. With no task, it starts the **[REPL](glossary.md#repl)**. The REPL import is inside `main`, so print mode does not load `prompt_toolkit` (the library that draws the REPL screen). If building the model fails with a `ValueError` (for example, an unknown profile), `main` prints the error and exits with code 1.

`pyproject.toml` maps the command to this function: `simp-agent = "simp_cli:main"`.

### Keys come from the environment

Before it picks a mode, `main` builds the model. `resolve_config` takes a profile from `~/.simp-agent/settings.json` ([18](18-profiles-plugins.md#profiles-and-build_model)) and puts CLI flags on top. One CLI rule matters here: **an API key is never read from the file**. Why: a settings file is easy to share or commit by mistake.

So `resolve_config` removes `"api_key"` from the profile. The file can only name an environment variable, `api_key_env`. For example, if the settings say `{"api_key_env": "MY_KEY"}` and `$MY_KEY` is set, the key is the value of `$MY_KEY`. If `$MY_KEY` is not set, the CLI falls back to `OPENAI_API_KEY` for OpenAI-style APIs (or `"dummy"`, for local servers with no key), and to `ANTHROPIC_API_KEY` otherwise.

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), functions `resolve_config` and `env_api_key`.

`env_api_key(model)` is the CLI's `get_api_key`. Providers never read the environment themselves ([01](01-pick-clean.md#1-pick-_providers-register_provider)); the app does.

### Sessions on disk

With the model and key ready, the CLI must open a session or load an old one. Both modes use `JsonlStore` from [13](13-session.md#jsonlstore-the-real-store-in-the-cli). Each working folder has its own sessions:

```text
FUNCTION session_dir(cwd):
    name = cwd without "/" at the ends, with each "/" changed to "-"
    RETURN folder SESSIONS / name
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `session_dir`.

Example: working in `/Users/a/proj` → sessions live in `~/.simp-agent/sessions/Users-a-proj/`, one `<id>.jsonl` file per session. This fixes break 4 (nothing saved).

So `-c` / `--continue` means "the latest session **for this folder**". `latest_session(cwd)` picks the file with the newest modified time; if the folder has no session yet, you simply get a new one. `--resume ID` opens one session by id. `-r` shows a list of this folder's sessions so you can pick one by number. A new session gets `uuid.uuid4().hex[:8]` as its id.

### Print mode

Print mode fixes breaks 1, 3 and 5: it streams, Ctrl-C only aborts, and it asks before risky tools.

`run(task, model, args)` is print mode. The heart of it:

```text
store = JsonlStore(file "<sid>.jsonl" in session_dir(cwd))
session = AgentSession(model, tools, store,
                       messages = store.load(),            // resume
                       get_api_key = env_api_key(model),
                       approve = none IF -y ELSE ask)
session sends each event to a new LinePrinter
WHEN Ctrl-C comes: call session.abort()
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `run`.

The store is loaded and passed as `messages=`, which is the resume pattern from [13](13-session.md#jsonlstore-the-real-store-in-the-cli). The tools come from `make_tools`, the coding tools of [10](10-coding-tools.md). With `-y` nothing asks for approval; else `ask` asks on the terminal (see [Approval in the terminal](#approval-in-the-terminal)). Ctrl-C (`SIGINT`, the signal the terminal sends) calls `session.abort()` ([06](06-events-abort.md#abort-one-asyncioevent)), so the run stops cleanly and the program does not die. Last, a `LinePrinter` subscribes to session events to print them.

At the end, `run` returns exit code `1` if the last message has `stop_reason` `"error"` or `"aborted"`, else `0`. So a shell script can check if the task worked.

**Why a `LinePrinter`?** Print mode output often goes to a file or a pipe. Printing every token makes a mess there. `LinePrinter` keeps deltas in a buffer and prints only full lines:

```text
FUNCTION _add(text, dim):
    IF dim is not the same as last time:
        flush what is in buf             // never mix dim and normal text on one line
    ADD text to buf
    split buf at each new line; the last, unfinished piece stays in buf
    FOR EACH finished line: PRINT it
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), method `LinePrinter._add`.

Thinking text is dim, but only when `self.out.isatty()`. In a pipe there are no **[ANSI codes](glossary.md#ansi-codes)**. Tool calls print as `> bash: ...`, and tool errors as `  ! ...`.

### The REPL

`repl.py` builds a `prompt_toolkit` `Application`. It is **not** full screen. The layout has three rows:

```text
RETURN an Application with:
    rows, top to bottom: live, prompt, bar
    keyboard focus on prompt
    redraw every 0.5 s
    erase itself when done
```

Real code: [apps/cli/src/simp_cli/repl.py](../../apps/cli/src/simp_cli/repl.py), method `Repl.build_app`.

The `live` row shows what is still changing (the streaming answer, tools waiting for a result; the [Components](#components) section at the end builds these), plus the approval question if one is waiting. The `prompt` row is one input line; its prefix is `> `, `… ` while running, or `Allow? [y/N/a] ` while asking. The `bar` row is a toolbar with the model id, the session id, about how many tokens are used (`estimate_tokens` from [16](16-compaction.md#when-estimate_tokens-and-should_compact)), and the state (`idle`, `running`, `compacting`, `retrying`).

Finished components go above the app with `run_in_terminal`. Why not full screen? Because then the text stays in the normal terminal: you can scroll back and copy it like any other output.

The input and the agent run at the same time. `start` makes the run a task and returns:

```text
FUNCTION start(run):
    start run as a background task, and RETURN at once
```

Real code: [apps/cli/src/simp_cli/repl.py](../../apps/cli/src/simp_cli/repl.py), method `Repl.start`.

So the input line stays alive while the agent works. This fixes breaks 2 and 6 of the naive version: there is one event loop for the whole REPL, and you can type during a run. Break 1 (streaming) is fixed by the `live` row, which is redrawn as deltas come in.

### Routing input

Now the user types their question and presses Enter. To know what to do with the line, we need a router. What a line means depends on the state. That logic is a pure function in `__init__.py`, so it is easy to test:

```text
FUNCTION route(line, running):        // gives back (kind, text)
    text = line without spaces at the ends
    IF text is empty:        RETURN ("empty", "")
    IF text starts with "/": RETURN ("command", text)
    IF running:
        IF text starts with ">>": RETURN ("follow_up", text after ">>", trimmed)
        ELSE:                     RETURN ("steer", text)
    RETURN ("prompt", text)
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `route`.

`Repl.submit` acts on the result. A `prompt` starts a run with `self.start(self.session.prompt(text))`. A `steer` calls `self.session.steer(text)`, and a `follow_up` calls `self.session.follow_up(text)`; these are the two queues of [07](07-steering.md#the-agent-side-two-lists-and-a-mode) (a **[steer](glossary.md#steer)** message goes in at the next turn, a follow-up runs after the agent would stop). A `command` goes to `Repl.command`, which knows `/help`, `/history`, `/new`, `/sessions`, `/compact`, and `/exit` (or `/quit`).

Some commands need an idle agent. While running, `/new`, `/sessions` and `/compact` say `busy: Ctrl-C to abort first`.

`submit` checks two states before `route`. If an approval is waiting, the line is the answer. If a session list is shown (`/sessions` or `-r`), the line is a number to pick.

Ctrl-C uses another pure function:

```text
FUNCTION interrupt_action(running, last_idle_ctrl_c, now):
    // Ctrl-C gives: "abort" (while running)
    //               "exit"  (second one within 2 s when idle)
    //               "warn"  (else)
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `interrupt_action`.

While running, Ctrl-C aborts the run. When idle, the first Ctrl-C only warns; a second one within 2 seconds exits. Ctrl-D on an empty line also exits.

### Approval in the terminal

A `prompt` line starts the agent. When the agent wants to run a risky tool, it must ask the user first. The session already has the approval policy ([08](08-hooks-approval.md#approval-a-before_tool_call-that-asks-a-human)): it calls an `approve(call)` function that returns `"allow"`, `"deny"` or `"always"`, and only for `bash`, `write` and `edit`. The CLI only has to supply that function, which asks the human.

Both modes turn the typed text into an answer with one function:

```text
FUNCTION approval_answer(text):
    t = text trimmed and in lower case
    IF t is "y" or "yes":       RETURN "allow"
    IF t is "a" or "always":    RETURN "always"
    RETURN "deny"
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `approval_answer`.

Anything else is `"deny"`. The safe answer is the default.

**In print mode**, `ask` is a plain blocking `input()`:

```text
FUNCTION ask(call):     // blocking input is fine: nothing else runs while a tool waits
    PRINT "? " + describe_call(call)
    REMOVE the Ctrl-C handler for now     // so Ctrl-C raises KeyboardInterrupt inside input()
    TRY:   RETURN approval_answer(input("Allow? [y/N/a] "))
    IF Ctrl-C:        call session.abort(); RETURN "deny"
    IF input ended:   RETURN "deny"
    ALWAYS at the end: put the Ctrl-C handler back (it calls session.abort)
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `ask` inside `run`.

Why remove the handler? While the asyncio handler is set, Ctrl-C only calls `session.abort()`; `input()` never sees it and keeps waiting. Removing it for a moment lets Ctrl-C break out of `input()`.

**In the REPL**, a blocking `input()` would freeze the screen. So `approve` is async and waits on a **[future](glossary.md#future)**: an empty box that one side waits on and the other side fills with `set_result`.

```text
FUNCTION approve(call):      // async
    pending = a new empty future, holding call
    redraw the screen                     // the question shows
    WAIT for pending to get an answer
    RETURN that answer
    ALWAYS at the end: pending = none, redraw the screen
```

Real code: [apps/cli/src/simp_cli/repl.py](../../apps/cli/src/simp_cli/repl.py), method `Repl.approve`.

The question shows in the live region. The next Enter calls `submit`, which sees `self.pending` and runs `self.pending.set_result(approval_answer(line))`. Ctrl-C while asking sets `"deny"` and then aborts.

`describe_call` makes the question short: `bash: <command>`, or `<tool>: <path>` for `write`, `edit` and `read` (for example `write: fizzbuzz.py`).

### Components

The agent now answers, and tools run after approval. Last, the answer must be drawn on the screen. To do that, the `live` row of [the REPL](#the-repl) is filled with small **[components](glossary.md#component)** from `components.py`. A component is any object with `render(width) -> list[str]`:

```text
COMPONENT UserMsg(text):
    FUNCTION render(width):
        RETURN the lines of "> " + text in bold, drawn at this width
```

Real code: [apps/cli/src/simp_cli/components.py](../../apps/cli/src/simp_cli/components.py), class `UserMsg`.

`_render` uses `rich` to draw into a string, not into the real terminal. So `render` is pure: a test can call `render(80)` and read the lines.

There are four components: `UserMsg`, `AssistantMsg`, `ToolCall` and `Notice`. `AssistantMsg` shows plain text while streaming and Markdown only when `done`; the code comment says why: "half-done markdown jumps around". `ToolCall` shows at most `TOOL_LINES = 12` lines of output, then `… (N more lines)`. A `CompactionEntry` ([16](16-compaction.md)) shows as the notice `— earlier history compacted —`.

`Chat` turns messages and events into components, and keeps them in two places. `live` holds components that still change. `commit(c)` sends a finished component to normal terminal scrollback, once.

The key method is `on_message`. It takes one finished message:

```text
FUNCTION on_message(m):     // called by live message_end AND by resume replay
    IF m is a user message:   commit UserMsg(m)
    IF m is an assistant message:
        drop the streaming component from live
        commit AssistantMsg(m), if it has something to show
        FOR EACH tool call in m: ADD a ToolCall to live      // waits for its result
    IF m is a tool result:    take its ToolCall out of live, add the result, commit it
    IF m is a compaction:     commit Notice("— earlier history compacted —")
```

Real code: [apps/cli/src/simp_cli/components.py](../../apps/cli/src/simp_cli/components.py), method `Chat.on_message`.

Example, fizzbuzz. One assistant message comes in: text "I will write it." and a call `write(path="fizzbuzz.py")`.

- Scrollback gets the lines of `I will write it.` (now Markdown, as it is done).
- `live` gets a `ToolCall` for `write: fizzbuzz.py`, still waiting.
- Then the tool result message comes in. The same `ToolCall` leaves `live`, gets the result, and goes to scrollback once.

Live events call it on `message_end`. Resume calls it too, through `replay(messages)`. One path for both means a resumed fizzbuzz session looks the same as when it ran live. `test_replay_equals_live` in `apps/cli/tests/test_tui.py` checks exactly this.

## Test

`apps/cli/tests/test_cli.py::test_route`:

```python
def test_route():
    assert cli.route("hi", False) == ("prompt", "hi")
    assert cli.route("hi", True) == ("steer", "hi")
    assert cli.route(">> later", True) == ("follow_up", "later")
    assert cli.route("/new", True) == ("command", "/new")
    assert cli.route("  ", True) == ("empty", "")
```

It checks that the same text `hi` is a new `prompt` when idle but a `steer` while running, that `>>` while running is a `follow_up` with the `>>` removed, that a `/` line is always a command, even while running, and that spaces only is `empty`.

No terminal, no model, no event loop. That is why `route` is a pure function and the REPL "only wires it to the terminal" (the comment above it in `__init__.py`).

Other tests in the same files use the same idea:

- `test_approval_answer_default_no` and `test_interrupt_action` test the other pure functions.
- `test_deny_skips_tool` and `test_always_asks_once_and_read_never_asks` are the approval tests already shown in [08](08-hooks-approval.md#test).
- `test_print_mode_full_lines_no_ansi` (in `test_tui.py`) feeds deltas to `LinePrinter` and checks it prints only full lines, with no ANSI.
- `test_pty_streaming_screen` starts a real REPL in a pseudo terminal and reads the screen with `pyte`. It checks that the answer shows while it still streams.

Run them:

```sh
uv run pytest apps/cli/tests/test_cli.py apps/cli/tests/test_tui.py -q
```

## Why this way

> **A thin app over the session, with pure logic pulled out.** The CLI adds no agent behaviour. Saving, approval policy, steering and abort all live in `AgentSession`; the CLI only connects keys and screen to them. Rules that are easy to get wrong (`route`, `approval_answer`, `interrupt_action`, `LinePrinter`, component `render`) are pure and unit tested. The REPL is not full screen, so finished output stays in normal scrollback. The cost: two modes with two `ask` functions, and the REPL itself is mostly tested by one slow pty test.

## Exercises

1. Run `route(">> later", False)` in your head. What does it return? (Answer: `("prompt", ">> later")`. `>>` only counts while running.)
2. In `approval_answer`, what does the text `"Y "` return? Why? (Answer: `"allow"`. It uses `strip().lower()`.)

## Recap

- `main()` picks **print mode** (a task is given) or the **REPL** (no task).
- Sessions are JSONL files per working folder; `-c` continues the latest, `--resume ID` opens one.
- Print mode prints full lines only, aborts on Ctrl-C, and returns exit code 1 on error or abort.
- Components render to lines; `Chat.on_message` is shared by live events and resume replay.
- The REPL runs the agent as a task, so you can steer, follow up and abort while it works.
- `route` decides what a line means; `approval_answer` turns `y` / `a` / anything into allow / always / deny.

**Builds on:** [18 Profiles and built-in plugins](18-profiles-plugins.md) · **Next:** [20 The server run](20-server-run.md)
