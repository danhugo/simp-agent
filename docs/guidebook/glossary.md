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
One part of the system prompt in `AgentSession`: an id, an order and a string or `fn(ctx)`. `_build_prompt` sorts them, skips empty ones and joins them before each model call. Home: [11](11-system-prompt.md#prompt-sections-building-the-prompt-every-turn).

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
