# 02 Part 1 · Translate + Send

**Goal:** Turn our clean messages into one vendor's JSON, and open a stream to that vendor.

**Builds on:** [01 Pick + Clean](01-pick-clean.md) · **Next:** [03 Parse](03-parse.md)

## Where we are

```mermaid
flowchart LR
    P["1 Pick"] --> C["2 Clean"] --> T["3 Translate"] --> S["4 Send"] --> R["5 Parse"] --> L["6 Label"]
    classDef me fill:#ffe9a8,stroke:#c90
    classDef part fill:#fff4d6,stroke:#c90,stroke-dasharray:3 3
    class T,S me
```

**Builds:** blocks 3, 4 · **IN:** `Model`, clean `Context`, `api_key` · **OUT:** raw chunks

Big picture of Part 1: [part-1-ai](part-1-ai.md).

In [01](01-pick-clean.md), Pick chose a [stream function](glossary.md#stream-function) by `model.api`, and Clean fixed the history. Now we go inside the stream function. It has three jobs: **Translate** our messages into the vendor's JSON, **Send** them over HTTP, and **Parse** what comes back. This chapter does the first two, for all three built-in [providers](glossary.md#provider). Parse is ch [03](03-parse.md).

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/ai/providers/openai_completions.py` — `to_openai`, `stream`
- `packages/simp_agent/src/simp_agent/ai/providers/openai_responses.py` — `to_input`, `request`
- `packages/simp_agent/src/simp_agent/ai/providers/anthropic.py` — `_to_anthropic`, `thinking_params`

## Problem

Vendors differ a lot:

| | OpenAI Chat Completions | OpenAI Responses | Anthropic Messages |
|---|---|---|---|
| System prompt | first message, role `system` | first input item, role `system` or `developer` | separate `system` field |
| Tool call | `tool_calls` on the assistant message | `function_call` item | `tool_use` block |
| Tool result | role `tool`, one per result | `function_call_output` item | `tool_result` block inside a **user** turn |
| Thinking | `reasoning_content` text (read only, never sent back) | encrypted `reasoning` item | signed `thinking` block |

**A real example.** Take one small chat in our format. The assistant turn has the common mix: some thinking, a short text, then a tool call.

```text
system:    "You are a coding agent."
user:      "What is in README.md?"
assistant: content = [
             Thinking("User wants the file; call read", signature=...),
             Text("Let me read it."),
             ToolCall(id="call_1", name="read", arguments={"path": "README.md"}),
           ]
tool:      ToolResultMessage(tool_call_id="call_1", content="# simp-agent ...")
```

We send it back to the SAME model that wrote the assistant turn. (For another model, Clean in [chapter 1](01-pick-clean.md) already turned signed thinking into plain text and dropped redacted thinking, so there is no thinking block to translate.) The `signature` is whatever that vendor's parser saved when the answer came in: none for Chat Completions, the whole reasoning item as JSON for Responses, an opaque string for Anthropic. To keep it simple we write the tool call id as `call_1` for all three.

Here is the SAME chat as each vendor wants it. We built each one by following the real code (`to_openai`, `to_input`, `_to_anthropic`). We show only the chat part; fields like `model` and `tools` are cut.

OpenAI Chat Completions (`messages=to_openai(...)`):

```jsonc
"messages": [
  {"role": "system", "content": "You are a coding agent."},        // system = first message
  {"role": "user", "content": "What is in README.md?"},            // content is a plain string
  {"role": "assistant", "content": "Let me read it.",              // only the text; the thinking is DROPPED
   "tool_calls": [{"id": "call_1", "type": "function",
     "function": {"name": "read",
                  "arguments": "{\"path\": \"README.md\"}"}}]},    // arguments is a STRING of JSON
  {"role": "tool", "tool_call_id": "call_1",
   "content": "# simp-agent ..."}                                   // tool result = its own role "tool"
]
```

Plainly: Chat Completions does **not** send thinking back. `to_openai` reads only `m.text()` (text blocks joined) and `m.tool_calls()`; the thinking block is skipped. If the turn had no text, `content` would be `null`.

OpenAI Responses (`input=to_input(...)`):

```jsonc
"input": [
  {"role": "system", "content": "You are a coding agent."},        // system = first item ("developer" for reasoning models)
  {"role": "user",
   "content": [{"type": "input_text", "text": "What is in README.md?"}]},  // text is a typed part
  {"type": "reasoning", "id": "rs_...", "encrypted_content": "...", ...},  // the saved reasoning item = json.loads(Thinking.signature), sent as-is
  {"type": "message", "role": "assistant", "status": "completed",
   "id": "msg_...", "phase": "...",                                 // id and phase come from json.loads(Text.signature)
   "content": [{"type": "output_text", "text": "Let me read it.", "annotations": []}]},
  {"type": "function_call", "call_id": "call_1", "name": "read",
   "arguments": "{\"path\": \"README.md\"}"},                      // tool call = its own item; arguments a STRING
  {"type": "function_call_output", "call_id": "call_1",
   "output": "# simp-agent ..."}                                    // tool result = its own item
]
```

Here one assistant turn becomes three separate items. The thinking signature is the whole reasoning item as JSON, so `to_input` just loads it and puts it back. If the text has no signature, the id is made up (`msg_pi_<i>`) and there is no `phase`. In real Responses chats our tool call id is `call_1|fc_...` (see below), and then the `function_call` item also gets `"id": "fc_..."`.

Anthropic Messages (`system=...`, `messages=_to_anthropic(...)`):

```jsonc
"system": "You are a coding agent.",                                // system = separate field, not a message
"messages": [
  {"role": "user", "content": [{"type": "text", "text": "What is in README.md?"}]},
  {"role": "assistant", "content": [                               // ONE turn, three blocks, same order
    {"type": "thinking", "thinking": "User wants the file; call read",
     "signature": "..."},                                           // signed thinking goes back with its signature
    {"type": "text", "text": "Let me read it."},
    {"type": "tool_use", "id": "call_1", "name": "read",
     "input": {"path": "README.md"}}]},                             // tool call = block; input is an OBJECT, not a string
  {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "call_1",
     "content": "# simp-agent ...", "is_error": false}]}            // tool result = block inside a USER turn
]
```

If the thinking was redacted, the block is `{"type": "redacted_thinking", "data": signature}` instead. If it has no signature (for example the answer was aborted), it is sent as a plain `text` block.

The assistant turn side by side:

| Our block | OpenAI Chat Completions | OpenAI Responses | Anthropic Messages |
|---|---|---|---|
| Thinking | dropped, not sent | saved `reasoning` item (from `signature`), own item | `thinking` block with `signature` (redacted → `redacted_thinking`) |
| Text | `content` string | `message` item, `id`/`phase` from text `signature` | `text` block |
| Tool call | `tool_calls` entry, `arguments` as JSON string | `function_call` item, `arguments` as JSON string | `tool_use` block, `input` as object |

One chat, three very different shapes. This is why we need block 3 Translate.

And sending can fail in many ways: network down, bad key, a 529 "overloaded". The [stream function](glossary.md#stream-function) rule says "never raise", so every failure must become an `error` event.

## 3 Translate / 4 Send: the three providers

All three have the same plan: **convert** our messages, **call** the SDK with `stream=True`, **parse** events, and catch every exception into an `error` event. Each one imports its SDK inside `stream`, so you only need the SDK you use. (Note: the import sits just before the `try`, so a missing SDK raises `ImportError` — the one case that breaks "never raise".)

**OpenAI Chat Completions** (`openai_completions.py`). This is the format most local servers copy. `to_openai` puts the system prompt first, sends tool results as one `role: "tool"` message each, and sends `content: None` for an assistant turn that only has tool calls. `stream` reads `compat` (small per-server switches on the `Model`; all keys in [ref-objects](ref-objects.md#request-objects-tool-context-model)):

Real code: [packages/simp_agent/src/simp_agent/ai/providers/openai_completions.py](../../packages/simp_agent/src/simp_agent/ai/providers/openai_completions.py) (`stream`)

```text
kw[ compat "max_tokens_field" or "max_tokens" ] = model.max_tokens
IF compat include_usage (default yes):
    kw.stream_options = {include_usage: true}
IF compat reasoning_effort is set:
    kw.reasoning_effort = that value
```

Some servers want `max_completion_tokens`, some fail on `stream_options`. `compat` handles that without code. The parser is in ch [03](03-parse.md).

**OpenAI Responses** (`openai_responses.py`). The newer OpenAI API. We send `store: False`, so OpenAI keeps nothing between calls. To let a reasoning model see its own past reasoning, we ask for `include: ["reasoning.encrypted_content"]` and save the whole reasoning item as JSON in `ThinkingContent.signature`. `to_input` puts it back in the input as-is. Text parts also keep a small JSON signature (`{v, id, phase}`) so their item id goes back the same. A tool call id is stored as `call_id|item_id` in one string; `to_input` splits it again. With reasoning on, the system prompt uses role `developer`. The request is built in `request`:

Real code: [packages/simp_agent/src/simp_agent/ai/providers/openai_responses.py](../../packages/simp_agent/src/simp_agent/ai/providers/openai_responses.py) (`request`)

```text
kw = {model id, input = to_input(model, system prompt, messages), stream: true,
      store: false, max_output_tokens: at least 16}
IF the model has a reasoning effort:
    kw.reasoning = {effort, summary: "auto"}
    kw.include   = ["reasoning.encrypted_content"]   // so we can send it back later
```

**Anthropic Messages** (`anthropic.py`). `_to_anthropic` sends a tool result as a `tool_result` block in a **user** turn. Anthropic needs user and assistant turns to alternate, so the last step merges turns next to each other with the same role:

Real code: [packages/simp_agent/src/simp_agent/ai/providers/anthropic.py](../../packages/simp_agent/src/simp_agent/ai/providers/anthropic.py) (`_to_anthropic`)

```text
merged = empty list
FOR EACH turn t in out:
    IF the last merged turn has the same role as t:
        ADD t's content to that last turn   // Anthropic needs user/assistant to alternate
    ELSE:
        ADD t to merged
```

So three tool results become one user turn. Thinking is turned on by `thinking_params(model)`: `compat.thinking_budget` gives a fixed token budget (older models); `compat.reasoning_effort` gives adaptive thinking with an effort level.

### Send: the wrapper `stream`

`parse` only reads chunks (ch [03](03-parse.md)). The `stream` function in each provider file makes the HTTP request and calls `parse`. In `openai_completions.py`:

```text
TRY:
    chunks = WAIT for client.chat.completions.create(...)
    FOR EACH event from parse(chunks, compat): SEND it on
IF any exception:
    SEND event {error, AssistantMessage(stop_reason = error, error = the text of the exception)}
```

Real code: [packages/simp_agent/src/simp_agent/ai/providers/openai_completions.py](../../packages/simp_agent/src/simp_agent/ai/providers/openai_completions.py) (`stream`)

A network error or a 401 becomes an `error` event, not an exception. We split `parse` out of `stream` so tests can feed it plain objects with no network and no `openai` client.

## Test

No real model or key is needed. The tests replace the SDK with a fake.

- `test_message_conversion` (`test_openai.py`) — `to_openai` output shape.
- `test_compat_params` (`test_openai.py`) — `compat` changes the request keys.
- `test_http_error_is_event` (`test_openai.py`) makes `AsyncOpenAI` raise a connection error. The stream yields an `error` event, not an exception. (The same test also checks the error classifiers built in ch [04](04-label-test.md).)
- `test_responses_replay_order_and_ids` (`test_reasoning.py`) — Responses replay: reasoning items and ids go back the same.

```bash
cd packages/simp_agent
uv run pytest -q tests/test_openai.py::test_message_conversion tests/test_openai.py::test_compat_params \
  tests/test_openai.py::test_http_error_is_event tests/test_reasoning.py::test_responses_replay_order_and_ids
```

> **Why this way**
>
> We pick the provider by **API format** (`model.api`), not by vendor. Many vendors and local servers speak the OpenAI format, so three providers cover almost all of them, and `compat` handles the small differences.
>
> Each provider only converts, sends and parses. A provider never raises and never reads the environment, so the loop has one rule (read the last event) and the app stays in control of keys.

## Exercises

1. Call `to_openai` on a history with an assistant turn that has only a tool call, then its tool result. What is the assistant's `content`, and what role does the result get?
2. Make a `Model(api="openai-completions", compat={"max_tokens_field": "max_completion_tokens", "include_usage": False})`. Which request keys change?

## Recap

- Each provider converts our messages to its own format; Anthropic merges same-role turns so user and assistant alternate.
- `compat` holds small per-server switches (`max_tokens_field`, `include_usage`, `reasoning_effort`, `thinking_budget`), so odd servers need a setting, not new code.
- OpenAI Responses keeps nothing on the server (`store: False`); we save the encrypted reasoning item in `ThinkingContent.signature` and send it back.
- `stream` sends the request and turns every exception into an `error` event.

**Builds on:** [01 Pick + Clean](01-pick-clean.md) · **Next:** [03 Parse](03-parse.md) — the server answers in many small chunks; next we glue them into one message.

**OUT →** raw chunks from the vendor are the IN of block 5 Parse (ch 03).
