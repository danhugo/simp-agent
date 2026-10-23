# Glossary

Terms are added here as chapters define them. Each entry links to the chapter that defines it.

## choices
The list of answers in one Chat Completions chunk. We ask for one answer, so we read `choices[0]`; each choice has `delta`, `finish_reason` and `index`. The last chunk may have `choices = []` and carry only `usage`. Home: [03](03-parse.md#problem-and-goal).

## Coding agent
A program that takes a task in plain words, asks a language model what to do, runs the tools the model asks for (read, write, run commands), and repeats until done. Home: [00](00-overview.md).

## Item (Responses)
One piece of an OpenAI Responses answer, with its own id: a reasoning item (`rs_...`, encrypted), a text `message` item (`msg_...`) or a `function_call` item (`fc_...`). See [chapter 2](02-translate-send.md).

## Layer
One folder of the `simp_agent` library (`ai`, `agent`, `coding`, `session`, `plugins`, `testing`). A layer imports only layers to its left; `test_layers.py` checks this. Home: [00](00-overview.md#the-layer-map).

## Tool call
A request from the model to execute one named tool with arguments (class `ToolCall` in `ai`). Home: [00](00-overview.md); built in [01](01-pick-clean.md).

## Message
One entry in a conversation: `UserMessage`, `AssistantMessage` or `ToolResultMessage` (all in `ai`). Each has a `role` field so it can be saved to JSON and loaded back with `to_dict` / `from_dict` ([JSON round trip](ref-objects.md#going-to-json-and-back)). Home: [01](01-pick-clean.md#what-is-inside-messages); all fields: [ref-objects](ref-objects.md).

## Context
Everything sent to a model in one request: system prompt, messages and tools (class `Context` in `ai`). Home: [01](01-pick-clean.md#in-model-and-context).

## Model
Which model to call and how (class `Model` in `ai`): `id`, `provider`, `api`, `max_tokens`, `context_window`, `base_url`, `api_key_env`, `compat`. `api` picks the provider. Home: [01](01-pick-clean.md#in-model-and-context); all fields: [ref-objects](ref-objects.md#request-objects-tool-context-model); overview: [Part 1](01-0-part-1-ai.md).

## Tool
What the model is told about one tool (class `Tool` in `ai`): `name`, `description`, `parameters` (JSON schema). Home: [ref-objects](ref-objects.md#request-objects-tool-context-model).

## AssistantMessage
The model's reply: `content` blocks (`TextContent`, `ThinkingContent`, `ToolCall`), `stop_reason`, `usage`, `error`, `error_kind`, and `api`/`provider`/`model` stamped by `ai.stream`. Home: [01](01-pick-clean.md#what-is-inside-messages), fields: [ref-objects](ref-objects.md#messages); overview: [Part 1](01-0-part-1-ai.md).

## Stream event
One dict yielded by a stream function: `start`, `text_delta`, `thinking_start/delta/end`, `toolcall_start/delta/end`, then `done` or `error` with the final `AssistantMessage`. Not the same as an agent [event](#event). Home: [03](03-parse.md); overview: [Part 1](01-0-part-1-ai.md).

## Compaction entry
A history marker (`CompactionEntry`) that says "messages before `first_kept_index` are replaced by this summary". Never sent to the model as-is. Defined in [ref-objects](ref-objects.md#two-history-entries-that-are-not-messages); built in [16](16-compaction.md).

## Custom entry
A history entry (`CustomEntry`) where apps and plugins keep their own data. Saved and replayed, never sent to the model. Defined in [ref-objects](ref-objects.md#two-history-entries-that-are-not-messages); used in [14](14-plugins.md).

## Provider
The code that talks to one model vendor's API and turns its answer into our events and messages. Every provider is a stream function. Defined in [01](01-pick-clean.md#out-the-shape-of-a-model-call); built in [02](02-translate-send.md) and [03](03-parse.md); faked in [04](04-label-test.md#testing-the-pipeline-without-a-real-model).

## Stream function
An async function `(model, context, api_key=None)` that yields event dicts and ends with a `done` or `error` event holding the final `AssistantMessage`. It never raises. The loop takes it as the `stream_fn` setting. Home: [01](01-pick-clean.md#out-the-shape-of-a-model-call).

## Scripted reply
One answer given in advance to `FakeProvider`; replies are played in order, one per model call. A reply is a message or a function `(ctx) -> message`. Home: [04](04-label-test.md#a-script-of-replies).

## Delta
One small piece of a streamed model answer (a bit of text, thinking, or tool-call arguments). The stream parser joins deltas into one `AssistantMessage` and yields each one as a `*_delta` event. Home: [03](03-parse.md).

## Usage
The token count of one model call, kept in `AssistantMessage.usage` as `{"input", "output", "reasoning"}`. `reasoning` is already inside `output`. Home: [03](03-parse.md#usage).

## Agent loop
The loop that calls the model, executes the tool calls it asks for, adds the results, and calls the model again until it stops asking (`agent_loop` in `agent`). Built in [05](05-agent-loop.md#agent_loop-the-loop).

## History
The list of all messages in one chat so far: user questions, model replies, tool results. The `Agent` keeps it (`agent.messages`) and sends it to the model every turn, because the model remembers nothing between calls. See [Part 2 big picture](05-0-part-2-agent.md).

## Run (agent)
Everything from the user's message until the loop stops: one call to `agent.prompt()` (or `agent.continue_()`), or one `agent_loop` call; normally `agent_start` … `agent_end`. One run has one or more [turns](#turn), and a turn has zero or more [tool calls](#tool-call). The noun "run" means only this whole run: a tool *executes*, and the model makes a *model call*. (`run_tool` executes one tool call; it is not a whole run.) Queued follow-ups stay in the same run ([07](07-steering.md)). Not the same as the server [Run](#run) object. Home: [05](05-agent-loop.md#problem).

## Turn
One pass of the agent loop: one model call plus the tool calls it asked for. Starts with a `turn_start` event, ends with `turn_end`. Home: [05](05-agent-loop.md#agent_loop-the-loop).

## Agent tool
An `ai.Tool` (name, description, JSON schema) plus `execute(args, ctx) -> str` and an optional `prepare_arguments` (class `AgentTool` in `agent`). Run by `run_tool`, which turns every failure into an error tool result. Home: [05](05-agent-loop.md#tools-agenttool).

## Tool context
The object a tool gets when it runs (`ToolContext`): `cancel`, `env`, `cwd`, `on_update`. Home: [05](05-agent-loop.md#toolcontext-what-a-tool-gets).

## Execution environment
The one object (`ExecutionEnv`, default `LocalEnv`) through which tools read files and run commands. Given to tools in the tool context. Defined in [05](05-agent-loop.md#toolcontext-what-a-tool-gets); built in [09](09-exec-env.md).

## Path safety
The rule that, when `LocalEnv` has a `root`, a file path may not leave it. `_path` resolves `..` and symlinks first, then raises `PermissionError` if the path is outside the root. Files only: `exec` is not checked. Home: [09](09-exec-env.md#step-3-_path-checks-the-path).

## Process-group kill
How `exec` stops a command: the shell starts in a new process group (`start_new_session=True`), and `run_kill` sends `SIGKILL` to the whole group until it is empty, so background children die too. Home: [09](09-exec-env.md#step-5-stop-kills-the-whole-group).

## Provider registry
The dict `_PROVIDERS` in `ai` that maps a `Model.api` string (`anthropic-messages`, `openai-completions`, `openai-responses`) to a stream function. `register_provider` adds or replaces one; `ai.stream` looks it up. Home: [01](01-pick-clean.md#1-pick-_providers-register_provider).

## Context overflow
An error that says the request is bigger than the model's context window. Found by `is_context_overflow`; never retried as-is. Defined and handled in [17](17-overflow.md#detecting-overflow).

## Event
A small dict with a `"type"` key (`agent_start`, `turn_start`, `message_update`, `message_end`, `tool_execution_start`, `turn_end`, `agent_end`, …) that the agent loop sends through `emit` so callers can watch a run. `Agent.subscribe` adds a listener. Home: [06](06-events-abort.md#events-one-stream-of-small-dicts).

## Abort
Stopping a run in the middle by setting one `asyncio.Event` (`cancel`, or `Agent.abort()`). It closes the model stream, stops tools, and ends the run with an assistant message whose `stop_reason` is `aborted`. Home: [06](06-events-abort.md#abort-one-asyncioevent).

## Steer
A user message typed while the agent works, meant to reach the model soon. `Agent.steer(text)` queues it; the loop reads it (through `LoopConfig.get_steering`) before the first turn, just before each model call, and after each tool batch. It never cuts a tool batch. Home: [07](07-steering.md#when-each-queue-is-read).

## Safe point
A place in the history where every tool call already has its tool result. Steering messages are added only here (the read points), so the request stays valid. Home: [07](07-steering.md#problem).

## Follow-up
A user message queued to run after the agent would stop. `Agent.follow_up(text)` queues it; the loop reads it (through `LoopConfig.get_follow_up`) only when there are no tool calls and no steering left, and it continues the same run. Home: [07](07-steering.md#two-loops-inner-for-steering-outer-for-follow-ups).

## Queue mode
How many queued messages one read takes: `"one-at-a-time"` (default, the oldest only) or `"all"`. Set by `Agent.steering_mode` and `Agent.follow_up_mode`. Home: [07](07-steering.md#the-agent-side-two-lists-and-a-mode).

## Tool hook
One of two optional functions in `LoopConfig` (and `Agent`) that wrap each tool call: `before_tool_call(call, ctx)` returns `None` to run the tool or a reason string to deny it (the call then gets the error result `User denied: <reason>`); `after_tool_call(call, result, ctx)` may return a new result, and runs after a deny too. Home: [08](08-hooks-approval.md#two-hooks-in-loopconfig).

## Tool approval
Asking a human before a risky tool runs. Built as one `before_tool_call` in `AgentSession`: `approve(call)` answers `"allow"`, `"always"` (remember this tool name) or anything else (deny). Only `bash`, `write` and `edit` ask, and the question ends on abort. Home: [08](08-hooks-approval.md#approval-a-before_tool_call-that-asks-a-human).

## Truncation
How tools keep output small (`coding/truncate.py`): keep whole lines under 2000 lines and 50 KB. `truncate_head` / `head` keep the start (read, ls, grep, find); `truncate_tail` / `tail` keep the end (bash). The wrappers add a note so the model knows it was cut. Home: [10](10-coding-tools.md#truncation-truncate_head-and-truncate_tail).

## System prompt
The first text of every model request: who the model is and how to work. Default made by `coding.system_prompt(tools, cwd)`: role, tool list, short rules, date and cwd. The session rebuilds it every turn from prompt sections. Home: [11](11-system-prompt.md#system_prompt-the-base-text).

## Context file
A project file with rules for agents. The first of `CONTEXT_FILES` (`AGENTS.override.md`, `AGENTS.md`, `AGENTS.MD`, `CLAUDE.md`, `CLAUDE.MD`) found in `cwd`, read through the env, added once as the "Project Context" section. Home: [11](11-system-prompt.md#context_files-and-load_context_file-the-project-file).

## Prompt section
One part of the system prompt in `AgentSession`: an id, an order and a string or `fn(ctx)`. `_build_prompt` sorts them, skips empty ones and joins them before each model call. Introduced in [11](11-system-prompt.md#prompt-sections-building-the-prompt-every-turn); home: [13](13-session.md#prompt-sections-the-system-prompt-rebuilt-every-turn).

## Eval
A test of the real agent with a real model on fixed tasks, checked by a program. It reports pass/fail plus turns, tokens, cost and time. Runner: `evals/run.py`. Home: [12](12-evals.md).

## Eval task
One file in `evals/tasks/*.toml`: a `prompt`, a shell `check` (exit 0 = pass) and optional `[setup]` files written into a fresh temp folder. Home: [12](12-evals.md#a-task-is-a-toml-file).

## Profile
A named model setup in a settings file (`settings.toml` under `[profiles.<name>]` for the server and evals, `~/.simp-agent/settings.json` for the CLI): `api`, `model`, optional `base_url`, `api_key_env`, `price_in` / `price_out` (dollars per million tokens). `build_model` turns it into a `Model`. Used by evals in [12](12-evals.md); home: [18](18-profiles-plugins.md).

## Session
One long conversation with the agent, across many prompts and restarts. Owned by `AgentSession`. Home: [13](13-session.md).

## AgentSession
The class in `session/__init__.py` that owns one `Agent` and adds saving, plugins, retry, compaction and overflow recovery. Home: [13](13-session.md).

## Title call
After the first assistant message, `Run` starts `title_task`: one small model call that names the session, saves it with `store.set_title` and sends a `session_title` event. Home: [20](20-server-run.md#the-title-call).

## SessionStore
A protocol with two methods, `append(entry)` and `load()`: where a session saves its history. `append` may be sync or async. Home: [13](13-session.md).

## JSONL
A file with one JSON object per line. The CLI's `JsonlStore` saves one history entry per line. Home: [13](13-session.md#jsonlstore-the-real-store-in-the-cli).

## `_maybe_await`
A helper in `agent/__init__.py` that awaits a value only if it is awaitable. It lets hooks and stores be sync or async. Home: [08](08-hooks-approval.md); used in [13](13-session.md).

## Append-only history
Finished messages are never changed or removed; new entries are only added at the end. So a store can save each entry once, right away. Home: [13](13-session.md).

## Plugin
Any object passed in `AgentSession(plugins=[...])`; the session calls its hook methods. Home: [14](14-plugins.md).

## Plugin hook
A method name the session calls on a plugin at a fixed point (`setup`, `input`, `context`, `tool_call`, `tool_result`, `on_event`, ...). Home: [14](14-plugins.md).

## Hook isolation
An error in a plugin hook becomes a `plugin_error` event instead of breaking the run. Home: [14](14-plugins.md).

## Fail closed
When a safety check itself fails, treat it as "no" (block the tool). Home: [14](14-plugins.md).

## PluginAPI
The object a plugin gets in `setup`; the actions it may take on its session. Home: [14](14-plugins.md).

## `plugin_error`
The event the session emits when an isolated plugin hook raises; it names the plugin and the hook. Home: [14](14-plugins.md).

## Retry
Calling the model again after a short-lived error, with `continue_()`. Home: [15](15-retry.md).

## Backoff
Waiting longer between each retry; here the wait doubles each time. Home: [15](15-retry.md).

## `error_kind`
A field on `AssistantMessage`; `fatal`, `budget` or `policy` mean "never retry". Home: [15](15-retry.md).

## Jitter
A small random part added to a retry wait, so many clients do not retry at the same moment. simp-agent does not use it (a known limit). Home: [15](15-retry.md).

## Retryable error
An error whose text matches `_RETRYABLE` (429, 5xx, overloaded, network...) and whose kind allows retry. Home: [15](15-retry.md).

## `auto_retry_start` / `auto_retry_end`
Session events sent before each backoff wait and once after the last retry. Home: [15](15-retry.md).

## `NON_RETRYABLE`
The set `{"fatal", "budget", "policy"}` of error kinds that `is_retryable` always rejects. Home: [15](15-retry.md).

## Context window
The most tokens a model can read in one call (`Model.context_window`). Home: [16](16-compaction.md).

## Compaction
Replacing old history in the model's view with a summary. Home: [16](16-compaction.md).

## View (LLM view)
The message list actually sent to the model, built from history by `build_view` and the plugin `context` chain. Home: [16](16-compaction.md).

## `reserve_tokens`
Tokens kept free for the reply and the summary (default 16384). Home: [16](16-compaction.md).

## `keep_recent_tokens`
About how many recent tokens are kept word for word (default 20000). Home: [16](16-compaction.md).

## Incremental summary
Updating the previous summary with only the new messages. Home: [16](16-compaction.md).

## Cut (`first_kept_index`)
The index of the first message kept word for word; always a user or assistant message. Home: [16](16-compaction.md).

## Overflow recovery
How `_run` handles a [Context overflow](#context-overflow): compact once and call the model again. See that entry. Home: [17](17-overflow.md).

## Overflowed flag
The per-run flag in `_run` that allows only one overflow recovery. Home: [17](17-overflow.md).

## `build_model`
`session/profile.py`; turns a profile into a `Model`. Shared by the CLI and the server. Home: [18](18-profiles-plugins.md).

## `build_plugins`
`plugins/__init__.py`; turns plugin names into new plugin objects. Home: [18](18-profiles-plugins.md).

## RedactSecrets
Built-in plugin that replaces secrets with `[REDACTED]`. Home: [18](18-profiles-plugins.md).

## `include_usage`
`Model.compat` flag; asks an OpenAI-style server to send token usage in the stream. `build_model` turns it on by default. Home: [18](18-profiles-plugins.md).

## Plan mode
Built-in plugin (`PlanMode`) that makes the agent read-only and asks it for a plan. Home: [18](18-profiles-plugins.md).

## Print mode
The CLI mode for one task (`simp-agent "task"` or `-p`): it runs once, prints full lines, and exits with 0 or 1. Home: [19](19-cli.md#print-mode).

## REPL
"Read, eval, print loop": the interactive CLI mode where you chat for many turns. Built on `prompt_toolkit` in `simp_cli/repl.py`. Home: [19](19-cli.md#the-repl).

## Component
An object with `render(width) -> list[str]` that draws one part of the chat (`UserMsg`, `AssistantMsg`, `ToolCall`, `Notice` in `simp_cli/components.py`). Home: [19](19-cli.md#components).

## ANSI codes
Special characters a terminal reads as colour or style. Not wanted in files or pipes, so `LinePrinter` uses them only on a TTY. Home: [19](19-cli.md#print-mode).

## Protocol
The fixed set of typed messages between simp-server and the web client, defined in `protocol.py`. Home: [20](20-server-run.md#protocol-models).

## Run
The server object (`Run` in `server.py`) that owns one `AgentSession`, its event log and its run state. Home: [20](20-server-run.md#the-run).

## Run state
One of `idle`, `running`, `waiting_approval`, `aborting`, `error`. Every change is checked by `check_transition`. Home: [20](20-server-run.md#run-state-machine).

## Discriminator
A field (here `type`) whose value says which model a JSON object is. Home: [20](20-server-run.md#protocol-models).

## Durable event
A server event with a `seq` number. It is saved and can be sent again after a reconnect. Home: [20](20-server-run.md#protocol-models).

## Live event
A streaming piece of text with no `seq`. It is not saved and is lost on reconnect. Home: [20](20-server-run.md#protocol-models).

## Snapshot
The event sent after a (re)connect with `last_seq`, run state, in-flight text and any pending approval. Home: [20](20-server-run.md#protocol-models). How it works with replay: [21](21-transport.md#replay-after-then-snapshot-then-live).

## JSON Schema
A standard JSON format that describes data shapes. Used here to generate TypeScript types. Home: [20](20-server-run.md#gen_protocol--protocolgents).

## SSE
Server-Sent Events: one long HTTP response where the server writes events as text blocks. Our browser client reads them with `fetch`, not `EventSource`, because `EventSource` cannot send the `Authorization` header ([25](25-web-client.md#fetch-based-sse)). Home: [21](21-transport.md#sse-out-post-in). OpenAI Responses names each event in its `type` ([03](03-parse.md#openai-responses-named-events)).

## `seq`
A number that grows by one for each saved row of a session. Clients use it to ask for the events they missed. Home: [21](21-transport.md#seq-one-counter-for-everything).

## Last-Event-ID
The HTTP header the browser sends on an SSE reconnect, with the last `id` it saw. Home: [21](21-transport.md#replay-after-then-snapshot-then-live).

## Heartbeat
The `": ping"` comment sent every 15 seconds on an idle SSE stream, so proxies keep it open. Home: [21](21-transport.md#the-sse-loop).

## Future
An asyncio object one task waits on until another task sets its result. Home: [21](21-transport.md#approval-over-the-wire).

## Store
The server slot that saves users, sessions, events and usage. By default `SqliteStore`. Home: [22](22-store-auth.md#opening-the-store).

## Auth
The server slot that finds the user for a request. By default `StaticTokenAuth`. Home: [22](22-store-auth.md#token-hashes).

## Server slot
One class the server needs (`store`, `auth` or `sandbox`), picked by name from `DEFAULT_PLUGINS` in `server.py`. Not the agent plugins of 14. Home: [22](22-store-auth.md#real-design).

## Salt
Random bytes mixed into a password hash, so two users with the same password get different hashes. Home: [22](22-store-auth.md#scrypt-passwords).

## Token (auth)
A long random string sent as `Authorization: Bearer <token>`. Only its SHA-256 hash is stored. Home: [22](22-store-auth.md#token-hashes).

## Static token
One long-lived token per user, saved only as its sha256 in `users.token_sha256`. The admin makes it with `seed` and changes it with `rotate`. Home: [22](22-store-auth.md).

## Per-device token
A token made by each password login and saved in the `tokens` table. `logout` deletes only that row. Home: [22](22-store-auth.md).

## WAL
SQLite write-ahead log mode. Readers do not wait for the writer, and a crash does not break the file. Home: [22](22-store-auth.md#opening-the-store).

## Scrypt
A slow, salted password hash from Python's `hashlib`. It is slow on purpose, so guessing is expensive. Home: [22](22-store-auth.md#scrypt-passwords).

## `recover`
`Run.recover`: closes a run that was busy when the server died, and leaves a valid history. Home: [22](22-store-auth.md#recover).

## Budget guard
`budget.guard`: a wrapper around `stream_fn` that runs a check before each model call. If a limit is reached, it refuses the call with an `error_kind="budget"` error. Home: [23](23-limits.md#the-budget-guard-wrap-the-stream).

## Run budget
The most money one run (a prompt plus its queued follow-ups) may spend; `run_usd` in settings. Home: [23](23-limits.md#the-check-itself).

## Daily budget
The most money one user may spend since local midnight; `user_day_usd` in settings. Home: [23](23-limits.md#the-check-itself).

## Kill switch
The `PAUSED` file in the data dir. While it exists, every model call on the server is refused. Home: [23](23-limits.md#kill-switch-one-file).

## Eviction
Removing an unused `Run` from memory and closing its sandbox. Files and log stay in the store and load back on the next use. Home: [23](23-limits.md#idle-release-evict-runs-nobody-uses).

## Idle release
Evicting runs that were not used for `idle_minutes`. Home: [23](23-limits.md#idle-release-evict-runs-nobody-uses).

## Reducer
A pure function `(state, event) -> new state`. In the web client, `reduce()` is the only place chat state changes. Home: [25](25-web-client.md#the-reducer-statets).

## In-flight buffer
Text of the assistant message that is still streaming, kept by the server `Run` (`self.inflight`) so a late or reloaded tab gets it in the snapshot. Home: [21](21-transport.md#replay-after-then-snapshot-then-live).

## Gap / dup delta
A delta that does not start at the end of the text: a skipped one (gap) or a repeated one (dup). The web client drops both; see [Offset](#offset). Home: [25](25-web-client.md#appendat).

## Bearer token
A secret sent in the header `Authorization: Bearer <token>` on every call to the server. See [Token (auth)](#token-auth). Home: [22](22-store-auth.md).

## Monotonic clock
A clock that only goes forward (`time.monotonic()`). Changing the computer's time does not move it, so it is safe for measuring how long something took. Used in [10](10-coding-tools.md) and [23](23-limits.md).

## Offset
The position in the full text where a delta starts. `appendAt()` uses it to drop repeated (dup) and skipped (gap) deltas. Home: [25](25-web-client.md#appendat).

## Sandbox
A closed place where a session's commands run, apart from the server and other users. Home: [24](24-docker-sandbox.md#the-sandbox-slot).

## Sandbox slot
The place in the server that answers "give me an env for this session". `LocalSandbox` gives a folder; `DockerSandbox` gives a container. Home: [24](24-docker-sandbox.md).

## Container
A process with its own files, users and limits, started from an image by Docker. Home: [24](24-docker-sandbox.md#dockersandboxopen-one-hardened-container-per-session).

## Hardening
Turning off powers a container does not need (root, network, capabilities, write access) and adding limits. Home: [24](24-docker-sandbox.md#dockersandboxopen-one-hardened-container-per-session).

## Bind mount
A host folder shown inside a container at a path, so both see the same files. Home: [24](24-docker-sandbox.md#dockerenv-files-on-the-host-commands-in-the-box).

## End-to-end test
A test that drives the whole running app from the outside, like a real user. Home: [26](26-system-tests-deploy.md#end-to-end-tests-with-playwright).

## Playwright
A tool that controls a real browser from test code. Home: [26](26-system-tests-deploy.md#end-to-end-tests-with-playwright).

## Deterministic
Gives the same output for the same input, every time. Home: [26](26-system-tests-deploy.md#fakellm-a-model-that-always-says-the-same-thing).

## Online backup
SQLite's built-in way to copy a database safely while it is open and in use. Home: [26](26-system-tests-deploy.md#opspy-logs-and-backup).

## `launchd`
The macOS service manager. It starts, restarts and schedules programs from `.plist` files. Home: [26](26-system-tests-deploy.md#launchd-run-it-as-a-service-on-a-mac).

## Pi
Another small coding agent that simp-agent copies many ideas from. Code comments like `(pi ExtensionAPI)` point to it. Home: [27](27-limits-choices-extend.md#part-1-design-choices).

## Protocol (Python)
A `typing.Protocol` class that lists methods. Any object with those methods fits; no base class is needed. Not the same as the server [Protocol](#protocol). Home: [27](27-limits-choices-extend.md#part-1-design-choices).

## Ponytail comment
A `ponytail:` code comment that marks a known shortcut and names its limit and the way to fix it later. Home: [27](27-limits-choices-extend.md#part-2-known-limits).

## Allow list
A fixed list of what to include; anything not on it is left out. The backup copies only the database, `settings.toml`, `workspaces` and `sandboxes`, so `.env` never goes in. Home: [26](26-system-tests-deploy.md).

## LoopConfig
The settings of one `agent_loop()` run: model, tools, `stream_fn`, queues, hooks, `env`, `cwd`. Every hook has a "do nothing" default. See [05](05-agent-loop.md), [part-2-agent](05-0-part-2-agent.md).

## Agent (class)
The thin object around `agent_loop()`. It keeps the history, subscribers, cancel event and the steer / follow-up queues; `prompt()` runs the loop once. See [06](06-events-abort.md), [part-2-agent](05-0-part-2-agent.md).

## SDK
Software development kit: the official library a vendor gives for its API, for example the Python package `anthropic`. Home: [03](03-parse.md#anthropic-the-sdk-builds-the-message).

## Signed thinking
A thinking block that carries a `signature` from Anthropic. It must be sent back unchanged in the next request. Home: [03](03-parse.md#anthropic-the-sdk-builds-the-message).

## `get_final_message()`
An Anthropic SDK method. After the stream ends, it returns the full message the SDK built from all events: content, `stop_reason`, `usage`. Home: [03](03-parse.md#anthropic-the-sdk-builds-the-message).

## Host
The program that runs the agent and sets things the model must not change: the CLI, the server, or the eval runner. Example: the host sets the `bash` time cap with `make_tools(bash_max_timeout_s=...)`. Home: [10](10-coding-tools.md#group-3--run-bash).
