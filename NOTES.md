# simp-agent notes

Layers: `ai.py` (messages, Anthropic `stream`) → `agent.py` (loop, `Agent`) → `tools.py` + `cli.py` (coding layer).

Not yet (present in pi, skipped here):
- steering / follow-up message queues
- before/after tool-call hooks
- parallel tool execution
- proxy transport
- compaction (the `transform_context` hook is where it plugs in)
- more providers, TUI, sessions
