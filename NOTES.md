# simp-agent notes

Layers: `ai.py` (messages, `stream` dispatch by `model.api`) → `providers/` (anthropic, openai_completions) → `agent.py` (loop, `Agent`) → `tools.py` + `cli.py` (coding layer).

Not yet (present in pi, skipped here):
- before/after tool-call hooks
- parallel tool execution
- proxy transport
- compaction split-turn cut (pi isSplitTurn): we only cut at user/assistant messages, so one huge turn cannot be compacted
- more providers (only anthropic-messages + openai-completions), TUI, sessions
- OpenAI `reasoning_content`/`reasoning` deltas are ignored: a reasoning model may return empty content
- retry loop with backoff: core only classifies (`ai.is_retryable`, `ai.is_context_overflow`); the app decides

Hardening (done):
- `ai.transform_messages` runs before every LLM call: drops error/aborted assistant turns (kept in history for the UI) and adds a "No result provided" error result for every tool call without one.
- stop_reason `length`: tool calls are not run; error results are added.
- abort during streaming closes the provider stream (generator cancel -> SDK `async with` exit) and keeps partial text.
- subscribers may be async; a raising subscriber ends the run with an error message.
- `Agent.prompt` while streaming raises RuntimeError.

Queues + compaction (done):
- `Agent.steer()` / `follow_up()`; steering polled at loop start, after each tool batch, and after `prepare_next_turn`.
- History is append-only. Compaction appends `CompactionEntry(summary, first_kept_index)`; `build_view()` gives the LLM view.
- On context overflow, `Agent` compacts once and continues; a second overflow ends with the error.
