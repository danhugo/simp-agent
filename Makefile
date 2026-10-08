# make dev: real server (DockerSandbox if docker runs, else LocalSandbox) + web on http://127.0.0.1:5173
export SIMP_SERVER_HOME ?= $(HOME)/.simp-server
PORT ?= 8766

dev:
	@mkdir -p $(SIMP_SERVER_HOME)
	@if docker info >/dev/null 2>&1; then uv run simp-server build-sandbox >/dev/null; export SIMP_SANDBOX=docker; fi; \
	uv run simp-server run --port $(PORT) $(ARGS) & trap "kill $$!" EXIT; \
	cd apps/web && SIMP_SERVER=http://127.0.0.1:$(PORT) pnpm dev

e2e:
	cd apps/web && pnpm e2e

.PHONY: dev e2e
