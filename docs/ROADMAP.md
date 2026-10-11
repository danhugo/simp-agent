# Roadmap

Principle for every stage: keep the core small and stable; everything new plugs in
(Sandbox, Store, Auth, provider, tool, agent plugin), so providers can be swapped
without rewrites.

## Done

- **Stage 0 – core.** Agent loop, append-only history + compaction, providers
  (Anthropic, OpenAI-compatible, OpenAI Responses with reasoning), 7 pi tools,
  plugin sockets (tool registry, prompt sections, custom entries, hooks, `Plugin`
  protocol), example plugins (redact_secrets, plan_mode).
- **Stage 1 – local multi-user server.** uv workspace; protocol v1 (SSE + POST,
  seq, offsets, snapshot); FastAPI server (token auth, Host guard, SQLite, files
  API, usage); hardened DockerSandbox; React web UI; Playwright e2e; hardening
  from review (SSE heartbeat, bounded queues, caps, no remote markdown images).
- **Stage 2 – self-hosted on one machine.** Docker sandbox required for several users;
  money budgets per user/day and per run (soft, checked before each LLM call) with a
  pause/resume kill switch and spend in the UI; restart closes interrupted runs; token
  revoke/rotate (also stops the user's LLM calls and open streams), session delete
  (with its files), configurable bind host and allowed hosts; shared `build_model` and
  plugins per profile; JSON logs with `run_id`, launchd service, daily backups with
  retention and a restore drill. DockerSandbox verified end to end (tests, API, web with a real model).
  Deferred: Postgres + Alembic (until multiple replicas), `org_id`, OIDC, rate limit,
  TLS (tunnel handles it), tracing, E2B sandbox plugin (when a key is provided).

## Stage 3 – daily use on one machine (decided 2026-10-12)

Plan: `docs/superpowers/plans/2026-10-12-stage3-daily-use.md`. Stage 2 leftovers
(run budget across follow-ups, one workspace dir); idle sessions release their
container and memory, cap on open sessions; accounts with invite-code sign-up and
password login; LLM-named sessions; web parity (compact, plan mode); Continue after
an interruption; browser notifications; a small eval script.

Later: repo upload/zip download and git diff in the web, approval rules for
unattended runs, web fetch/search tool, read-only admin/usage page, sandbox
egress allowlist, compaction inside one long turn. Dropped while on one machine:
replicas, LISTEN/NOTIFY, session leases, Postgres, BYOK.

## Stage 4 – capabilities via plugins

MCP (external tool servers), skills, memory, sub-agents, plan mode in the web
UI, web search/fetch tools, session sharing and collaboration.

## Stage 5 – own infrastructure and product

Own sandbox infrastructure (Firecracker/gVisor), Kubernetes, multi-region,
billing and plans, regular security review and red-teaming.

## Cross-cutting (any stage)

Evals for agent quality; more clients (IDE, mobile, Slack) over a WebSocket or
stdio transport; compliance (retention, deletion, audit log); cost and latency
tuning (prompt cache, cheaper models for small steps, smarter compaction).
