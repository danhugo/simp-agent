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

## Stage 2 – self-hosted on one machine (decided 2026-10-11)

The local machine is the deploy target; no cloud deploy. Network exposure (tunnel,
TLS) is out of scope for now; a tunnel such as Cloudflare provides TLS later.
LLM: OpenAI-compatible API with an auth key (shared platform key, held by the server).

Deliverables, in order:

1. E2e on the local stack early, as the safety net for the items below.
2. DockerSandbox is the default; with several users, refuse to start on LocalSandbox.
3. Budgets: per user/day ($2) and per run ($0.50), `error_kind=budget`; price per
   1M input/output tokens configured per profile; kill switch; usage in the UI.
4. Restart safety: `runs` table with `boot_id`; on startup orphaned runs become
   `interrupted`. Resume is Stage 3.
5. Token revoke/rotate (CLI), session delete; configurable bind host and allowed hosts.
6. Shared wiring helper (model + session factory) used by CLI and server;
   agent plugins configurable per profile.
7. Ops: JSON logs with `run_id`; run as a service (launchd/systemd); scheduled
   backup of `simp.db` (WAL on) and `workspaces/`, one restore drill.

Exit criteria: killing the server mid-run gives a clean `interrupted` state; a
runaway loop stops at its budget; a test proves one user cannot read another
user's data; e2e passes on the local stack; one backup restore done.

Deferred: Postgres + Alembic (until multiple replicas), `org_id`, OIDC, rate limit,
TLS (tunnel handles it), tracing, E2B sandbox plugin (when a key is provided).

## Stage 3 – scale and reliability

Multiple server replicas with event fan-out (Postgres LISTEN/NOTIFY first) and
session leases; resume runs after restart (careful with tool side effects);
background runs + notifications; BYOK model keys; sandbox pause/resume;
approval rules for unattended runs; admin UI and cost dashboards; start evals.

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
