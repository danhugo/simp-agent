# 38 — Decision records

> **Who this is for:** anyone who asks "why is it built like this?" before changing it.
> **What you need first:** [30 Architecture](30-architecture.md) and [32 The server inside](32-server-inside.md). Words: [plugin](glossary.md#plugin), [sandbox](glossary.md#sandbox), [budget](glossary.md#budget).
> **What you will learn:** six big choices, each as a short record: the situation, the choice, why, and what would make us change it.
> **Sources:** `docs/ROADMAP.md`, `NOTES.md`, `docs/superpowers/plans/` (Stage 2 and Stage 3 plans), and the chapters linked below.
> **Verified at commit:** `5c0f47c` (read from the sources above; nothing run).

**Back:** [37 Testing and evals](37-testing.md) · **Next:** [Table of contents](README.md)

## How to read a record

Each record has four parts:

- **Context** — the situation when the choice was made.
- **Decision** — what was chosen.
- **Why** — the reasons written down in the sources.
- **What would change it** — the event that would make us choose again.

A record says only what the sources say. Where a source gives no reason, the record says so.

## 1. Small core, everything else is a plugin

- **Context.** The project wants to grow (server, web, more tools, more providers) without rewrites.
- **Decision.** Keep the library core small and stable. New things plug in through fixed slots: Sandbox, Store, Auth, provider, tool, agent plugin. The core is split into [layers](glossary.md#layer), and a test (`test_layers.py`) keeps imports going one way.
- **Why.** ROADMAP, first line: "keep the core small and stable; everything new plugs in … so providers can be swapped without rewrites." A small core can be read and tested with fakes alone ([30 §4](30-architecture.md#4-why-layers)).
- **Cost.** Sometimes a higher layer must pass a thing down (a callback, an env, a store) instead of the lower layer importing it.
- **What would change it.** Nothing planned. Stage 4 (MCP, skills, memory, sub-agents) is planned as plugins too.
- **Read more:** [30](30-architecture.md), [35](35-tools-plugins.md), [36](36-server-plugins.md).

## 2. SSE + POST, not WebSocket

- **Context.** The browser sends short commands (prompt, steer, abort) and receives a long stream of events.
- **Decision.** Protocol v1: commands are HTTP POST; events come over Server-Sent Events (SSE). [Durable events](glossary.md#durable-event) carry a `seq`; a client that reconnects asks from its offset and gets a [snapshot](glossary.md#snapshot) if needed.
- **Why.** The two directions are different: commands are short requests, events flow one way for a long time. SSE is made for that, works over plain HTTP, and the browser reconnects by itself ([32](32-server-inside.md)). Stage 1 added an SSE heartbeat and bounded queues.
- **What would change it.** ROADMAP (cross-cutting) lists more clients — IDE, mobile, Slack — "over a WebSocket or stdio transport". That would be an extra transport for those clients; nothing in the sources says SSE + POST is replaced for the web.
- **Read more:** [32](32-server-inside.md), [`docs/protocol.md`](../protocol.md).

## 3. SQLite, not Postgres

- **Context.** The server runs on one machine for a few users.
- **Decision.** One SQLite file (`simp.db` in `data_dir`), with WAL turned on. Store is a plugin slot, so another store can be added later.
- **Why.** The Stage 2 plan says "SQLite stays; WAL on" and "No Postgres". ROADMAP deferred "Postgres + Alembic (until multiple replicas)".
- **What would change it.** Running more than one server process (replicas). Since Stage 3, replicas and Postgres are dropped while on one machine (record 5).
- **Read more:** [32](32-server-inside.md), [36](36-server-plugins.md).

## 4. Docker sandbox for several users

- **Context.** With `LocalSandbox`, every user's commands run as the same account on the server machine. One user could read another user's files, the database or `settings.toml`.
- **Decision.** Stage 2: "Docker sandbox required for several users". `check_sandbox` refuses more than one active user with `LocalSandbox`, unless `allow_local_sandbox = true` (for tests). DockerSandbox runs one container per session ([23](23-sandboxes.md)); one workspace folder `<data_dir>/workspaces/<sid>`.
- **Why.** Isolation between users: each session can touch only its own folder ([23 §3](23-sandboxes.md#3-why-docker-for-several-users)). Stage 2 deferred E2B "when a key is provided". Stage 5 plans stronger isolation (Firecracker/gVisor) on own infrastructure.
- **What would change it.** Moving to own infrastructure (Stage 5), or an E2B key (then an E2B sandbox plugin).
- **Read more:** [23](23-sandboxes.md), [26](26-security.md).

## 5. One machine (replicas dropped)

- **Context.** Stage 2 deferred Postgres "until multiple replicas", so replicas looked like a next step.
- **Decision.** Stage 3 (decided 2026-10-12): "Dropped while on one machine: replicas, LISTEN/NOTIFY, session leases, Postgres, BYOK."
- **Why.** The sources do not give a long reason. The Stage 3 plan picks daily-use work instead (idle release, cap on open sessions, accounts, titles, Continue). LISTEN/NOTIFY and session leases are ways for several servers to share sessions, so they go with replicas. BYOK (each user brings their own API key) is dropped too; no reason is written.
- **What follows from it.** Live runs, command queues and SSE subscribers live in the memory of one process ([32](32-server-inside.md)). TLS is left to a tunnel (ROADMAP, Stage 2; see [26](26-security.md)).
- **What would change it.** Load that one machine cannot carry, or Stage 5 (Kubernetes, multi-region).
- **Read more:** [00](00-introduction.md), [ROADMAP](../ROADMAP.md).

## 6. Soft budgets

- **Context.** Several users spend real money on one provider key.
- **Decision.** Money [budgets](glossary.md#budget) per user per day and per [run](glossary.md#run) (defaults `user_day_usd = 2.0`, `run_usd = 0.5`), checked **before** each LLM call, plus a pause/resume [kill switch](glossary.md#kill-switch). A refused call ends the run with an `error_kind="budget"` error, which is never retried.
- **Why.** The check wraps `stream_fn`, so it stops even a long tool loop at its next LLM call, with no change to the core loop (Stage 2 plan). Cost is known only after a call, so a before-call check is the simple place to stop.
- **The price.** Limits can be passed: one call can go over, parallel sessions can pass the check together, running calls are not cut, and compaction is checked but not counted ([24 §6](24-money.md#6-how-limits-can-be-exceeded)).
- **What would change it.** A need for hard limits (for example billing, Stage 5). Until then: set limits with a margin, and set a cap at the provider too.
- **Read more:** [24](24-money.md).

## What to remember

- The core stays small; new features come as plugins.
- SSE + POST because events go one way for a long time; WebSocket is only listed for other clients.
- SQLite and in-memory runs are fine because there is one server process.
- Docker is required once there is more than one user.
- Budgets are soft: checked before a call, not a hard wall.
- If the situation in a record changes, revisit the record before the code.

**Back:** [37 Testing and evals](37-testing.md) · **Next:** [Table of contents](README.md)

**Builds on:** [30](30-architecture.md), [32](32-server-inside.md), [37](37-testing.md).

**Built on by:** nothing — this is the last chapter.
