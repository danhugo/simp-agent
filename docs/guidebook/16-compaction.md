# 16 Part 4 · Compaction

**Goal:** Keep long conversations inside the context window.

**Builds on:** [15 Retry](15-retry.md) · **Next:** [17 Context overflow](17-overflow.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent --> coding --> session --> plugins --> testing
    session -.used by.-> apps["apps: cli, server (+ web)"]
    style agent fill:#ffd54f,stroke:#333,stroke-width:2px
    style session fill:#ffd54f,stroke:#333,stroke-width:2px
```

*This chapter adds `agent/compaction.py` (pure helpers, in `agent`) and wires it into the `session` layer (both marked).*

## Problem

Every model has a **[context window](glossary.md#context-window)**: the most tokens it can read in one call. In simp-agent it is `Model.context_window`. Each turn we send the whole history. A coding session reads files and runs commands, and tool results are big. After a while the history does not fit any more.

Now the fizzbuzz task is done and the user keeps going: "add tests", "add a CLI", "refactor"... After an hour, the next call would be too big. We need to make the history smaller **before** that happens, but we must not lose what the user asked for or which files were changed.

## Naive version

Drop old messages:

```python
def trim(messages, keep=20):
    return messages[-keep:]

# before each model call:
view = trim(agent.messages)
```

It keeps the call small. It breaks badly:

1. **The model forgets the task.** The first user message ("write fizzbuzz.py ...") is the first thing dropped.
2. **Broken pairs.** If the cut lands on a tool result, its tool call is gone. Providers reject a tool result without its call.
3. **Counting messages is not counting tokens.** 20 small messages are fine; 20 file reads are not.
4. **History is lost.** If we cut `agent.messages` itself, the saved session loses data too.

## Step by step: from naive to real

We fix the four problems one at a time. Each step is small.

**Step 0: naive.** `messages[-keep:]`. Fast, but it forgets the task and can break pairs.

**Step 1: count tokens, not messages.** Fixes problem 3.

```python
def estimate(m) -> int:
    ...
    return n // 4
```

A rough guess: 4 characters is about 1 token. Now "too big" means tokens, so 20 file reads count as big.

**Step 2: decide *when* with the window.** Still problem 3.

```python
def should_compact(tokens: int, model, settings: CompactionSettings) -> bool:
    return settings.enabled and tokens > model.context_window - settings.reserve_tokens
```

We act before the limit, not at it. `reserve_tokens` leaves room for the reply and the summary.

**Step 3: cut only on a user or assistant message.** Fixes problem 2.

```python
ok = [j for j in range(start + 1, len(messages)) if isinstance(messages[j], (UserMessage, AssistantMessage))]
before = [j for j in ok if j <= i]
```

`find_cut` walks back about `keep_recent_tokens`, then moves the cut to a safe message. A tool result is never the first kept message, so it never loses its call.

**Step 4: summarize the old part instead of dropping it.** Fixes problem 1.

```python
summary = await summarize(stream_fn, model, old, previous, settings.reserve_tokens)
```

The model writes a summary in a fixed format. The first section lists every user request, so the task is not lost.

**Step 5: append a marker, do not cut history.** Fixes problem 4.

```python
return CompactionEntry(summary + format_files(read, mod), cut, read, mod)
```

`compact` returns a `CompactionEntry`. The session appends it. `build_view` uses it to make the smaller list for the model. Full history stays in memory and in the store.

**Step 6: be exact about files, and incremental.** The model can forget details, so code adds `<read-files>` and `<modified-files>`. Next time, `summarize` gets only the new old messages plus the `previous` summary, so we never re-read old text.

**Step 7: wire it in the session.** `_prepare` runs before every model call, checks `should_compact`, and returns `build_view(...)`. The sections below show the real code for each step.

## Real design

The idea: when the history is near the limit, ask the model to **summarize** the old part. Keep the summary and the recent messages. This is **[compaction](glossary.md#compaction)**.

All the pure logic is in `packages/simp_agent/src/simp_agent/agent/compaction.py`. It knows nothing about sessions, so it can be tested alone (layer rule, [00](00-overview.md)).

### CompactionEntry and build_view: history stays append-only

The summary is not a replacement. It is a marker appended to history. In `ai/__init__.py`:

```python
@dataclass
class CompactionEntry:
    """Marker appended to history. History stays append-only; build_view() turns it into the LLM view."""

    summary: str
    first_kept_index: int
    read_files: list = field(default_factory=list)
    modified_files: list = field(default_factory=list)
    role: Literal["compaction"] = "compaction"
```

A **[CompactionEntry](glossary.md#compactionentry)** says: "from now on, the model sees this summary, then the messages from `first_kept_index` on". The old messages stay in history and in the store ([13](13-session.md)). Only the **view** sent to the model changes:

```python
def build_view(messages: list) -> list:
    """[summary user message] + messages from first_kept_index on (markers and custom entries dropped)."""
    k = _last_entry(messages)
    if k is None:
        return [m for m in messages if not isinstance(m, CustomEntry)]
    e = messages[k]
    kept = [m for m in messages[e.first_kept_index :] if not isinstance(m, (CompactionEntry, CustomEntry))]
    return [UserMessage(f"{SUMMARY_PREFIX}{e.summary}\n</summary>")] + kept
```

The summary becomes one `UserMessage` that starts with `SUMMARY_PREFIX` ("The conversation history before this point was compacted into the following summary: ..."). `CustomEntry` items ([13](13-session.md)) are always dropped from the view.

Why append-only? The saved file is never rewritten, so a crash during compaction cannot corrupt it. And a UI can still show the full history.

### estimate_tokens and should_compact: when

```python
def estimate(m) -> int:
    ...
    return n // 4

def estimate_tokens(messages: list) -> int:
    """Tokens of the LLM view of full history: last valid assistant usage after the last CompactionEntry + chars/4 after it.
    No such usage -> chars/4 of the view. Error, aborted and all-zero usage are ignored."""
    k = _last_entry(messages)
    for i in range(len(messages) - 1, -1 if k is None else k, -1):
        m = messages[i]
        if isinstance(m, AssistantMessage) and m.stop_reason not in ("error", "aborted") and any(m.usage.values()):
            return m.usage["input"] + m.usage["output"] + sum(estimate(x) for x in messages[i + 1 :])
    return sum(estimate(x) for x in build_view(messages))


def should_compact(tokens: int, model, settings: CompactionSettings) -> bool:
    return settings.enabled and tokens > model.context_window - settings.reserve_tokens
```

- `estimate` is a rough guess: 4 characters ≈ 1 token.
- `estimate_tokens` prefers the real number. The last good assistant reply has `usage` from the provider ([04](04-providers.md)): input + output tokens of that call. Add the guess only for messages after it. It looks only **after** the last `CompactionEntry`, because usage from before was measured on the old, bigger view.
- `should_compact` is true when tokens pass `context_window - reserve_tokens`.

`CompactionSettings` has three fields: `enabled=True`, `reserve_tokens=16384` (room left for the reply and the summary), `keep_recent_tokens=20000` (how much recent history to keep word for word).

### find_cut: where

```python
def find_cut(messages: list, start: int, keep_tokens: int) -> int | None:
    """First kept index in (start, len). Only a user or assistant message: never a tool_result, so pairs stay together.
    ponytail: no split-turn cut (pi isSplitTurn); one huge turn cannot be compacted."""
    total, i = 0, len(messages)
    while i > start and total < keep_tokens:
        i -= 1
        total += estimate(messages[i])
    ok = [j for j in range(start + 1, len(messages)) if isinstance(messages[j], (UserMessage, AssistantMessage))]
    before = [j for j in ok if j <= i]
    return before[-1] if before else (ok[0] if ok else None)
```

Walk back from the end until about `keep_tokens` are kept. Then move the cut to a user or assistant message at or before that point. A cut **never** lands on a tool result, so a tool call and its result stay together. `start` is the previous entry's `first_kept_index`, so a new cut is always after the old one. The `ponytail:` comment names a known limit: one single huge turn cannot be cut.

### serialize_conversation: what the summarizer reads

```python
def serialize_conversation(messages: list) -> str:
    """Messages -> one text, so the summarizer reads it instead of continuing the chat (pi serializeConversation)."""
    parts = []
    for m in ai.transform_messages(messages):
        if isinstance(m, UserMessage) and m.content:
            parts.append(f"[User]: {m.content}")
        elif isinstance(m, AssistantMessage):  # thinking skipped: big, the text + tool calls carry the result
            ...
                parts.append(f"[Assistant tool calls]: {'; '.join(calls)}")
        elif isinstance(m, ToolResultMessage) and m.content:
            parts.append(f"[Tool result]: {_cut(m.content, TOOL_RESULT_MAX)}")
    return "\n\n".join(parts)
```

Why one text and not the real messages? If you send the chat as chat, the model tends to **continue** it ("Sure, I will add tests now"). As one block of text inside `<conversation>` tags, with a system prompt that says "Do NOT continue the conversation", it summarizes. Tool results are cut to `TOOL_RESULT_MAX = 2000` characters and tool arguments to `ARG_MAX = 500`: the summary needs what happened, not every byte of a file. Thinking is skipped.

### summarize: incremental

```python
async def summarize(stream_fn, model, old: list, previous: str | None, reserve_tokens: int = 16384) -> str:
    text = f"<conversation>\n{serialize_conversation(old)}\n</conversation>\n\n"
    if previous:
        text += f"<previous-summary>\n{previous}\n</previous-summary>\n\n{UPDATE_SUMMARIZATION_PROMPT}"
    else:
        text += SUMMARIZATION_PROMPT
    model = dataclasses.replace(model, max_tokens=min(int(0.8 * reserve_tokens), model.max_tokens))
    ...
    if msg is None or msg.stop_reason in ("error", "length", "aborted"):
        raise RuntimeError(f"summary failed: {msg.error if msg else 'no response'}")
    return msg.text()
```

- The first time, it uses `SUMMARIZATION_PROMPT`: a fixed format with `## User Requests (chronological)`, `## Goal`, `## Progress`, `## Next Steps` and more. The first section says "EVERY request the user made ... Never drop one". That fixes the "model forgets the task" problem.
- The next time, it sends only the **new** old messages plus the previous summary, with `UPDATE_SUMMARIZATION_PROMPT` ("PRESERVE all existing information"). This is **incremental**: we never re-read what was already summarized.
- `max_tokens` is capped at 80% of `reserve_tokens`, so the summary always fits in the room we kept.
- A cut-off (`"length"`) or failed reply raises. A half summary is worse than none.

### File tracking

```python
def file_lists(messages: list, prev: CompactionEntry | None) -> tuple[list, list]:
    """(read_only, modified) paths from read/write/edit calls, merged with the previous entry's lists."""
```

From the `path` argument of `read`, `write` and `edit` calls ([10](10-coding-tools.md)), the code builds two lists: files only read, and files changed. They merge with the previous entry's lists. `format_files` appends them to the summary as `<read-files>` and `<modified-files>` blocks. The model may lose details in a summary, but it will always know that `fizzbuzz.py` was modified. This is done in code, not by the model, so it is exact.

### compact: putting it together

```python
async def compact(messages: list, model, stream_fn, settings: CompactionSettings, redact=None) -> CompactionEntry:
    """Pure: summarize full history up to a cut into a new CompactionEntry. Raises if nothing to do or on failure."""
    k = _last_entry(messages)
    prev = messages[k] if k is not None else None
    start, previous = (prev.first_kept_index, prev.summary) if prev else (0, None)
    cut = find_cut(messages, start, settings.keep_recent_tokens)
    if cut is None:
        raise RuntimeError("nothing to compact")
    old = [m for m in messages[start:cut] if not isinstance(m, (CompactionEntry, CustomEntry))]
    read, mod = file_lists(old, prev)
    if redact:  # e.g. the plugin context chain: secrets must not reach the summary model
        old = await redact(old)
    summary = await summarize(stream_fn, model, old, previous, settings.reserve_tokens)
    return CompactionEntry(summary + format_files(read, mod), cut, read, mod)
```

`compact` returns an entry; it does not change `messages`. The `redact` argument lets the session pass the plugin `context` chain ([14](14-plugins.md)), so a secret masked for the model is also masked for the summary model.

### In the session

In `session/__init__.py`, `_prepare` is the agent's `prepare_next_turn` socket ([13](13-session.md)). It runs before **every** model call:

```python
    async def _prepare(self, messages: list) -> list:
        if self.auto_compact and should_compact(estimate_tokens(messages), self.agent.model, self.compaction):
            await self.compact()
        return await self._context(build_view(messages))
```

And `compact()`:

```python
    async def compact(self) -> bool:
        """Manual compaction. Summarize old history and append a CompactionEntry. Failure keeps history as is."""
        a = self.agent
        before = estimate_tokens(a.messages)
        await self._emit({"type": "compaction_start", "tokens_before": before})
        try:
            stream_fn = functools.partial(a.stream_fn, **await api_key_opts(a.get_api_key, a.model))
            entry = await compact(a.messages, a.model, stream_fn, self.compaction, self._context)
        except Exception as e:
            await self._emit({"type": "compaction_end", "error": str(e), "tokens_before": before, "tokens_after": before})
            return False
        a.messages.append(entry)
        if self.store:
            await _maybe_await(self.store.append(entry))
        ...
        return True
```

- It uses the same model and the same API key as the chat.
- On failure it emits `compaction_end` with the `error` and returns `False`. History is unchanged and the turn goes on. The model call may then overflow, and [17](17-overflow.md) handles that.
- On success the entry is appended and saved like any message.
- Apps can call `compact()` by hand too (a `/compact` command).

Because compaction runs inside `prepare_next_turn`, it happens **inside** a turn, not between prompts. A long tool loop gets compacted in the middle. And a steer message typed during the slow summary call still arrives in the same turn (`test_steer_during_compaction_same_turn`).

### Replay a real compaction

`apps/cli/scripts/replay_compaction.py` takes a saved session file and a cut, and prints the summary that a real model gives:

```sh
uv run apps/cli/scripts/replay_compaction.py ~/.simp-agent/sessions/<cwd-slug>/<id>.jsonl 40
```

It calls `summarize`, `file_lists` and `format_files` directly. Use it to tune the prompts on real sessions instead of guessing.

## Test

Two tests. First, the pure request, `packages/simp_agent/tests/test_compaction_serialize.py::test_request_is_one_serialized_user_message`:

```python
async def test_request_is_one_serialized_user_message():
    stream, seen = capture()
    msgs = turn("a.html") + turn("b.html", "read") + [UserMessage("last" + "x" * 1000)]
    entry = await compact(msgs, Model(max_tokens=100000), stream, SETTINGS)
    model, ctx = seen[0]
    assert "Do NOT continue the conversation" in ctx.system_prompt
    assert len(ctx.messages) == 1 and ctx.messages[0].content.startswith("<conversation>\n[User]: make a.html")
    text = ctx.messages[0].content
    assert "C" * 501 not in text and "R" * 2001 not in text and "more characters truncated]" in text
    assert "## User Requests (chronological)" in text
    assert model.max_tokens == int(0.8 * SETTINGS.reserve_tokens)
    assert entry.modified_files == ["a.html"] and entry.read_files == ["b.html"]
    assert entry.summary.endswith("<read-files>\nb.html\n</read-files>\n\n<modified-files>\na.html\n</modified-files>")
```

It checks: one serialized user message, args cut at 500 and results at 2000, the summary format, the `max_tokens` cap, and the file lists.

Second, the session flow, `packages/simp_agent/tests/test_queues_compaction.py::test_compaction_appends_marker_and_view`:

```python
async def test_compaction_appends_marker_and_view():
    stream = FakeProvider(AssistantMessage([TextContent("SUM")]), DONE)
    seen = stream.messages
    a = compact_agent(stream)
    a.agent.messages = history()
    events = []
    a.subscribe(lambda e: events.append(e["type"]))
    await a.prompt("next")
    assert "compaction_start" in events and "compaction_end" in events
    summary_call = seen[0]
    assert len(summary_call) == 1 and summary_call[0].content.startswith("<conversation>\n[User]: old")
    assert "[Tool result]: yyy" in summary_call[0].content
    assert a.messages[0].content.startswith("old")  # full history still has the old messages
    entry = next(m for m in a.messages if isinstance(m, CompactionEntry))
    assert entry.summary == "SUM" and a.messages[entry.first_kept_index].content.startswith("new")
    assert seen[1][0].content == SUM_HEAD + "SUM\n</summary>" and seen[1][1].content.startswith("new")
```

`compact_agent` makes a session with a 10 000-token window and a small reserve, and `history()` is about 20 000 tokens. So the first `FakeProvider` reply is the summary `"SUM"`, the second is the real answer. It checks that history still starts with `"old"`, the entry points at `"new"`, and the model's view is the summary plus `"new"`.

Run them:

```sh
uv run pytest packages/simp_agent/tests/test_compaction_serialize.py packages/simp_agent/tests/test_queues_compaction.py -q
```

## Why this way

> **Summarize, append a marker, change only the view.** Compaction keeps the model inside its window without losing the user's requests or the list of changed files. The pure logic in `agent/compaction.py` is easy to test; the session only decides *when*. History stays append-only, so the store is never rewritten. The cost: the summary is a model call (time and money), and a summary can still miss details; the fixed format, incremental updates and code-made file lists keep that small.

## Exercises

1. **Try `find_cut` by hand.** Build a list: `UserMessage("a"*4000)`, an `AssistantMessage` with a `ToolCall`, a `ToolResultMessage` with `"b"*4000`, then `UserMessage("c"*4000)`. Call `find_cut(msgs, 0, keep)` for many `keep` values. Check the result is never the tool result index. *Hint:* copy the loop in `test_cut_never_on_tool_result` in `test_queues_compaction.py`.

2. **No compaction below the limit.** Make an `AgentSession` with `Model(context_window=10000)` and a short history. Use `FakeProvider(DONE)` and call `prompt("hi")`. Check that no `CompactionEntry` is in `messages` and only one model call was made. *Hint:* see `small_model`, `compact_agent` and `test_below_threshold_no_compaction` in the same file.

## Recap

- `should_compact`: tokens > `context_window - reserve_tokens`. Tokens come from real `usage` when possible.
- `find_cut` keeps about `keep_recent_tokens` and never cuts on a tool result.
- `serialize_conversation` turns old messages into one text so the model summarizes instead of chatting.
- `summarize` is incremental: new messages + previous summary.
- File lists are built by code and added to the summary.
- `CompactionEntry` is appended; `build_view` makes the model's view. History is never rewritten.
- The session compacts in `_prepare`, before every model call; failure keeps history as is.

**Builds on:** [15 Retry](15-retry.md) · **Next:** [17 Context overflow](17-overflow.md)

## Terms to add to glossary

- **context window** — the most tokens a model can read in one call (`Model.context_window`).
- **compaction** — replacing old history in the model's view with a summary.
- **CompactionEntry** — the marker appended to history: summary, `first_kept_index`, read and modified files.
- **view (LLM view)** — the message list actually sent to the model, built from history by `build_view` and the plugin `context` chain.
- **reserve_tokens** — tokens kept free for the reply and the summary (default 16384).
- **keep_recent_tokens** — about how many recent tokens are kept word for word (default 20000).
- **incremental summary** — updating the previous summary with only the new messages.
- **cut (first_kept_index)** — the index of the first message kept word for word; always a user or assistant message.
