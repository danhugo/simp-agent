#!/bin/sh
# e2e server: fresh home (always /tmp/simp-e2e: the Makefile exports SIMP_SERVER_HOME and app.spec.ts reads the token here), one fake profile, a seeded token in $SIMP_SERVER_HOME/token, FakeLLM (deterministic).
set -e
export SIMP_SERVER_HOME=/tmp/simp-e2e SIMP_FAKE_DELAY=0.05
rm -rf "$SIMP_SERVER_HOME" && mkdir -p "$SIMP_SERVER_HOME"
printf 'signup_code = "e2e-code"\nallow_local_sandbox = true\n[profiles.fake]\napi = "fake"\nmodel = "fake"\nprice_in = 10000\nprice_out = 0\n[budget]\nuser_day_usd = 1\nrun_usd = 1\n' > "$SIMP_SERVER_HOME/settings.toml"
uv run simp-server seed --name e2e > "$SIMP_SERVER_HOME/token"
exec uv run simp-server run --port 8767 --fake-llm
