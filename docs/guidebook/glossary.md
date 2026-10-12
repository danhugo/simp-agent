# Glossary

Every term in this book is defined here, once. Chapters link to these entries the first time
they use a term. Terms are in A–Z order. "Home" is the chapter that explains the term in full.

Verified at commit: `d74b7ee` (entries from 01: `d3d03f6`).

## Access token
A secret string that proves who you are to the server. `simp-server seed --name <name>`
creates a user and prints its token once; `rotate` prints a new one, stops the old one, and lets a revoked user back in.
The web UI sends it as `Authorization: Bearer <token>`. You can also sign in with a username
and password, which gives you a new token for that sign-in.
Code: `apps/server/src/simp_server/server.py`.
Introduced in [01](01-quick-start.md#43-make-a-user). Home: [22 Users and accounts](22-users.md).

## Agent loop
The cycle at the heart of simp-agent: send the [messages](#message) to the model, get a reply,
run any [tool](#tool) calls in the reply, add the results, and go again. It stops when the
model's reply has no tool calls, or on an error or abort. Each pass is one [turn](#turn).
Code: `agent_loop()` in `packages/simp_agent/src/simp_agent/agent/__init__.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Budget
The money limits the server puts on LLM calls: a most per user per day and a most per [run](#run). Cost is tokens × the [profile](#profile) prices. The check is soft (see the box in the home chapter). Home: [24 Money and limits](24-money.md).

## Compaction
Making a long [history](#history) fit in the model's context window. Old messages are
summarized by one extra LLM call; a `CompactionEntry` with the summary is *added* to the
history (nothing is deleted). Before each LLM call, the model sees the summary plus the recent
messages only. The [session](#session) compacts automatically when the history gets close to
the window (`context_window - reserve_tokens`), after a "context too long" error, or when you
ask for it. Code: `packages/simp_agent/src/simp_agent/agent/compaction.py`, `AgentSession.compact()`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Context file
A Markdown file in the working folder whose text is added to the [system prompt](#system-prompt). The agent tries `AGENTS.override.md`, `AGENTS.md`, `AGENTS.MD`, `CLAUDE.md`, `CLAUDE.MD` in that order and uses the first one found. It looks in the working folder only and reads it once, at the first message of a session.
Code: `load_context_file()` in `packages/simp_agent/src/simp_agent/coding/__init__.py`.
Introduced in [13](13-working-well.md#1-give-standing-rules-with-agentsmd--both). Home: [13 Working well with the agent](13-working-well.md).

## Context window
The most text (in tokens) the model can read at one time: the [system prompt](#system-prompt) plus the [history](#history) it is sent. When the history gets close to it, the session [compacts](#compaction).
Code: `context_window` on the model, used in `packages/simp_agent/src/simp_agent/agent/compaction.py`.
Introduced in [13](13-working-well.md#3-long-sessions-and-compaction--both). Home: 31 How one turn flows.

## Execution environment
Where [tools](#tool) read and write files and run commands. In code it is the `ExecutionEnv`
protocol. The library ships one: `LocalEnv`, which uses this machine (optionally limited to
one root folder). The server's [sandbox](#sandbox) gives each session its own environment.
Code: `packages/simp_agent/src/simp_agent/agent/env.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: [23 Sandboxes](23-sandboxes.md).

## Fake LLM
A scripted model built into the server, for trying the web UI or testing with no API key.
Start it with `simp-server run --fake-llm` (or `make dev ARGS=--fake-llm`). It echoes your
text, runs a `bash` tool call when your message starts with `tool`, and streams slowly when it
starts with `slow`. It needs no key, but the server still needs one [profile](#profile). Not the
same as `FakeProvider`, the library's scripted model for tests (chapter 37).
Code: `apps/server/src/simp_server/fakellm.py`.
Introduced in [01](01-quick-start.md#42-add-a-profile). Home: 37 Testing and evals.

## Follow-up
In the [REPL](#repl), a message typed as `>> text` while the agent is running. It waits
until the agent is done, then starts a new turn. Compare [steer](#steer).
Code: `route()` in `apps/cli/src/simp_cli/__init__.py`.
Introduced in [10](10-cli.md#3-the-repl). Home: [10 The CLI](10-cli.md).

## History
The full, saved list of a [session's](#session) entries: [messages](#message), compaction
markers, and plugin data. It is append-only: entries are added, never changed or removed.
What is sent to the model is built from it each turn (see [compaction](#compaction)).
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Kill switch
The `simp-server pause` command. It makes a `PAUSED` file, and every LLM call is refused until `simp-server resume`. Home: [24 Money and limits](24-money.md#4-kill-switch).

## Layer
One folder under `packages/simp_agent/src/simp_agent/`: `ai`, `agent`, `coding`, `session`, `plugins`,
`testing`, in that order. A layer may import only layers to its left; the library never imports an app.
Checked by `packages/simp_agent/tests/test_layers.py`. Home: [30 Architecture](30-architecture.md).

## Message
One item in a conversation. There are three kinds that the model sees:
- **user message** — text from you (or from the app on your behalf);
- **assistant message** — the model's reply: text, optional thinking, and tool calls;
- **tool result message** — the output of one tool call, sent back to the model.

The [history](#history) can also hold two kinds the model never sees directly:
`CompactionEntry` (see [compaction](#compaction)) and `CustomEntry` (data saved by an app or
[plugin](#plugin)). Code: `packages/simp_agent/src/simp_agent/ai/__init__.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Plan mode
A switch on a [session](#session) that makes the agent read-only: it can look at files and
plan, but its editing and command [tools](#tool) are blocked. In the web UI it is the **Plan**
button; the setting is saved with the session. Code: `PlanMode` in
`packages/simp_agent/src/simp_agent/plugins`, `SetPlanMode` in `apps/server/src/simp_server/server.py`.
Introduced in [11](11-web.md#4-plan-mode). Home: [11 The web UI](11-web.md).

## Plugin
Code that adds behaviour to a [session](#session) without changing the core. A plugin is an
object with optional hooks (for example `setup`, `tool_call`, `tool_result`, `context`). Through
`PluginAPI` it can add or remove tools, add text to the system prompt, save data in the history,
and send messages. Two ship with the library: `redact_secrets` (masks secrets) and `plan_mode`
(blocks `write`, `edit`, `bash`). The server also has its own plugin slots — Sandbox, Store,
Auth — set in the `[plugins]` table of `settings.toml`; those are a different kind (chapter 36).
Code: `packages/simp_agent/src/simp_agent/session/__init__.py`, `packages/simp_agent/src/simp_agent/plugins/`.
Introduced in [00](00-introduction.md#2-what-simp-agent-is-not). Home: 35 Extending: tools and agent plugins.

## Print mode
The CLI's one-shot mode: `simp-agent -p "task"` (or `simp-agent "task"`) runs one task,
prints the answer line by line, and exits. Exit code 1 means an error or abort. Compare
[REPL](#repl). Code: `run()` in `apps/cli/src/simp_cli/__init__.py`.
Introduced in [01](01-quick-start.md#32-make-a-practice-folder). Home: [10 The CLI](10-cli.md).

## Profile
A named set of model settings: `api`, `model`, `base_url`, `context_window`, `max_tokens`,
`api_key_env` (the *name* of the environment variable that holds the key — never the key
itself), and optional prices (`price_in` and `price_out`, USD per 1M tokens; without them calls
cost $0). The CLI reads profiles from `~/.simp-agent/settings.json`; the
server reads them from `[profiles.<name>]` in `settings.toml`. Both turn a profile into a model
with `build_model()` in `packages/simp_agent/src/simp_agent/session/profile.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: [21 Configuration reference](21-configuration.md).

## Provider
The adapter that talks to one LLM API and turns its reply into simp-agent [messages](#message)
and stream events. Built in: `anthropic-messages`, `openai-completions`, `openai-responses`.
More can be added with `register_provider()`. A provider never raises an error; failures come
back as an assistant message with `stop_reason="error"`.
Code: `packages/simp_agent/src/simp_agent/ai/__init__.py`, `packages/simp_agent/src/simp_agent/ai/providers/`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 34 Extending: providers.

## REPL
The CLI's interactive chat ("read–eval–print loop"): run `simp-agent` with no task, type
messages, and use slash commands such as `/help` and `/exit`. Compare [print mode](#print-mode).
Code: `apps/cli/src/simp_cli/repl.py`.
Introduced in [01](01-quick-start.md#34-chat-back-and-forth). Home: [10 The CLI](10-cli.md).

## Run
One piece of server work started by one prompt (or a compact or continue), from start until the agent stops. The run limit of the [budget](#budget) counts per run. Home: [24 Money and limits](24-money.md#2-two-limits).

## Sandbox
The server's way to give each [session](#session) its own [execution environment](#execution-environment),
with files in `<data_dir>/workspaces/<session_id>`. Two exist: `LocalSandbox` (a folder on the
server machine — no isolation, fine for one person) and `DockerSandbox` (a locked-down Docker
container per session — needed for several users). The CLI does not use a sandbox; its tools run
on your machine. Code: `apps/server/src/simp_server/server.py` (`Sandbox`, `LocalSandbox`),
`apps/server/src/simp_server/sandboxes/docker.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: [23 Sandboxes](23-sandboxes.md).

## Session
One conversation with the agent, with its saved [history](#history). In code it is
`AgentSession`: it owns the [agent loop](#agent-loop) and adds automatic
[compaction](#compaction), retry on temporary errors, saving each entry right away, tool
approval, and [plugins](#plugin). The CLI saves sessions as JSONL files in
`~/.simp-agent/sessions/`; the server saves them in SQLite.
Code: `packages/simp_agent/src/simp_agent/session/__init__.py`.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.

## Steer
In the [REPL](#repl), a message typed while the agent is running. The agent reads it before
its next step. Compare [follow-up](#follow-up).
Code: `route()` in `apps/cli/src/simp_cli/__init__.py`.
Introduced in [10](10-cli.md#3-the-repl). Home: [10 The CLI](10-cli.md).

## System prompt
The fixed instructions sent to the model before the [messages](#message) on every call. For the
coding agent it names the tools, gives the working directory and date, and includes your
`AGENTS.md` / `CLAUDE.md` if one exists. It is built again each turn from sections, and
[plugins](#plugin) can add sections (`plan_mode` adds one). It is not part of the history.
Code: `system_prompt()` in `packages/simp_agent/src/simp_agent/coding/__init__.py`,
`AgentSession.add_prompt_section()`.
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

## Tool approval
The question before a risky [tool](#tool) runs. `bash`, `write` and `edit` need approval;
answers are allow, deny, or always (allow this tool for the rest of the session). The CLI asks
`Allow? [y/N/a]`; `--yes` turns it off; the web UI shows buttons.
Code: `approve` in `packages/simp_agent/src/simp_agent/session/__init__.py`.
Introduced in [01](01-quick-start.md#33-see-tool-approval). Home: [10 The CLI](10-cli.md).

## Turn
One pass of the [agent loop](#agent-loop): one LLM call, then running the tool calls in its
reply. A single prompt can take many turns.
Introduced in [00](00-introduction.md#3-the-core-ideas-in-one-picture). Home: 31 How one turn flows.
