# simp-agent

## Layout

The library `packages/simp_agent` (`src/simp_agent/`) is layered. Each layer imports only the layers to its left, and
the apps import only the library (checked by `packages/simp_agent/tests/test_layers.py`):

`ai` <- `agent` <- `coding` <- `session` <- `plugins` <- `testing`;  apps: `apps/cli` (`simp_cli`), `apps/server` (`simp_server`)

- `ai/` — message types, `stream()` + `register_provider`, error classify, `to_dict`/`from_dict`; `ai/providers/` (anthropic, openai_completions, openai_responses).
- `agent/` — generic loop, `Agent` (queues, prepare hook), tools, `ExecutionEnv` + `LocalEnv`, compaction helpers.
- `coding/` — read/write/edit/bash tools, system prompt, AGENTS.md / CLAUDE.md loader.
- `session/` — `AgentSession`: owns an Agent; auto-compaction, overflow recovery, auto-retry with backoff, `SessionStore` persistence. No terminal or file assumptions.
- `plugins/` — `RedactSecrets`, `PlanMode`. `testing/` — `FakeProvider`, `EnvConformance`.
- `apps/cli` (`simp_cli/__init__.py`) — argparse, settings profiles (`~/.simp-agent/settings.json`), `JsonlStore` (`~/.simp-agent/sessions/<cwd-slug>/<id>.jsonl`), print mode, and `repl.py` + `components.py` (prompt_toolkit + rich, extra `cli`: `uv sync --extra cli`). Uses only `AgentSession`. Tool approval: `AgentSession(approve=...)`; `--yes` skips it.

## Server (`apps/server`)

Home: `$SIMP_SERVER_HOME` or `~/.simp-server` (holds `settings.toml`, `.env` with model keys, `simp.db`).
`uv run simp-server seed --name hung` prints a token once; `uv run simp-server run [--port 8766]` serves on 127.0.0.1
(`Authorization: Bearer <token>`). `uv run simp-server fake` is the replay server without an LLM.

```toml
default_profile = "luna"

[plugins]  # optional; defaults: LocalSandbox, SqliteStore, StaticTokenAuth
sandbox = "simp_server.sandboxes.docker:DockerSandbox"  # needs `uv run simp-server build-sandbox` once

[sandbox]  # DockerSandbox options (these are the defaults)
# workspaces_dir = "<data_dir>/workspaces"
image = "simp-sandbox:latest"
network = "none"
memory = "1g"
cpus = "1"
pids_limit = 256

[profiles.luna]
api = "openai-responses"
model = "openai/gpt-6-luna"
base_url = "https://mlapi.run/.../v1"
context_window = 922000
max_tokens = 32000
api_key_env = "OPENAI_API_KEY"  # the key itself goes in .env or the server's env, never here
```

```sh
uv run simp-server seed --name me   # prints your token once; paste it in the web login
make dev                            # server on :8766 (DockerSandbox if docker runs, else LocalSandbox) + web on :5173
```
`make dev ARGS=--fake-llm` uses a scripted model (no key). E2e (real server + fake model): `make e2e`.
