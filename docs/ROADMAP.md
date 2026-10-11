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

## Stage 2 – hosted beta (single region, single replica, ~20 invited users)

Deliverables, in order:

1. Shared wiring helper (model + session factory) used by CLI and server;
   agent plugins configurable per profile.
2. Ops basics: server Dockerfile, compose (server + Postgres + web), JSON logs
   with `run_id`, traces (Opik/OTel).
3. Full `Store` protocol + conformance suite; Postgres store; Alembic migrations.
   SQLite stays for dev.
4. Restart safety: `runs` table with `boot_id`; on startup orphaned runs become
   `interrupted` (no stuck sessions). Resume is Stage 3.
5. Identity/tenancy: OIDC auth plugin (static token stays for dev), `org_id` on
   every row, session delete, token revoke, configurable allowed hosts.
6. Cost/safety before the first outside user: budget per user/day and per run
   (`error_kind=budget`), rate limit, usage in the UI, kill switch.
7. Cloud sandbox plugin (E2B or Daytona): egress denied by default (allowlist),
   no secrets inside, file I/O via the provider API. DockerSandbox stays for dev.
8. Deploy to one target with managed Postgres (backups) + e2e against the URL.

Exit criteria: Store and Sandbox conformance suites pass on Postgres and the
cloud sandbox; killing the server mid-run gives a clean `interrupted` state;
a test proves one org cannot read another org's data; a runaway loop stops at
its budget; e2e passes against the deployed URL in CI; one backup restore done.

Open decisions: hosting (Fly/Render vs own VM/K8s), sandbox provider (E2B vs
Daytona), who pays for the LLM (platform key + caps vs BYOK), login provider,
network policy for unattended runs, budget ceiling and data retention.

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
