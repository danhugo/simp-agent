# Glossary

Terms are added here as chapters define them. Each entry links to the chapter that defines it.

## Coding agent
A program that takes a task in plain words, asks a language model what to do, runs the tools the model asks for (read, write, run commands), and repeats until done. Home: [00](00-overview.md).

## Layer
One folder of the `simp_agent` library (`ai`, `agent`, `coding`, `session`, `plugins`, `testing`). A layer imports only layers to its left; `test_layers.py` checks this. Home: [00](00-overview.md#the-layer-map).

## Tool call
A request from the model to run one named tool with arguments (class `ToolCall` in `ai`). Home: [00](00-overview.md); built in [01](01-messages.md).

## Message
One entry in a conversation: `UserMessage`, `AssistantMessage` or `ToolResultMessage` (all in `ai`). Each has a `role` field so it can be saved to JSON and loaded back with `to_dict` / `from_dict`. Home: [01](01-messages.md).

## Context
Everything sent to a model in one request: system prompt, messages and tools (class `Context` in `ai`). Home: [01](01-messages.md#packing-a-request-tool-context-model).

## Compaction entry
A history marker (`CompactionEntry`) that says "messages before `first_kept_index` are replaced by this summary". Never sent to the model as-is. Defined in [01](01-messages.md); built in [16](16-compaction.md).

## Custom entry
A history entry (`CustomEntry`) where apps and plugins keep their own data. Saved and replayed, never sent to the model. Defined in [01](01-messages.md); used in [14](14-plugins.md).

## Provider
The code that talks to one model vendor's API and turns its answer into our events and messages. Every provider is a stream function. Defined in [02](02-fake-provider.md); built in [04](04-providers.md).

## Stream function
An async function `(model, context, api_key=None)` that yields event dicts and ends with a `done` or `error` event holding the final `AssistantMessage`. It never raises. The loop takes it as the `stream_fn` setting. Home: [02](02-fake-provider.md#the-shape-of-a-model-call).

## Scripted reply
One answer given in advance to `FakeProvider`; replies are played in order, one per model call. A reply is a message or a function `(ctx) -> message`. Home: [02](02-fake-provider.md#a-script-of-replies).

## Delta
One small piece of a streamed model answer (a bit of text, thinking, or tool-call arguments). The stream parser joins deltas into one `AssistantMessage` and yields each one as a `*_delta` event. Home: [03](03-stream-parser.md).

## Usage
The token count of one model call, kept in `AssistantMessage.usage` as `{"input", "output", "reasoning"}`. `reasoning` is already inside `output`. Home: [03](03-stream-parser.md#usage).

## Agent loop
The loop that calls the model, runs the tool calls it asks for, adds the results, and calls the model again until it stops asking (`agent_loop` in `agent`). Built in [05](05-agent-loop.md#agent_loop-the-loop).

## Turn
One pass of the agent loop: one model call plus the tool calls it asked for. Starts with a `turn_start` event, ends with `turn_end`. Home: [05](05-agent-loop.md#agent_loop-the-loop).

## Agent tool
An `ai.Tool` (name, description, JSON schema) plus `execute(args, ctx) -> str` and an optional `prepare_arguments` (class `AgentTool` in `agent`). Run by `run_tool`, which turns every failure into an error tool result. Home: [05](05-agent-loop.md#tools-agenttool).

## Tool context
The object a tool gets when it runs (`ToolContext`): `cancel`, `env`, `cwd`, `on_update`. Home: [05](05-agent-loop.md#toolcontext-what-a-tool-gets).

## Execution environment
The one object (`ExecutionEnv`, default `LocalEnv`) through which tools read files and run commands. Given to tools in the tool context. Defined in [05](05-agent-loop.md#toolcontext-what-a-tool-gets); built in [09](09-exec-env.md).

## Path safety
The rule that, when `LocalEnv` has a `root`, a file path may not leave it. `_path` resolves `..` and symlinks first, then raises `PermissionError` if the path is outside the root. Files only: `exec` is not fenced. Home: [09](09-exec-env.md#path-safety).

## Process-group kill
How `exec` stops a command: the shell starts in a new process group (`start_new_session=True`), and `run_kill` sends `SIGKILL` to the whole group until it is empty, so background children die too. Home: [09](09-exec-env.md#process-group-kill).

## Provider registry
The dict `_PROVIDERS` in `ai` that maps a `Model.api` string (`anthropic-messages`, `openai-completions`, `openai-responses`) to a stream function. `register_provider` adds or replaces one; `ai.stream` looks it up. Home: [04](04-providers.md#the-registry-_providers-register_provider-stream).

## Context overflow
An error that says the request is bigger than the model's context window. Found by `is_context_overflow`; never retried as-is. Defined in [04](04-providers.md#error-classification-is_retryable-is_context_overflow); handled in [17](17-overflow.md).

## Event
A small dict with a `"type"` key (`agent_start`, `turn_start`, `message_update`, `message_end`, `tool_execution_start`, `turn_end`, `agent_end`, …) that the agent loop sends through `emit` so callers can watch a run. `Agent.subscribe` adds a listener. Home: [06](06-events-abort.md#events-one-stream-of-small-dicts).

## Abort
Stopping a run in the middle by setting one `asyncio.Event` (`cancel`, or `Agent.abort()`). It closes the model stream, stops tools, and ends the run with an assistant message whose `stop_reason` is `aborted`. Home: [06](06-events-abort.md#abort-one-asyncioevent).

## Steer
A user message typed while the agent works, meant to reach the model soon. `Agent.steer(text)` queues it; the loop reads it (through `LoopConfig.get_steering`) before the first turn, just before each model call, and after each tool batch. It never cuts a tool batch. Home: [07](07-steering.md#when-each-queue-is-read).

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
A named model setup in `settings.toml` under `[profiles.<name>]`: `api`, `model`, optional `base_url`, `api_key_env`, `price_in` / `price_out` (dollars per million tokens). `build_model` turns it into a `Model`. Used by evals in [12](12-evals.md); home: [18](18-profiles-plugins.md).

## Session
One long conversation with the agent, across many prompts and restarts. Owned by `AgentSession`. Home: [13](13-session.md).

## AgentSession
The class in `session/__init__.py` that owns one `Agent` and adds saving, plugins, retry, compaction and overflow recovery. Home: [13](13-session.md).

## SessionStore
A protocol with two methods, `append(entry)` and `load()`: where a session saves its history. `append` may be sync or async. Home: [13](13-session.md).

## JSONL
A file with one JSON object per line. The CLI's `JsonlStore` saves one history entry per line. Home: [13](13-session.md#jsonlstore-the-real-store-in-the-cli).

## _maybe_await
A helper in `agent/__init__.py` that awaits a value only if it is awaitable. It lets hooks and stores be sync or async. Home: [08](08-hooks-approval.md); used in [13](13-session.md).

## Append-only history
Finished messages are never changed or removed; new entries are only added at the end. So a store can save each entry once, right away. Home: [13](13-session.md).

## plugin
Any object passed in `AgentSession(plugins=[...])`; the session calls its hook methods. Home: [14](14-plugins.md).

## plugin hook
A method name the session calls on a plugin at a fixed point (`setup`, `input`, `context`, `tool_call`, `tool_result`, `on_event`, ...). Home: [14](14-plugins.md).

## hook isolation
An error in a plugin hook becomes a `plugin_error` event instead of breaking the run. Home: [14](14-plugins.md).

## fail closed
When a safety check itself fails, treat it as "no" (block the tool). Home: [14](14-plugins.md).

## PluginAPI
The object a plugin gets in `setup`; the actions it may take on its session. Home: [14](14-plugins.md).

## plugin_error
The event the session emits when an isolated plugin hook raises; it names the plugin and the hook. Home: [14](14-plugins.md).

## retry
Calling the model again after a short-lived error, with `continue_()`. Home: [15](15-retry.md).

## backoff
Waiting longer between each retry; here the wait doubles each time. Home: [15](15-retry.md).

## error_kind
A field on `AssistantMessage`; `fatal`, `budget` or `policy` mean "never retry". Home: [15](15-retry.md).

## retryable error
An error whose text matches `_RETRYABLE` (429, 5xx, overloaded, network...) and whose kind allows retry. Home: [15](15-retry.md).

## auto_retry_start / auto_retry_end
Session events sent before each backoff wait and once after the last retry. Home: [15](15-retry.md).

## NON_RETRYABLE
The set `{"fatal", "budget", "policy"}` of error kinds that `is_retryable` always rejects. Home: [15](15-retry.md).

## context window
The most tokens a model can read in one call (`Model.context_window`). Home: [16](16-compaction.md).

## compaction
Replacing old history in the model's view with a summary. Home: [16](16-compaction.md).

## CompactionEntry
The marker appended to history: summary, `first_kept_index`, read and modified files. Home: [16](16-compaction.md).

## view (LLM view)
The message list actually sent to the model, built from history by `build_view` and the plugin `context` chain. Home: [16](16-compaction.md).

## reserve_tokens
Tokens kept free for the reply and the summary (default 16384). Home: [16](16-compaction.md).

## keep_recent_tokens
About how many recent tokens are kept word for word (default 20000). Home: [16](16-compaction.md).

## incremental summary
Updating the previous summary with only the new messages. Home: [16](16-compaction.md).

## cut (first_kept_index)
The index of the first message kept word for word; always a user or assistant message. Home: [16](16-compaction.md).

## overflow recovery
In `_run`: compact once and call the model again. Home: [17](17-overflow.md).

## overflowed flag
The per-run flag in `_run` that allows only one overflow recovery. Home: [17](17-overflow.md).

## build_model
`session/profile.py`; turns a profile into a `Model`. Shared by the CLI and the server. Home: [18](18-profiles-plugins.md).

## build_plugins
`plugins/__init__.py`; turns plugin names into new plugin objects. Home: [18](18-profiles-plugins.md).

## RedactSecrets
Built-in plugin that replaces secrets with `[REDACTED]`. Home: [18](18-profiles-plugins.md).

## include_usage
`Model.compat` flag; asks an OpenAI-style server to send token usage in the stream. `build_model` turns it on by default. Home: [18](18-profiles-plugins.md).

## plan mode
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
The event sent after a (re)connect with `last_seq`, run state, in-flight text and any pending approval. Home: [20](20-server-run.md#protocol-models).

## JSON Schema
A standard JSON format that describes data shapes. Used here to generate TypeScript types. Home: [20](20-server-run.md#gen_protocol--protocolgents).

## SSE
Server-Sent Events: one long HTTP response where the server writes events as text blocks. The browser reads them with `EventSource`. Home: [21](21-transport.md#sse-out-post-in).

## seq
A number that grows by one for each saved row of a session. Clients use it to ask for the events they missed. Home: [21](21-transport.md#seq-one-counter-for-everything).

## Last-Event-ID
The HTTP header the browser sends on an SSE reconnect, with the last `id` it saw. Home: [21](21-transport.md#replay-after-then-snapshot-then-live).

## Heartbeat
The `": ping"` comment sent every 15 seconds on an idle SSE stream, so proxies keep it open. Home: [21](21-transport.md#the-sse-loop).

## Future
An asyncio object one task waits on until another task sets its result. Home: [21](21-transport.md#approval-over-the-wire).

## Store
The server plugin that saves users, sessions, events and usage. By default `SqliteStore`. Home: [22](22-store-auth.md#sqlitestore-one-file-five-tables).

## Auth
The server plugin that finds the user for a request. By default `StaticTokenAuth`. Home: [22](22-store-auth.md#token-hashes).

## Token (auth)
A long random string sent as `Authorization: Bearer <token>`. Only its SHA-256 hash is stored. Home: [22](22-store-auth.md#token-hashes).

## WAL
SQLite write-ahead log mode. Readers do not wait for the writer, and a crash does not break the file. Home: [22](22-store-auth.md#sqlitestore-one-file-five-tables).

## scrypt
A slow, salted password hash from Python's `hashlib`. It is slow on purpose, so guessing is expensive. Home: [22](22-store-auth.md#scrypt-passwords).

## recover
`Run.recover`: closes a run that was busy when the server died, and leaves a valid history. Home: [22](22-store-auth.md#recover).
