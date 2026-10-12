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
