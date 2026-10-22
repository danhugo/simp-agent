# 14 Part 4 · Plugins

**Goal:** Add behaviour without changing the core.

**Builds on:** [13 Sessions](13-session.md) · **Next:** [15 Retry](15-retry.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent --> coding --> session --> plugins --> testing
    session -.used by.-> apps["apps: cli, server (+ web)"]
    style session fill:#ffd54f,stroke:#333,stroke-width:2px
```

*This chapter adds plugin support to the `session` layer (marked). The `plugins` layer itself is filled in [18](18-profiles-plugins.md).*

Big picture of Part 4: [part-4-session](13-0-part-4-session.md).

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/session/__init__.py` — `plugin_name`, `PluginAPI`, `AgentSession._hook`, `_context`, `_before_tool_call`, `_after_tool_call`, `_emit`
- `apps/cli/tests/test_sockets.py` — `Rec` and the plugin tests

## Problem

People want many small extras: hide API keys in tool output, a read-only "plan mode", an extra tool, a line in the system prompt, a log of every event. If each extra is an `if` inside `AgentSession`, the session grows without end, and every app gets every extra.

We want a **[plugin](glossary.md#plugin)**: a plain object that the session calls at fixed points. The core stays the same; you add a plugin to a list.

## Naive version

A first try: a list of callbacks, one per tool call.

Naive sketch (not in the repo):

```text
CLASS Session:
    FUNCTION init(agent, plugins):
        save agent and plugins
        agent.before_tool_call = before

    FUNCTION before(call, ctx):
        FOR EACH plugin p:
            r = p.tool_call(call)        // every plugin MUST have tool_call
            IF r has "block":
                RETURN r["block"]

CLASS NoBash:
    FUNCTION tool_call(call):
        IF call.name is "bash": RETURN {block: "no bash"}
        RETURN nothing
```

Key idea: one callback list. Limit: no optional hooks, no error safety, one hook point.

It blocks `bash` for the fizzbuzz task. Problems:

1. **Every plugin must define every method.** A plugin that only wants events has no `tool_call`. The run does not crash, but it ends with an `AttributeError` error message, and the tool never runs.
2. **One bad plugin breaks the run.** If a plugin's code raises, the whole agent run fails.
3. **Only one hook point.** No way to change the user's text, the messages sent to the model, the system prompt or the tool list.
4. **No access to the session.** A plugin cannot add a tool or save state.

## Step by step: from naive to real

We fix the naive `Session` one problem at a time.

**Step 1 — hooks are optional.** Do not call `p.tool_call(...)` directly. Look it up first with `getattr`, and skip the plugin if it has no such method:

(The full `_hook` is shown once, in [Real design](#a-plugin-is-any-object-hooks-are-optional-methods) below.)

Key idea: a missing hook is skipped, not an error.

Now a plugin that only wants events needs only `on_event`. This fixes problem 1.

**Step 2 — sync or async.** Some hooks are plain functions, some are `async`. We wrap the call with `_maybe_await(fn(*args))`. It awaits only when the result can be awaited. Plugin authors can pick either style.

**Step 3 — catch errors in one place.** We put the lookup and the call inside one helper, `_hook`, with a `try`. On error it emits a `plugin_error` event and returns `None`. This fixes problem 2: a bad plugin is reported, but the run goes on.

**Step 4 — but not for safety checks.** For `tool_call`, "skip on error" is wrong. A crashed guard must not let the tool run. So `_hook` gets `isolate=False`, and `_before_tool_call` turns the error into a block:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `_before_tool_call`

```text
TRY:
    r = WAIT for _hook(p, "tool_call", call, isolate = false), or {}
IF it raised error e:
    RETURN "blocked by plugin <name> (<error type>: e)"   // crash means no
```

Key idea: a crashed safety check blocks the tool.

**Step 5 — more hook points.** One hook is not enough. We call `_hook` at more fixed places: `input` and `before_agent_start` in `prompt()`, `context` before each model call, `tool_result` after a tool, `tool_update` and `on_event` in `_emit`. This fixes problem 3.

**Step 6 — give plugins a handle.** In `start()`, each plugin's `setup` gets a `PluginAPI` and its own config. With it, the plugin can add tools, prompt sections and saved entries. This fixes problem 4, without handing over the whole session.

The result is the real code below.

## Real design

The code is in `packages/simp_agent/src/simp_agent/session/__init__.py`.

### A plugin is any object; hooks are optional methods

There is no base class. A plugin is any object. Its name is `p.name` or its class name:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `plugin_name`

```text
FUNCTION plugin_name(p):
    RETURN p.name IF it has one, ELSE the class name of p
```

Key idea: no base class; any object can be a plugin.

The session calls a **[hook](glossary.md#plugin-hook)** only if the plugin has a method with that name. All calls go through one helper, `_hook`:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession._hook`

```text
FUNCTION _hook(p, hook, args, isolate = true):
    fn = method named hook on p, or nothing
    IF fn is nothing:
        RETURN nothing                         // missing hook: skip
    TRY:
        RETURN WAIT for fn(args) IF it is async, ELSE its plain result
    IF it raised error:
        IF not isolate:
            raise it again                     // caller decides (tool_call)
        SEND event plugin_error {plugin, hook, error} to subscribers only
                                               // not to plugins, so on_event cannot loop
        RETURN nothing                         // as if the plugin did nothing
```

Key idea: one place for lookup, sync/async and error handling.

Three things in a few lines:

- **Missing hook → skip.** No need to define every method.
- **Sync or async.** `_maybe_await` awaits only if the result is awaitable.
- **[Hook isolation](glossary.md#hook-isolation).** If the hook raises, the session emits a `plugin_error` event and returns `None`, as if the plugin did nothing. One broken plugin does not stop the run. Note the event goes to `_emit_all(self._subs, ...)` directly, not to other plugins, so a broken `on_event` cannot loop.

### The hook list

| Hook | When | What it can return |
|---|---|---|
| `setup(api, config)` | once, in `start()` | — |
| `session_start()` | once, after all setups | — |
| `input(text)` | start of `prompt()` | `{"handled": True}` to stop, or `{"text": ...}` to rewrite |
| `before_agent_start(info)` | before the run | `{"messages": [...]}` to add messages |
| `context(messages)` | before each model call | a new message list (chained) |
| `tool_call(call)` | before a tool runs | `{"block": reason}` or `{"args": {...}}` |
| `tool_result(call, result)` | after a tool runs, or after it is blocked or denied ([ch 08](08-hooks-approval.md)) | a dict of fields to replace |
| `tool_update(call, text)` | on streamed tool output | new text |
| `on_event(e)` | every session event | — |
| `session_shutdown()` | in `shutdown()` | — |

Let us look at the important ones.

**`setup` gets a `PluginAPI` and its config.** In `start()`:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession.start`

```text
FOR EACH plugin p:
    WAIT for _hook(p, "setup", new PluginAPI(session, name of p), plugin_config[name of p] or {})
FOR EACH plugin p:
    WAIT for _hook(p, "session_start")      // only after ALL setups are done
```

Key idea: each plugin gets its own API handle and only its own config.

`plugin_config` is a dict keyed by plugin name. Each plugin sees only its own part.

**`context` is a chain.** Before each model call:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession._context`

```text
FUNCTION _context(view):
    FOR EACH plugin p:                  // chained: each gets the previous output
        new = WAIT for _hook(p, "context", COPY of view)
        IF new is not empty: view = new  // fail or nothing: keep old view
    RETURN view
```

Key idea: plugins change only the view sent to the model, never the saved history.

Each plugin gets the output of the one before. It gets a *copy* of the list (`list(view)`), and the result is only the **[view](glossary.md#view-llm-view)** sent to the model. The saved history does not change. If a plugin fails or returns `None`, the chain keeps the previous view.

**`tool_call` fails closed.** This one is different:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession._before_tool_call`

```text
FUNCTION _before_tool_call(call, ctx):
    FOR EACH plugin p:                  // first block wins
        TRY:
            r = WAIT for _hook(p, "tool_call", call, isolate = false), or {}
        IF it raised error e:
            RETURN "blocked by plugin <name> (<error type>: e)"   // fail closed
        IF r has "block":
            RETURN "blocked by plugin <name>: <reason>"
        IF r has "args":
            call.arguments = r["args"]   // plugin rewrites the arguments
    ...  // then the approval check from ch 08
```

Key idea: an error in a safety hook means "no". Limit: plugins run before user approval.

**Worked example: fail closed with `NoBash`.** Take the `NoBash` plugin from above, but with a bug: its `tool_call` raises `KeyError('name')` instead of returning a block. The model asks for `bash`. `_hook` re-raises (`isolate=False`), `_before_tool_call` catches it and returns `blocked by plugin NoBash (KeyError: 'name')`. The loop turns that into a tool result `User denied: blocked by plugin NoBash (KeyError: 'name')` ([ch 08](08-hooks-approval.md)). The `bash` tool never runs. With a working `NoBash`, the result is `User denied: blocked by plugin NoBash: no bash`.

Here `isolate=False`. If a plugin's `tool_call` raises, the tool is **blocked**. Why? A `tool_call` hook is often a safety check. If the check crashes, running the tool anyway would be unsafe. So for this one hook, an error means "no". This is called **[fail closed](glossary.md#fail-closed)**. The first plugin that blocks wins. Plugins run before the user approval from [08](08-hooks-approval.md), so a blocked call never asks the user.

**`tool_result` merges.** Each plugin can return a few fields, and they are merged with `dataclasses.replace`:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession._after_tool_call`

```text
FUNCTION _after_tool_call(call, result, ctx):
    FOR EACH plugin p:                  // in order
        r = WAIT for _hook(p, "tool_result", call, result)
        IF r is not empty:
            result = copy of result with the fields in r replaced
    RETURN result
```

Key idea: each plugin changes only the fields it returns.

**`input` can handle a command.** In `prompt()`, if a plugin returns `{"handled": True}`, the session returns `[]` and the model is never called. This is how a plugin can handle its own slash command.

### PluginAPI: what a plugin may do

A plugin does not get the whole session. It gets a **[PluginAPI](glossary.md#pluginapi)**:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `PluginAPI`

```text
CLASS PluginAPI:                         // what a plugin may do with its session
    FUNCTION init(session, name): save both

    FUNCTION register_tool(tool):
        unregister_tool(tool.name)       // same name: replace the old one
        ADD tool to session agent tools
    ...
    FUNCTION add_prompt_section(id, value, order = 100):
        session.add_prompt_section(id, value, order)
    ...
    FUNCTION append_entry(type, data):
        RETURN WAIT for session.append_entry(type, data)
```

Key idea: a small, named surface, not the whole session.

The full method list is in [Reference · objects](ref-objects.md#pluginapi-methods). A small, named surface is easier to keep stable than "here is the whole session".

### Prompt sections

The system prompt is built every turn from ordered **[prompt sections](glossary.md#prompt-section)**. [Ch 13](13-session.md#prompt-sections-the-system-prompt-rebuilt-every-turn) shows how they work. What is new here: a plugin adds its own section with `api.add_prompt_section(id, value, order)`. The default order is 100, so it comes after `coding` (0) and `context_file` (10). Plan mode uses 1000, so it comes last ([18](18-profiles-plugins.md)).

### Plugin events

`_emit` also feeds plugins:

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession._emit`

```text
FUNCTION _emit(e):
    IF e.type is "tool_execution_update":
        FOR EACH plugin p:               // e.g. mask secrets before UI and logs see them
            r = WAIT for _hook(p, "tool_update", e.call, e.text)
            IF r is not nothing:
                e = copy of e with text = r
    SEND event e to all subscribers
    FOR EACH plugin p:
        WAIT for _hook(p, "on_event", e)
```

Key idea: tool output is changed before anyone sees it; then plugins see every event.

Streamed tool output goes through `tool_update` **before** the app sees it. So a redact plugin can hide a key before it reaches the screen or a log.

## Test

`apps/cli/tests/test_sockets.py::test_plugin_context_chain_and_error_isolated`:

```python
class Rec:
    def __init__(self, name, **hooks):
        self.name, self.log = name, []
        for k, v in hooks.items():
            setattr(self, k, v)
...
async def test_plugin_context_chain_and_error_isolated():
    seen, events = [], []

    def boom(msgs):
        raise RuntimeError("bad")

    p1 = Rec("p1", context=lambda m: m + [UserMessage("A")])
    p2 = Rec("p2", context=boom)
    p3 = Rec("p3", context=lambda m: m + [UserMessage(m[-1].content + "B")])
    s = session(DONE, seen=seen, plugins=[p1, p2, p3])
    s.subscribe(events.append)
    await s.prompt("hi")
    assert [m.content for m in seen[0].messages] == ["hi", "A", "AB"]
    assert [(e["plugin"], e["hook"]) for e in events if e["type"] == "plugin_error"] == [("p2", "context")]
```

What it checks:

- `Rec` builds a plugin from keyword hooks. No base class needed.
- The chain: `p1` adds `"A"`, `p3` sees `"A"` and adds `"AB"`. The model (a `FakeProvider`, [04](04-label-test.md)) got `["hi", "A", "AB"]`.
- Isolation: `p2` raised, but the run went on, and one `plugin_error` event names `p2` and `context`.

The sibling test `test_plugin_tool_call_first_block_exception_and_result_merge` in the same file checks the fail-closed rule for `tool_call`.

Run it:

```sh
uv run pytest apps/cli/tests/test_sockets.py::test_plugin_context_chain_and_error_isolated -q
```

## Why this way

> **Optional hooks, isolated errors, except where safety needs "no".** A plugin is any object with some of the hook methods. Errors in most hooks become a `plugin_error` event, so one bad plugin cannot break a run. But `tool_call` fails closed, because it often guards something. Plugins get a small `PluginAPI`, not the whole session, so the core can change inside without breaking them. The cost: hook names are plain strings; a typo like `tool_calls` is silently never called.

## Exercises

1. Write a plugin `class Upper: name = "upper"` with one hook `input(self, text)` that returns `{"text": text.upper()}`. Run a session with a `FakeProvider` and check that the first user message is in upper case. Hint: copy `session(...)` and `DONE` from `apps/cli/tests/test_sockets.py`.
2. Write a plugin whose `tool_call` raises for the tool `bash`. Check that the tool result says `User denied: blocked by plugin ...` and the tool never ran. (The loop puts `User denied:` in front of every block reason, see [ch 08](08-hooks-approval.md).) Then change the hook name to `tool_calls` (a typo). What happens now, and why? Hint: look at `getattr(p, hook, None)` in `_hook`.

## Recap

- A plugin is any object; the session calls a hook only if the method exists.
- `_hook` awaits sync or async hooks and turns errors into `plugin_error` events.
- `tool_call` is the exception: an error blocks the tool (fail closed). First block wins.
- `context` is a chain that changes only the model's view, not history.
- `PluginAPI` is the plugin's handle: tools, prompt sections, custom entries, messages, events.
- The system prompt is built every turn from ordered prompt sections.

**Builds on:** [13 Sessions](13-session.md) · **Next:** [15 Retry](15-retry.md)
