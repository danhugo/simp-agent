# simp-agent notes

Layers: `ai.py` (messages, Anthropic `stream`) → `agent.py` (loop, `Agent`) → `tools.py` + `cli.py` (coding layer).

Not yet (present in pi, skipped here):
- steering / follow-up message queues
- before/after tool-call hooks
- parallel tool execution
- proxy transport
- compaction (the `transform_context` hook is where it plugs in)
- more providers, TUI, sessions
- retry loop with backoff: core only classifies (`ai.is_retryable`, `ai.is_context_overflow`); the app decides
- auto-compaction on context overflow (use `ai.is_context_overflow` + `transform_context`)

Hardening (done):
- `ai.transform_messages` runs before every LLM call: drops error/aborted assistant turns (kept in history for the UI) and adds a "No result provided" error result for every tool call without one.
- stop_reason `length`: tool calls are not run; error results are added.
- abort during streaming closes the provider stream (generator cancel -> SDK `async with` exit) and keeps partial text.
- subscribers may be async; a raising subscriber ends the run with an error message.
- `Agent.prompt` while streaming raises RuntimeError.
