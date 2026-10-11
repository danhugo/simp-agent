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

### Budgets

Each LLM call costs `input * price_in / 1e6 + output * price_out / 1e6` (prices per profile, USD per 1M tokens).
A profile with no prices costs $0 and never hits a budget (the server warns at startup). Before every LLM call the
server refuses with a `budget` error when the user's spend since local midnight or the current run's spend is over limit:

```toml
[profiles.luna]
price_in = 3
price_out = 15

[budget]  # defaults
user_day_usd = 2.0
run_usd = 0.5
```

Kill switch: `uv run simp-server pause` (creates `<data_dir>/PAUSED`) refuses every LLM call at once, on running
servers too; `uv run simp-server resume` lifts it. The web header shows today's spend and limit.

### Running as a service (macOS launchd)

Logs are JSON lines on stderr (`{"ts", "level", "msg", "run_id", "session", "user", ...}`).
```sh
for p in server backup; do
  sed "s#__REPO__#$PWD#g; s#__HOME__#$HOME#g" deploy/launchd/com.simp.$p.plist > ~/Library/LaunchAgents/com.simp.$p.plist
  launchctl load ~/Library/LaunchAgents/com.simp.$p.plist
done
```
`com.simp.server` keeps the server up on :8766 with `SIMP_SANDBOX=docker` (log: `~/.simp-server/server.log`);
`com.simp.backup` runs a backup every day at 03:00 into `~/.simp-server/backups`.

### Backups and restore

`uv run simp-server backup --to DIR` writes `DIR/simp-<YYYYmmdd-HHMMSS>.tar.gz` with `simp.db` (online snapshot, safe while
the server runs), `settings.toml`, `workspaces/` and `sandboxes/`. `.env` (keys) is never included; back it up separately.
Restore: stop the server (`launchctl unload ~/Library/LaunchAgents/com.simp.server.plist`),
`tar xzf <file> -C ~/.simp-server`, start it again (`launchctl load ...`).
