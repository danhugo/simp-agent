# Glossary

Every term in this book is defined here, once. Chapters link to these entries the first time
they use a term. Terms are in A–Z order. "Home" is the chapter that explains the term in full.

Verified at commit: `d74b7ee`.

## Agent loop
The cycle at the heart of simp-agent: send the [messages](#message) to the model, get a reply,
run any [tool](#tool) calls in the reply, add the results, and go again. It stops when the
model's reply has no tool calls, or on an error or abort. Each pass is one [turn](#turn).
Code: `agent_loop()` in `packages/simp_agent/src/simp_agent/agent/__init__.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Compaction
Making a long [history](#history) fit in the model's context window. Old messages are
summarized by one extra LLM call; a `CompactionEntry` with the summary is *added* to the
history (nothing is deleted). Before each LLM call, the model sees the summary plus the recent
messages only. The [session](#session) compacts automatically when the history gets close to
the window (`context_window - reserve_tokens`), after a "context too long" error, or when you
ask for it. Code: `packages/simp_agent/src/simp_agent/agent/compaction.py`, `AgentSession.compact()`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Execution environment
Where [tools](#tool) read and write files and run commands. In code it is the `ExecutionEnv`
protocol. The library ships one: `LocalEnv`, which uses this machine (optionally limited to
one root folder). The server's [sandbox](#sandbox) gives each session its own environment.
Code: `packages/simp_agent/src/simp_agent/agent/env.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 23 Sandboxes.

## History
The full, saved list of a [session's](#session) entries: [messages](#message), compaction
markers, and plugin data. It is append-only: entries are added, never changed or removed.
What is sent to the model is built from it each turn (see [compaction](#compaction)).
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Message
One item in a conversation. There are three kinds that the model sees:
- **user message** — text from you (or from the app on your behalf);
- **assistant message** — the model's reply: text, optional thinking, and tool calls;
- **tool result message** — the output of one tool call, sent back to the model.

The [history](#history) can also hold two kinds the model never sees directly:
`CompactionEntry` (see [compaction](#compaction)) and `CustomEntry` (data saved by an app or
[plugin](#plugin)). Code: `packages/simp_agent/src/simp_agent/ai/__init__.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Plugin
Code that adds behaviour to a [session](#session) without changing the core. A plugin is an
object with optional hooks (for example `setup`, `tool_call`, `tool_result`, `context`). Through
`PluginAPI` it can add or remove tools, add text to the system prompt, save data in the history,
and send messages. Two ship with the library: `redact_secrets` (masks secrets) and `plan_mode`
(blocks `write`, `edit`, `bash`). The server also has its own plugin slots — Sandbox, Store,
Auth — set in the `[plugins]` table of `settings.toml`; those are a different kind (chapter 36).
Code: `packages/simp_agent/src/simp_agent/session/__init__.py`, `packages/simp_agent/src/simp_agent/plugins/`.
Introduced in [00](00-introduction.md#2-what-simp-agent-is-not). Home: 35 Extending: tools and agent plugins.

## Profile
A named set of model settings: `api`, `model`, `base_url`, `context_window`, `max_tokens`,
`api_key_env` (the *name* of the environment variable that holds the key — never the key
itself), and optional prices. The CLI reads profiles from `~/.simp-agent/settings.json`; the
server reads them from `[profiles.<name>]` in `settings.toml`. Both turn a profile into a model
with `build_model()` in `packages/simp_agent/src/simp_agent/session/profile.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 21 Configuration reference.

## Provider
The adapter that talks to one LLM API and turns its reply into simp-agent [messages](#message)
and stream events. Built in: `anthropic-messages`, `openai-completions`, `openai-responses`.
More can be added with `register_provider()`. A provider never raises an error; failures come
back as an assistant message with `stop_reason="error"`.
Code: `packages/simp_agent/src/simp_agent/ai/__init__.py`, `packages/simp_agent/src/simp_agent/ai/providers/`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 34 Extending: providers.

## Sandbox
The server's way to give each [session](#session) its own [execution environment](#execution-environment),
with files in `<data_dir>/workspaces/<session_id>`. Two exist: `LocalSandbox` (a folder on the
server machine — no isolation, fine for one person) and `DockerSandbox` (a locked-down Docker
container per session — needed for several users). The CLI does not use a sandbox; its tools run
on your machine. Code: `apps/server/src/simp_server/server.py` (`Sandbox`, `LocalSandbox`),
`apps/server/src/simp_server/sandboxes/docker.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 23 Sandboxes.

## Session
One conversation with the agent, with its saved [history](#history). In code it is
`AgentSession`: it owns the [agent loop](#agent-loop) and adds automatic
[compaction](#compaction), retry on temporary errors, saving each entry right away, tool
approval, and [plugins](#plugin). The CLI saves sessions as JSONL files in
`~/.simp-agent/sessions/`; the server saves them in SQLite.
Code: `packages/simp_agent/src/simp_agent/session/__init__.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Tool
An action the model can ask for, such as reading a file. A tool has a name, a description, a
JSON schema for its arguments, and an `execute` function. The model sends a tool call; the
[agent loop](#agent-loop) checks the arguments, runs the tool, and sends back a tool result
[message](#message). The seven built-in tools are `read`, `write`, `edit`, `bash`, `grep`,
`find`, `ls`. By default `write`, `edit` and `bash` need your approval when the app asks for it.
Code: `AgentTool` in `packages/simp_agent/src/simp_agent/agent/__init__.py`,
`packages/simp_agent/src/simp_agent/coding/tools.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 35 Extending: tools and agent plugins.

## Turn
One pass of the [agent loop](#agent-loop): one LLM call, then running the tool calls in its
reply. A single prompt can take many turns.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.
