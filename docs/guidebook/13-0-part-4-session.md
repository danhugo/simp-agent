# Part 4 big picture: the session layer

**In one sentence:** Part 4 builds `AgentSession`, one object that owns an `Agent` for a whole conversation: it saves every message, lets plugins join in, and fixes errors, so a chat can last for days.

Read this page before [13](13-session.md). Come back to it any time you get lost in [13](13-session.md)–[18](18-profiles-plugins.md). It adds no new facts. The plain walk-through comes first; the map (picture and tables) is at the end.

## Example: the user comes back the next day

Yesterday the user asked **"What is in README.md?"** and then asked the agent to write `fizzbuzz.py`. Today they open the app again and type **"now add tests"**.

After Part 3 we have an agent that can read files, run commands and answer. But everything lives in memory. When the app closes, the history is gone, so today the agent has no idea what `fizzbuzz.py` is. There are more problems that only show up in long, real use. The model API may say "too many requests" (`429`) for a moment, and the run just stops. After many turns the history grows bigger than the model's window, and the model refuses the call. Every team wants something a little different (hide secrets, a "plan first" mode), and they should not have to edit the loop for it. And each app needs a way to pick the model from a settings file.

Somebody must keep the history on disk, give it back the next day, retry short failures, shrink the history when it gets too big, and let small add-ons hook in. **That "somebody" is the session.**

## The core idea

The agent loop from Part 2 stays the same. The session wraps it from the outside, and talks to it only through the hooks the loop already has: `prepare_next_turn`, `before_tool_call`, `after_tool_call`, the system prompt function and the events. Nothing in Part 2 changes.

The second idea is that history is only ever added to, never changed. Each finished message is written to the [store](glossary.md#sessionstore) the moment it ends, so a crash loses at most the message in progress. When the history gets too big we do not delete old messages; we add a summary marker, and the model sees a shorter *view* built from the full history.

## What each chapter adds

**[13 Sessions](13-session.md): keep the chat.** 13 builds `AgentSession`. It owns one `Agent`, saves each finished message to a `SessionStore`, loads it back the next day, and builds the system prompt from named [prompt sections](glossary.md#prompt-section). It also writes [tool approval](glossary.md#tool-approval) as one `before_tool_call` hook (shown early in [08](08-hooks-approval.md)).

**[14 Plugins](14-plugins.md): let add-ons hook in.** A [plugin](glossary.md#plugin) is any object with methods of known names, such as `input`, `context`, `tool_call` or `tool_result`. The session calls them at the right moment. Through the [PluginAPI](glossary.md#pluginapi) a plugin may add tools, prompt sections or saved entries.

**[15 Retry](15-retry.md): survive short failures.** When the last message is a retryable error (like `429`), the session waits 2 s, 4 s, 8 s… and calls `agent.continue_()`, up to 3 times.

**[16 Compaction](16-compaction.md): shrink a long history.** When the history is near the model's window, the session asks the model for a summary, saves a `CompactionEntry`, and from then on sends only the summary plus recent messages.

**[17 Context overflow](17-overflow.md): recover when it is too late.** If the model still says "prompt is too long", the session compacts once and continues, instead of stopping.

**[18 Profiles and built-in plugins](18-profiles-plugins.md): make it usable.** A [profile](glossary.md#profile) is a plain dict from the settings file; `build_model()` turns it into a `Model`. `build_plugins()` turns plugin names into objects, and two real plugins ship: `RedactSecrets` and `PlanMode`.

## The map

### The picture

![The session layer: blocks, objects and chapters](img/part-4-session.svg)

Read the top row left to right: the task goes in, and each model turn is prepared. The grey box is the agent loop from Part 2. Then read the bottom row right to left: tools run, messages are saved, and errors are fixed. Blocks are steps. Cards on the arrows are the data passed between steps. Purple tags say which chapter builds the block.

### The blocks

| # | Block | What it does | IN | OUT | Code (file · function) | Chapter |
|---|---|---|---|---|---|---|
| 1 | Build | Turn a profile dict into a `Model`, and plugin names into plugin objects. The app then makes the `AgentSession`. | profile dict, plugin names | `Model`, plugin list | `packages/simp_agent/src/simp_agent/session/profile.py` · `build_model()`; `packages/simp_agent/src/simp_agent/plugins/__init__.py` · `build_plugins()` | [18](18-profiles-plugins.md) |
| 2 | Start | Once, before the first prompt: add the context file as a prompt section, call each plugin's `setup(api, config)`, then `session_start`. | plugins, `plugin_config` | plugins ready, prompt sections | `packages/simp_agent/src/simp_agent/session/__init__.py` · `AgentSession.start()` | [13](13-session.md), [14](14-plugins.md) |
| 3 | Input hooks | Each plugin may change the text (`input`), say "handled", or add extra messages (`before_agent_start`). | task text | text + extra messages | `packages/simp_agent/src/simp_agent/session/__init__.py` · `AgentSession.prompt()` | [14](14-plugins.md) |
| 4 | Prepare view | Each turn: if history is too big, compact it. Then build the LLM view and pass it through each plugin's `context` hook. | full history | LLM view (list of messages) | `packages/simp_agent/src/simp_agent/session/__init__.py` · `_prepare()`, `_context()`; `packages/simp_agent/src/simp_agent/agent/compaction.py` · `should_compact()`, `compact()`, `build_view()` | [16](16-compaction.md), [14](14-plugins.md) |
| 5 | Build prompt | Each turn: join all prompt sections, sorted by `order`, into one system prompt. | prompt sections | system prompt string | `packages/simp_agent/src/simp_agent/session/__init__.py` · `_build_prompt()` | [13](13-session.md) |
| 6 | Tool hooks | Before a tool runs: plugin `tool_call` may block or change args, then ask for approval. After: plugin `tool_result` may change the result. | `ToolCall`, result | allowed or blocked; final result | `packages/simp_agent/src/simp_agent/session/__init__.py` · `_before_tool_call()`, `_after_tool_call()` | [14](14-plugins.md) |
| 7 | Save + emit | On each `message_end`, append the message to the store. Pass every event to subscribers and to plugin `on_event`. | agent events | lines in the store, events | `packages/simp_agent/src/simp_agent/session/__init__.py` · `_on_agent_event()`, `_emit()` | [13](13-session.md), [14](14-plugins.md) |
| 8 | Recover | If the last message is an error: context overflow → compact once and continue; retryable → wait (2 s, 4 s, 8 s…) and continue, up to `max_retries` (3); else stop. | last `AssistantMessage` | new messages | `packages/simp_agent/src/simp_agent/session/__init__.py` · `_run()`; `packages/simp_agent/src/simp_agent/ai/__init__.py` · `is_context_overflow()`, `is_retryable()` | [15](15-retry.md), [17](17-overflow.md) |

Not numbered: the agent loop (call the model, run tools, repeat) is Part 2, [05](05-agent-loop.md)–[08](08-hooks-approval.md). The real store, `JsonlStore`, lives in the CLI app: `apps/cli/src/simp_cli/__init__.py` ([13](13-session.md)).

### Which block is inside which

`AgentSession` is the whole Part. It holds one `Agent` and gives it three hooks: `prepare_next_turn=_prepare` (block 4), and `before_tool_call` and `after_tool_call` (block 6). The system prompt (5) is also a function the agent calls each turn. `prompt()` is Start (2) + Input hooks (3) + `_run()`; `continue_()` is the same without the Input hooks. `_run()` runs the start function once (`agent.prompt` or `agent.continue_`), then Recover (8) loops while the last message is an error. One agent turn is Prepare view (4) + Build prompt (5) + the model call + Tool hooks (6). Save (7) happens on every `message_end` event.

Compaction is used in two places: in Prepare view (4) when the history is near the window, and in Recover (8) after an overflow error. Both call the same `AgentSession.compact()`. Build (1) is outside the session: the app (CLI or server) calls `build_model` and `build_plugins`, then makes the `AgentSession`. [14](14-plugins.md) adds the plugin sockets; [18](18-profiles-plugins.md) ships two plugins that use them: `RedactSecrets` (hooks `tool_result`, `tool_update`, `context`) and `PlanMode` (hook `tool_call`, a prompt section, a custom entry).

The small chart below shows only the nesting:

```mermaid
flowchart LR
    B["1 Build<br/>build_model, build_plugins (ch18)"] --> S
    subgraph S["AgentSession.prompt()  (ch13)"]
        ST["2 Start (ch13, ch14)"] --> IN["3 Input hooks (ch14)"] --> R
        subgraph R["_run()"]
            subgraph T["one agent turn (Part 2)"]
                V["4 Prepare view (ch16, ch14)"] --> P["5 Build prompt (ch13)"] --> M["model call"] --> H["6 Tool hooks (ch14)"]
            end
            T --> RC["8 Recover (ch15, ch17)"]
            RC -.continue_.-> T
        end
    end
    T -. message_end .-> SV["7 Save + emit (ch13, ch14)"]
```

**Rule for the whole Part:** history is append-only. Compaction adds a `CompactionEntry` and plugins add `CustomEntry`s; nothing is deleted. The LLM sees only the view that `build_view()` makes from it.

### The objects

| Object | Fields | Meaning |
|---|---|---|
| [AgentSession](glossary.md#agentsession) | `agent`, `store`, `plugins`, `plugin_config`, `auto_compact`, `compaction`, `max_retries`, `retry_base_delay`, `approve` | Owns one `Agent` for a whole conversation. |
| [SessionStore](glossary.md#sessionstore) | `append(entry)`, `load()` | Where history is saved. `append` is called once per finished entry. |
| [Profile](glossary.md#profile) | `api`, `model`, `base_url`, `api_key_env`, `compat`, `max_tokens`, `context_window` | A plain dict from the settings file. `build_model` turns it into a `Model`. |
| [Plugin](glossary.md#plugin) | `name` (optional) + any [plugin hooks](glossary.md#plugin-hook) | Any object. A hook is a method with a known name; missing = skipped. |
| [PluginAPI](glossary.md#pluginapi) | `register_tool`, `add_prompt_section`, `append_entry`, `send_message`, `set_model`, `abort`, `get_messages`, `emit`, … | What a plugin may do with its session. |
| [Prompt section](glossary.md#prompt-section) | `id` → (`order`, string or function) | One part of the system prompt, rebuilt every turn. |
| [CustomEntry](glossary.md#custom-entry) | `type`, `data` | Saved and replayed on resume, never sent to the LLM. |
| [CompactionEntry](glossary.md#compaction-entry) | `summary`, `first_kept_index`, `read_files`, `modified_files` | Marker in history: "everything before this index is replaced by this summary". |
| [CompactionSettings](glossary.md#compaction) | `enabled`, `reserve_tokens`, `keep_recent_tokens` | When to compact, and how much recent history to keep. |

### The worked example with all blocks

The same "now add tests" story, now with block numbers. The history is in a JSONL file, and the `redact_secrets` plugin is on.

1. **Build:** the app calls `build_model(profile)` → a `Model`, and `build_plugins(["redact_secrets"])` → `[RedactSecrets()]`. It makes `AgentSession(model, store=JsonlStore(path), messages=store.load(), plugins=...)`. Yesterday's messages are back.
2. **Start:** `AGENTS.md` (if there is one) becomes the `context_file` section. `RedactSecrets.setup` collects secret values from env vars.
3. **Input hooks:** `RedactSecrets` has no `input` hook, so the text stays "now add tests".
4. **Prepare view:** the history is small, so no compaction. `build_view` returns the messages; `RedactSecrets.context` masks secrets in copies.
5. **Build prompt:** the `coding` section + the `context_file` section → one system prompt. The model call runs (Part 2) and asks to `write` `test_fizzbuzz.py`.
6. **Tool hooks:** no plugin blocks `write`; with no `approve` function, it is allowed. After the tool runs, `RedactSecrets.tool_result` finds no secret and returns nothing.
7. **Save + emit:** the assistant message and the tool result each get one new line in the JSONL file as soon as they end.
8. **Recover:** the next model call fails with `429`. It is retryable, so the session emits `auto_retry_start` (attempt 1, delay 2 s), waits, and calls `agent.continue_()`. This time it works; `auto_retry_end` says `success: true`. If the error had been "prompt is too long", the session would compact once instead, then continue.

## Builds on / Next

- Builds on: [Part 3 big picture](09-0-part-3-coding.md), [Part 3 · 11 The system prompt](11-system-prompt.md) and [12 Evals](12-evals.md); the agent loop from [05](05-agent-loop.md)–[08](08-hooks-approval.md).
- Chapters: [13 Sessions](13-session.md) · [14 Plugins](14-plugins.md) · [15 Retry](15-retry.md) · [16 Compaction](16-compaction.md) · [17 Context overflow](17-overflow.md) · [18 Profiles and built-in plugins](18-profiles-plugins.md).
- Next: [Part 5 big picture](19-0-part-5-system.md), then [19 The CLI](19-cli.md) builds an app on top of `AgentSession`.
