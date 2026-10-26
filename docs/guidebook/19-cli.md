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


## Problem

Picture a real morning. You open a terminal in your project folder and type `simp-agent "write fizzbuzz.py"`. You want to see the answer appear word by word. Halfway through you see the agent pick the wrong file name, and you want to tell it so without waiting. Before it writes the file or runs `bash`, you want to say yes or no. Tomorrow you want to type `simp-agent -c` and go on from where you stopped.

At the end of Part 4 we have an `AgentSession` ([13](13-session.md)) with plugins, retry, compaction and profiles ([14](14-plugins.md)–[18](18-profiles-plugins.md)). It can write `fizzbuzz.py`. But you can only use it from Python code.

The CLI (command-line interface: the program you run in a terminal) is the thin layer that connects keys, screen and disk to that session. It adds no agent behaviour of its own. Its code is in `apps/cli/src/simp_cli/`. The CLI is the first of two front doors to the same `AgentSession`; the server in [20](20-server-run.md) is the second.

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


- **No streaming.** You see the answer only at `message_end`. A long answer looks like a hang.
- **No typing during a run.** `input()` is not called until `asyncio.run` returns. So no steering, no follow-up.
- **Ctrl-C kills the program.** It raises `KeyboardInterrupt` and the program dies. It does not call `session.abort()` ([06](06-events-abort.md)).
- **Nothing saved.** No store is passed, so no resume.
- **No approval.** No `approve` is passed, so the agent runs `bash` with no question.
- **A new [event loop](glossary.md#event-loop) per line.** `asyncio.run` is called again and again on one session. Anything async the session made in the last run (its abort event, a task still running) belonged to the old loop, so it is lost or breaks.

None of these needs a new agent. The session already has every knob; the CLI only has to wire keys, screen and disk to it.

## Real design

We follow one run, from the moment you press Enter in the terminal: `main` picks a mode, a session opens, your question goes to `AgentSession`, its events come back, a printer draws them, and the agent stops to ask before a risky tool. Print mode (one task, then exit) shows this path in its simplest form. The REPL then runs the same path many times in one chat screen.

### main: pick a mode

You type `simp-agent "write fizzbuzz.py"`. `pyproject.toml` maps the command to one function: `simp-agent = "simp_cli:main"`.

`apps/cli/src/simp_cli/__init__.py`:

```text
task = the -p text, or else all plain words joined
IF there is a task:
    EXIT with the code from run(task, model, args)    // print mode
load the repl module now                              // needs the `cli` extra
EXIT with the code from repl(model, args)
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `main`.

`main()` reads flags with `argparse` and builds the model (from a profile, [18](18-profiles-plugins.md#profiles-and-build_model)). If there is a task (`-p "task"` or plain words), it runs **[print mode](glossary.md#print-mode)**: one task, then exit. With no task, it starts the **[REPL](glossary.md#repl)** (read–eval–print loop: a chat screen where you type many lines). The REPL import is inside `main`, so print mode does not load `prompt_toolkit` (the library that draws the REPL screen). If building the model fails with a `ValueError` (for example, an unknown profile), `main` calls `argparse`'s `p.error`, which prints the usage and the error and exits with code 2.

Our fizzbuzz command has a task, so `main` calls `run`.

### A session opens

`run(task, model, args)` first needs a session to put the question in: a new one, or yesterday's. Both modes keep sessions with `JsonlStore` from [13](13-session.md#jsonlstore-the-real-store-in-the-cli), and each working folder has its own sessions:

```text
FUNCTION session_dir(cwd):
    name = cwd without "/" at the ends, with each "/" changed to "-"
    RETURN folder SESSIONS / name
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `session_dir`.

Example: working in `/Users/a/proj` → sessions live in `~/.simp-agent/sessions/Users-a-proj/`, one `<id>.jsonl` file per session. This fixes "nothing saved".

So `-c` / `--continue` means "the latest session **for this folder**". `latest_session(cwd)` picks the file with the newest modified time; if the folder has no session yet, you simply get a new one. `--resume ID` opens one session by id. A new session gets `uuid.uuid4().hex[:8]` as its id.

### The question goes to AgentSession

With the session file chosen, `run` builds the session and sends the task:

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

The store is loaded and passed as `messages=`, which is the resume pattern from [13](13-session.md#jsonlstore-the-real-store-in-the-cli). The tools come from `make_tools`, the coding tools of [10](10-coding-tools.md). Ctrl-C (`SIGINT`, the signal the terminal sends) calls `session.abort()` ([06](06-events-abort.md#abort-one-asyncioevent)), so the run stops cleanly and the program does not die. This fixes "Ctrl-C kills the program". Then `run` awaits `session.prompt(task)`.

**Where does the API key come from?** The session calls `get_api_key` when it needs a key. Providers never read the environment themselves ([01](01-pick-clean.md#1-pick-_providers-register_provider)); the app does, and `env_api_key(model)` is the CLI's version. One rule matters here: **an API key is never read from the settings file**, because a settings file is easy to share or commit by mistake. So `resolve_config` removes `"api_key"` from the profile; the file can only name an environment variable, `api_key_env`. For example, if the settings say `{"api_key_env": "MY_KEY"}` and `$MY_KEY` is set, the key is the value of `$MY_KEY`. If not, the CLI falls back to `OPENAI_API_KEY` for OpenAI-style APIs (or `"dummy"`, for local servers with no key), and to `ANTHROPIC_API_KEY` otherwise.

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), functions `resolve_config` and `env_api_key`.

At the end, `run` returns exit code `1` if `prompt` raises a `ValueError`, or if the last message has `stop_reason` `"error"` or `"aborted"`, else `0`. So a shell script can check if the task worked.

### Events come back: LinePrinter draws them

While `session.prompt` runs, the session sends events ([06](06-events-abort.md)). `run` subscribed a `LinePrinter` to them, so every event goes to it. Why not print every token? Print mode output often goes to a file or a pipe, and single tokens make a mess there. `LinePrinter` keeps deltas in a buffer and prints only full lines:

```text
FUNCTION _add(text, dim):
    IF dim is not the same as last time:
        flush what is in buf             // never mix dim and normal text on one line
    ADD text to buf
    split buf at each new line; the last, unfinished piece stays in buf
    FOR EACH finished line: PRINT it
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), method `LinePrinter._add`.

Thinking text is dim, but only when `self.out.isatty()`. In a pipe there are no **[ANSI codes](glossary.md#ansi-codes)**. Tool calls print as `> bash: ...`, and tool errors as `  ! ...`. This fixes "no streaming" for print mode: you see each line as soon as it is done.

### The agent asks before a risky tool

Now the model wants to `write` `fizzbuzz.py`. The session already has the approval policy ([08](08-hooks-approval.md#approval-a-before_tool_call-that-asks-a-human)): it calls an `approve(call)` function that returns `"allow"`, `"deny"` or `"always"`, and only for `bash`, `write` and `edit`. The CLI only supplies that function: `none` with `-y` (nothing asks), else `ask`. This fixes "no approval".

`describe_call` makes the question short: `bash: <command>`, or `<tool>: <path>` for `write`, `edit` and `read` (for example `write: fizzbuzz.py`). The typed answer becomes a decision with one function, used by both modes:

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

That is the whole print-mode run. The REPL runs the same path, but many times, and you can type while it runs.

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

The `live` row shows what is still changing (the streaming answer, tools waiting for a result), plus the approval question if one is waiting. The `prompt` row is one input line; its prefix is `> `, `… ` while running, or `Allow? [y/N/a] ` while asking. The `bar` row is a toolbar with the model id, the session id, about how many tokens are used (`estimate_tokens` from [16](16-compaction.md#when-estimate_tokens-and-should_compact)), and the state (`idle`, `running`, `compacting`, `retrying`).

Finished components go above the app with `run_in_terminal`. Why not full screen? Because then the text stays in the normal terminal: you can scroll back and copy it like any other output.

The input and the agent run at the same time. `start` makes the run a task and returns:

```text
FUNCTION start(run):
    start run as a background task, and RETURN at once
```

Real code: [apps/cli/src/simp_cli/repl.py](../../apps/cli/src/simp_cli/repl.py), method `Repl.start`.

So the input line stays alive while the agent works. There is one event loop for the whole REPL (this fixes "a new event loop per line"), and you can type during a run (this fixes "no typing during a run").

### Routing input

You type a line and press Enter. Is it a new question, a steer for the running agent, or a command? It depends on the state, so a router decides. That logic is a pure function in `__init__.py`, so it is easy to test:

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

`submit` checks two states before `route`. If an approval is waiting, the line is the answer. If a session list is shown (`/sessions`, or `-r` at start, which lists this folder's sessions), the line is a number to pick.

Ctrl-C uses another pure function:

```text
FUNCTION interrupt_action(running, last_idle_ctrl_c, now):
    // Ctrl-C gives: "abort" (while running)
    //               "exit"  (second one within 2 s when idle)
    //               "warn"  (else)
```

Real code: [apps/cli/src/simp_cli/__init__.py](../../apps/cli/src/simp_cli/__init__.py), function `interrupt_action`.

While running, Ctrl-C aborts the run. When idle, the first Ctrl-C only warns; a second one within 2 seconds exits. Ctrl-D on an empty line also exits.

### Approval in the REPL

When a `prompt` run reaches a risky tool, the REPL must ask, like print mode does. But a blocking `input()` would freeze the screen. So `approve` is async and waits on a **[future](glossary.md#future)**: an empty box that one side waits on and the other side fills with `set_result`.

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

### Components

In print mode, `LinePrinter` draws events. In the REPL, events go to `Chat`, which draws them as small **[components](glossary.md#component)** from `components.py`. A component is any object with `render(width) -> list[str]`:

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

Scrollback gets the lines of `I will write it.` (now Markdown, as it is done), and `live` gets a `ToolCall` for `write: fizzbuzz.py`, still waiting. When the tool result message comes in, that same `ToolCall` leaves `live`, gets the result, and goes to scrollback once.

Live events call it on `message_end`. Resume calls it too, through `replay(messages)`. One path for both means a resumed fizzbuzz session looks the same as when it ran live. `test_replay_equals_live` in `apps/cli/tests/test_tui.py` checks exactly this.

The rules that are easy to get wrong (`route`, `approval_answer`, `interrupt_action`, `LinePrinter`) are pure functions with fast unit tests; the REPL itself is mostly checked by one slow pty test, `test_pty_streaming_screen`.

**Builds on:** [18 Profiles and built-in plugins](18-profiles-plugins.md) · **Next:** [20 The server run](20-server-run.md)
