#!/usr/bin/env bash
# make setup: install everything, write a minimal local config once, then start server + web.
# Everything that differs between machines lives in $SIMP_SERVER_HOME (settings.toml + .env), never in code.
set -euo pipefail
cd "$(dirname "$0")/.."
H="${SIMP_SERVER_HOME:-$HOME/.simp-server}"
export SIMP_SERVER_HOME="$H"

for t in uv pnpm; do
  command -v $t >/dev/null || { echo "missing: $t  (uv: https://docs.astral.sh/uv/  pnpm: https://pnpm.io/installation)"; exit 1; }
done
uv sync
(cd apps/web && pnpm install)

mkdir -p "$H"
if [ ! -f "$H/settings.toml" ]; then
  read -rsp "Anthropic API key (Enter = fake model, no key): " key; echo
  if [ -n "$key" ]; then
    printf 'ANTHROPIC_API_KEY=%s\n' "$key" >> "$H/.env" && chmod 600 "$H/.env"
    cat > "$H/settings.toml" <<'EOF'
default_profile = "sonnet"

[profiles.sonnet]
api = "anthropic-messages"
model = "claude-sonnet-5-5"
context_window = 1000000
max_tokens = 32000
price_in = 3
price_out = 15
EOF
  else
    printf '# fake model (no key): scripted replies, for a first look\n[profiles.fake]\napi = "fake"\nmodel = "fake"\n' > "$H/settings.toml"
  fi
fi

# local login without Google: one user named "local", a fresh token on every run (old link stops working)
if uv run simp-server users | grep -q '^local	'; then token=$(uv run simp-server rotate --name local)
else token=$(uv run simp-server seed --name local); fi

grep -q '^api = "fake"' "$H/settings.toml" && ARGS="--fake-llm"
echo; echo "Open: http://localhost:5173/#login=$token"; echo
exec make dev ARGS="${ARGS:-}"
