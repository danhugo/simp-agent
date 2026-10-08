# simp-agent

## Layout

One package, layered. Each layer imports only the layers to its left (checked by `tests/test_layers.py`):

`ai` <- `agent` <- `coding` <- `session` <- `cli`

- `ai/` — message types, `stream()` + `register_provider`, error classify, `to_dict`/`from_dict`; `ai/providers/` (anthropic, openai_completions).
- `agent/` — generic loop, `Agent` (queues, prepare hook), tools, `ExecutionEnv` + `LocalEnv`, compaction helpers.
- `coding/` — read/write/edit/bash tools, system prompt, AGENTS.md / CLAUDE.md loader.
- `session/` — `AgentSession`: owns an Agent; auto-compaction, overflow recovery, auto-retry with backoff, `SessionStore` persistence. No terminal or file assumptions.
- `cli/` — argparse, printer, `JsonlStore`, print mode. Uses only `AgentSession`.
