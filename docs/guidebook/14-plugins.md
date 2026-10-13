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

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/session/__init__.py` — `plugin_name`, `PluginAPI`, `AgentSession._hook`, `_context`, `_before_tool_call`, `_after_tool_call`, `_emit`
- `apps/cli/tests/test_sockets.py` — `Rec` and the plugin tests

## Problem

People want many small extras: hide API keys in tool output, a read-only "plan mode", an extra tool, a line in the system prompt, a log of every event. If each extra is an `if` inside `AgentSession`, the session grows without end, and every app gets every extra.

We want a **[plugin](glossary.md#plugin)**: a plain object that the session calls at fixed points. The core stays the same; you add a plugin to a list.

## Naive version

A first try: a list of callbacks, one per tool call.

```python
class Session:
    def __init__(self, agent, plugins=()):
        self.agent, self.plugins = agent, list(plugins)
        agent.before_tool_call = self.before

    async def before(self, call, ctx):
        for p in self.plugins:
            r = p.tool_call(call)          # every plugin must have tool_call
            if r and "block" in r:
                return r["block"]

class NoBash:
    def tool_call(self, call):
        return {"block": "no bash"} if call.name == "bash" else None
```

It blocks `bash` for the fizzbuzz task. Problems:

1. **Every plugin must define every method.** A plugin that only wants events has no `tool_call`. The run does not crash, but it ends with an `AttributeError` error message, and the tool never runs.
2. **One bad plugin breaks the run.** If a plugin's code raises, the whole agent run fails.
3. **Only one hook point.** No way to change the user's text, the messages sent to the model, the system prompt or the tool list.
4. **No access to the session.** A plugin cannot add a tool or save state.

## Step by step: from naive to real

We fix the naive `Session` one problem at a time.

**Step 1 — hooks are optional.** Do not call `p.tool_call(...)` directly. Look it up first with `getattr`, and skip the plugin if it has no such method:

```python
fn = getattr(p, hook, None)
if fn is None:
    return None
```

Now a plugin that only wants events needs only `on_event`. This fixes problem 1.

**Step 2 — sync or async.** Some hooks are plain functions, some are `async`. We wrap the call with `_maybe_await(fn(*args))`. It awaits only when the result can be awaited. Plugin authors can pick either style.

**Step 3 — catch errors in one place.** We put the lookup and the call inside one helper, `_hook`, with a `try`. On error it emits a `plugin_error` event and returns `None`. This fixes problem 2: a bad plugin is reported, but the run goes on.

**Step 4 — but not for safety checks.** For `tool_call`, "skip on error" is wrong. A crashed guard must not let the tool run. So `_hook` gets `isolate=False`, and `_before_tool_call` turns the error into a block:

```python
try:
    r = await self._hook(p, "tool_call", call, isolate=False) or {}
except Exception as e:
    return f"blocked by plugin {plugin_name(p)} ({type(e).__name__}: {e})"
```

**Step 5 — more hook points.** One hook is not enough. We call `_hook` at more fixed places: `input` and `before_agent_start` in `prompt()`, `context` before each model call, `tool_result` after a tool, `tool_update` and `on_event` in `_emit`. This fixes problem 3.

**Step 6 — give plugins a handle.** In `start()`, each plugin's `setup` gets a `PluginAPI` and its own config. With it, the plugin can add tools, prompt sections and saved entries. This fixes problem 4, without handing over the whole session.

The result is the real code below.

## Real design

The code is in `packages/simp_agent/src/simp_agent/session/__init__.py`.

### A plugin is any object; hooks are optional methods

There is no base class. A plugin is any object. Its name is `p.name` or its class name:

```python
def plugin_name(p) -> str:
    return getattr(p, "name", type(p).__name__)
```

The session calls a **[hook](glossary.md#plugin-hook)** only if the plugin has a method with that name. All calls go through one helper, `_hook`:

```python
    async def _hook(self, p, hook: str, *args, isolate: bool = True):
        fn = getattr(p, hook, None)
        if fn is None:
            return None
        try:
            return await _maybe_await(fn(*args))
        except Exception as e:
            if not isolate:
                raise
            await _emit_all(self._subs, {"type": "plugin_error", "plugin": plugin_name(p), "hook": hook,
                                         "error": f"{type(e).__name__}: {e}"})
            return None
```

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

```python
        for p in self.plugins:
            await self._hook(p, "setup", PluginAPI(self, plugin_name(p)), self.plugin_config.get(plugin_name(p), {}))
        for p in self.plugins:
            await self._hook(p, "session_start")
```

`plugin_config` is a dict keyed by plugin name. Each plugin sees only its own part.

**`context` is a chain.** Before each model call:

```python
    async def _context(self, view: list) -> list:
        for p in self.plugins:  # chained: each gets the previous output
            view = await self._hook(p, "context", list(view)) or view
        return view
```

Each plugin gets the output of the one before. It gets a *copy* of the list (`list(view)`), and the result is only the **[view](glossary.md#view-llm-view)** sent to the model. The saved history does not change. If a plugin fails or returns `None`, the chain keeps the previous view.

**`tool_call` fails closed.** This one is different:

```python
    async def _before_tool_call(self, call, ctx) -> str | None:
        for p in self.plugins:  # first block wins; a raising hook blocks (fail closed)
            try:
                r = await self._hook(p, "tool_call", call, isolate=False) or {}
            except Exception as e:
                return f"blocked by plugin {plugin_name(p)} ({type(e).__name__}: {e})"
            if "block" in r:
                return f"blocked by plugin {plugin_name(p)}: {r['block']}"
            if "args" in r:
                call.arguments = r["args"]
        ...  # then the approval check from ch 08
```

Here `isolate=False`. If a plugin's `tool_call` raises, the tool is **blocked**. Why? A `tool_call` hook is often a safety check. If the check crashes, running the tool anyway would be unsafe. So for this one hook, an error means "no". This is called **[fail closed](glossary.md#fail-closed)**. The first plugin that blocks wins. Plugins run before the user approval from [08](08-hooks-approval.md), so a blocked call never asks the user.

**`tool_result` merges.** Each plugin can return a few fields, and they are merged with `dataclasses.replace`:

```python
    async def _after_tool_call(self, call, result, ctx):
        for p in self.plugins:  # partial overrides, merged in order
            if r := await self._hook(p, "tool_result", call, result):
                result = dataclasses.replace(result, **r)
        return result
```

**`input` can handle a command.** In `prompt()`, if a plugin returns `{"handled": True}`, the session returns `[]` and the model is never called. This is how a plugin can own a slash command like `/plan`.

### PluginAPI: what a plugin may do

A plugin does not get the whole session. It gets a **[PluginAPI](glossary.md#pluginapi)**:

```python
class PluginAPI:
    """What a plugin can do with its session (pi ExtensionAPI)."""

    def __init__(self, session: "AgentSession", name: str):
        self._s, self.name = session, name

    def register_tool(self, tool) -> None:
        self.unregister_tool(tool.name)
        self._s.agent.tools.append(tool)
    ...
    def add_prompt_section(self, id: str, value, order: int = 100) -> None:
        self._s.add_prompt_section(id, value, order)
    ...
    async def append_entry(self, type: str, data: dict) -> CustomEntry:
        return await self._s.append_entry(type, data)
```

The full list: `register_tool`, `unregister_tool`, `add_prompt_section`, `remove_prompt_section`, `append_entry` ([CustomEntry](13-session.md)), `send_message` (steer, follow-up or a new prompt), `set_model`, `abort`, `get_messages`, `env`, `cwd`, and `emit` (send a custom event tagged with the plugin name). A small, named surface is easier to keep stable than "here is the whole session".

### Prompt sections

The system prompt is built every turn from ordered **[prompt sections](glossary.md#prompt-section)**. [Ch 13](13-session.md#prompt-sections-the-system-prompt-rebuilt-every-turn) shows how they work. What is new here: a plugin adds its own section with `api.add_prompt_section(id, value, order)`. The default order is 100, so it comes after `coding` (0) and `context_file` (10). Plan mode uses 1000, so it comes last ([18](18-profiles-plugins.md)).

### Plugin events

`_emit` also feeds plugins:

```python
    async def _emit(self, e: dict) -> None:
        if e["type"] == "tool_execution_update":
            for p in self.plugins:  # e.g. mask secrets before the UI and logs see them
                if (r := await self._hook(p, "tool_update", e["call"], e["text"])) is not None:
                    e = {**e, "text": r}
        await _emit_all(self._subs, e)
        for p in self.plugins:
            await self._hook(p, "on_event", e)
```

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
- The chain: `p1` adds `"A"`, `p3` sees `"A"` and adds `"AB"`. The model (a `FakeProvider`, [02](02-fake-provider.md)) got `["hi", "A", "AB"]`.
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
