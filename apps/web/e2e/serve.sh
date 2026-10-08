#!/bin/sh
# e2e server: fresh home, one fake profile, a seeded token in $SIMP_SERVER_HOME/token, FakeLLM (deterministic).
set -e
export SIMP_SERVER_HOME="${SIMP_SERVER_HOME:-/tmp/simp-e2e}" SIMP_FAKE_DELAY=0.05
rm -rf "$SIMP_SERVER_HOME" && mkdir -p "$SIMP_SERVER_HOME"
printf '[profiles.fake]\napi = "fake"\nmodel = "fake"\n' > "$SIMP_SERVER_HOME/settings.toml"
uv run simp-server seed --name e2e > "$SIMP_SERVER_HOME/token"
exec uv run simp-server run --port 8767 --fake-llm
