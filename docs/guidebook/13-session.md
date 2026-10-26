# 13 Part 4 · Sessions

**Goal:** Keep a conversation across turns and save it.

**Builds on:** [12 Evals](12-evals.md) · **Next:** [14 Plugins](14-plugins.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent --> coding --> session["session ★ AgentSession (this chapter)"] --> plugins --> testing
```

This chapter starts the `session` layer. Big picture of Part 4: [part-4-session](13-0-part-4-session.md).

Yesterday the user asked the agent to write `fizzbuzz.py`. In the middle of the task they closed the CLI. Today they open it again and type "now add tests". At the end of Part 3 we have an `Agent` ([06](06-events-abort.md)) with coding tools ([10](10-coding-tools.md)) and a system prompt ([11](11-system-prompt.md)), but its whole history lives in memory. When the program stopped, the conversation was gone, so today the agent has no idea what `fizzbuzz.py` is.

This chapter adds one object, the **[session](glossary.md#session)**, that owns the agent for a whole conversation and keeps it on disk. We build it by answering five questions.

## What must survive a restart?

The messages. The model has no memory of its own; everything it knows about yesterday is in the list of messages we send it. So if we keep every message (the user's words, each assistant reply, each tool result), we can rebuild the conversation and the agent can go on as if it never stopped.

We keep them as **[JSONL](glossary.md#jsonl)**: one JSON object per line, one line per message. A saved user message looks like this:

```text
{"content": "now add tests", "role": "user"}
```

The `role` field says which kind of message the line is, so we can turn the line back into the right class ([ref-objects](ref-objects.md#going-to-json-and-back)).

## When do we save?

The simple idea is to save the whole list when the run ends. But a run can die in the middle, after the model has already written `fizzbuzz.py`; then nothing is saved, and on resume the model does not know the file exists.

So the session saves each message the moment it is finished: on every `message_end` event ([06](06-events-abort.md)). In one run that happens many times:

| Moment | Finished message | Saved? |
|---|---|---|
| The user sends the question | [1] user: "write fizzbuzz.py" | yes, at once |
| The model is still streaming its reply | (not finished) | no |
| The model's reply ends: it asks for `write` | [2] assistant: tool call `write fizzbuzz.py` | yes, at once |
| The `write` tool is done; the file exists | [3] tool result: "Wrote 120 chars to fizzbuzz.py" | yes, at once |
| The model's last reply ends | [4] assistant: "Done." | yes, at once |

Each save adds one line at the end and never rewrites old lines. So if the program dies after [3], the history already shows that `fizzbuzz.py` was written; a crash loses at most the one message that was still being written.

Real code: [session/\_\_init\_\_.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `_on_agent_event`

## Where do we save?

Not every app wants a file. Tests want a list in memory, the CLI wants files, and the server wants a database ([22](22-store-auth.md)). So the session does not know where things go. It only talks to a **[SessionStore](glossary.md#sessionstore)**, which is anything with two methods:

```python
class SessionStore(Protocol):
    def append(self, entry) -> Any: ...   # save one entry; may be async
    def load(self) -> list: ...           # give back all entries
```

`Protocol` is Python's way to say "any class with these methods fits"; the store does not need to inherit from anything. A list in memory is already a full store, and the tests use exactly that (`ListStore`). A database store needs `await` and a list does not, so the session accepts both, with the same [`_maybe_await`](glossary.md#_maybe_await) helper as the hooks in [08](08-hooks-approval.md). Besides messages, `append` also gets a few entries that are saved but never sent to the model, like a plugin's [custom entry](glossary.md#custom-entry) ([14](14-plugins.md)).

The CLI's store is `JsonlStore`. Its `append` opens the file in `"a"` mode (add at the end), writes one line and closes the file, so the line is on disk right away. Its `load` reads the lines back into messages. Each project folder has its own sessions, in `~/.simp-agent/sessions/<cwd-slug>/<id>.jsonl`, where `session_dir(cwd)` turns the project path into a folder name (`/home/me/project` becomes `home-me-project`).

Real code: [simp_cli/\_\_init\_\_.py](../../apps/cli/src/simp_cli/__init__.py) — `JsonlStore`, `session_dir`

## How does the user come back?

The session never loads by itself. The app does, because only the app knows *which* conversation the user wants: an id they typed, the latest one, or a new one. (The CLI's `latest_session(cwd)` picks the newest file for this folder.) The app loads it and passes the list in:

```python
AgentSession(model, store=store, messages=store.load())
```

Now the user types "now add tests" and the app calls `session.prompt(text)`: a new user message, and the agent runs. Sometimes there is no new message to add. The run stopped on an error, or the last saved message is a tool result the model never answered. Then the app calls `session.continue_()`, which runs the agent again on the same history. The CLI does this when it resumes with no task. Retry in [15](15-retry.md) uses the same call.

## Why does the session own the agent?

Without a session, the CLI and the server would each have to build the `Agent`, plug in the store, wire the hooks and subscribe to events, the same code twice. `AgentSession` does this once. It builds one `Agent` with good defaults (the coding tools of [10](10-coding-tools.md), `LocalEnv` of [09](09-exec-env.md), the coding prompt of [11](11-system-prompt.md)), fills the agent's hooks from [08](08-hooks-approval.md) with its own methods (`_before_tool_call`, `_after_tool_call`, and `_prepare` for `prepare_next_turn`), and is the one place where apps `subscribe`. It does not copy the loop. Later chapters (plugins, retry, compaction) add their features inside these methods, and the loop never changes.

`session.messages` is the agent's own list, so there is one history, not two copies that could drift apart.

Some setup needs `await`, and `__init__` cannot await. So it lives in `start()`, which `prompt` and `continue_` call first and which runs only once. The main job here: read the [context file](glossary.md#context-file) `AGENTS.md` ([11](11-system-prompt.md)) and add it to the prompt. So `AGENTS.md` is read **once per session**; if you edit it, the change shows up in a new session.

Real code: [session/\_\_init\_\_.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession.__init__`, `start`, `prompt`, `continue_`

## Prompt sections

`start()` adds `AGENTS.md` as a **[prompt section](glossary.md#prompt-section)**. The session builds the system prompt from a small table of sections. Each section has an id, an order and a value: a string, or a function that makes the string. To build the prompt, the session sorts the sections by order, skips empty ones and joins them with a blank line. With the default prompt and an `AGENTS.md` that says `use tabs`, the model gets:

```text
You are an expert coding assistant. ...   <- section "coding", order 0

# Project Context                         <- section "context_file", order 10

## /home/me/project/AGENTS.md

use tabs
```

The `coding` section is a function, so it always uses the current tools and folder. If the app passes its own `system_prompt` string, that becomes the only base section and no coding text or `AGENTS.md` is added.

A plugin adds its own section with `add_prompt_section(id, value, order)`; the default order 100 puts it after these two. Adding the same id again replaces the text but keeps its place. Because the prompt is rebuilt before every model call ([11](11-system-prompt.md#why-is-the-prompt-a-function-not-a-fixed-string)), a change shows up on the next turn. Plugins come in [14](14-plugins.md); plan mode in [18](18-profiles-plugins.md) is a full example of a section turned on and off.

Real code: [session/\_\_init\_\_.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `add_prompt_section`, `remove_prompt_section`, `_build_prompt`

**Next:** [14 Plugins](14-plugins.md) — plugins use the session's hooks and prompt sections.
