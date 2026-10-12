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

## Provider registry
The dict `_PROVIDERS` in `ai` that maps a `Model.api` string (`anthropic-messages`, `openai-completions`, `openai-responses`) to a stream function. `register_provider` adds or replaces one; `ai.stream` looks it up. Home: [04](04-providers.md#the-registry-_providers-register_provider-stream).

## Context overflow
An error that says the request is bigger than the model's context window. Found by `is_context_overflow`; never retried as-is. Defined in [04](04-providers.md#error-classification-is_retryable-is_context_overflow); handled in [17](17-overflow.md).
