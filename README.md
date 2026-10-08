# simp-agent

## Layout

One package, layered. Each layer imports only the layers to its left (checked by `tests/test_layers.py`):

`ai` <- `agent` <- `coding` <- `session` <- `cli`

- `ai/` — message types, `stream()` + `register_provider`, error classify, `to_dict`/`from_dict`; `ai/providers/` (anthropic, openai_completions).
- `agent/` — generic loop, `Agent` (queues, prepare hook), tools, `ExecutionEnv` + `LocalEnv`, compaction helpers.
- `coding/` — read/write/edit/bash tools, system prompt, AGENTS.md / CLAUDE.md loader.
- `session/` — `AgentSession`: owns an Agent; auto-compaction, overflow recovery, auto-retry with backoff, `SessionStore` persistence. No terminal or file assumptions.
- `cli/` — argparse, settings profiles (`~/.simp-agent/settings.json`), `JsonlStore` (`~/.simp-agent/sessions/<cwd-slug>/<id>.jsonl`), print mode, and `repl.py` (prompt_toolkit + rich, extra `cli`: `uv sync --extra cli`). Uses only `AgentSession`. Tool approval: `AgentSession(approve=...)`; `--yes` skips it.
