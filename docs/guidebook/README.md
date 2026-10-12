# simp-agent guidebook

Status: **outline v2 — locked after debate (critic + wide view).** Describes Stage 3. Written: 00, 01, 10, 11, 12, 13, 20, 21, 22, 25.
Tags: [T] tutorial, [H] how-to, [R] reference, [E] explanation.

## What simp-agent is

simp-agent is a small coding agent: a Python library (`packages/simp_agent`) with a
small, stable core and plug-in points, plus three apps built on it — a terminal CLI
(`apps/cli`), a multi-user server (`apps/server`) and a web UI (`apps/web`).
See [ROADMAP](../ROADMAP.md) for where it is going.

## Who this book is for

Three readers, in this order. Each part says who it is for at the top.

1. **User** — wants to chat with the agent in the terminal or the browser.
2. **Operator** — runs the server for a small team on one machine.
3. **Developer** — changes the library, writes a provider, tool or plugin.

Everyone reads Part 0. Then read only your part; parts link back to what they need.

## Outline

### Part 0 — Start here (everyone)
- [00 Introduction and core ideas](00-introduction.md) [E]: what it is and is not, the three apps, the main terms (links to glossary), how to read this book
- [01 Quick start](01-quick-start.md) [T]: two paths — CLI in 2 minutes; web via `make dev` + `seed`. No API key? web: `make dev ARGS=--fake-llm`, server: `simp-server fake` (the CLI has no fake mode)

### Part 1 — Using simp-agent (User)
- [10 The CLI](10-cli.md) [H]: print mode, REPL, profiles, tool approval, `--yes`, where sessions are saved
- [11 The web UI](11-web.md) [H]: login (token or signup code), sessions, files, compact, Continue, notifications, spend
- [12 CLI vs web feature table](12-cli-vs-web.md) [R] — one place; other chapters link here
- [13 Working well with the agent](13-working-well.md) [H]: AGENTS.md / CLAUDE.md, long sessions; each tip tagged CLI/web/both

### Part 2 — Running the server (Operator)
- [20 Operator tutorial](20-operator-tutorial.md) [T]: fresh Mac → DockerSandbox server, two users, a budget, a restore drill
- [21 Configuration reference](21-configuration.md) [R]: profiles, hosts, plugins, capacity (`idle_minutes`, `max_open_sessions`)
- [22 Users and accounts](22-users.md) [H]: tokens, one shared signup code, passwords, revoke/rotate
- [23 Sandboxes](23-sandboxes.md) [E] — home chapter for sandbox: Local vs Docker, why Docker for several users
- 24 Money and limits [H]: budgets, kill switch, how limits can be exceeded
- [25 Day-to-day ops](25-ops.md) [H]: logs, launchd (macOS only), backups (what they do not cover), upgrades
- 26 Security model and known gaps [E]: dated list, links ROADMAP
- 27 Troubleshooting [H]: 401 after rotate, budget errors, Docker down, provider errors

### Part 3 — Inside simp-agent (Developer)
- 30 Architecture [E]: the layers and why; layout details point to code and `test_layers.py`
- 31 How one turn flows [E]: ai → agent → session (stream, loop, tools, retry, compaction home)
- 32 The server inside [E]: runs, storage; protocol links to `docs/protocol.md`, not copied
- 33 Developer tutorial [T]: write a tool plugin, test with `FakeProvider`, load it via `[plugins]`
- 34 Extending: providers [H]
- 35 Extending: tools and agent plugins [H] (stubs reserved for Stage 4: MCP, skills, memory, sub-agents)
- 36 Extending: server plugins — Sandbox, Store, Auth [H]
- 37 Testing and evals [H]: FakeProvider, EnvConformance, fake server, e2e, `evals/run.py`
- 38 Decision records [E]: SSE + POST, SQLite, Docker, small core

### Appendix
- [glossary.md](glossary.md) — every term defined once; chapters link here
- [changelog.md](changelog.md) — book changes, tied to project commits

## Writing rules
- Plain, simple English. Short sentences. One idea per paragraph.
- Each chapter starts with: who it is for, what you need first (links), what you will learn.
- Each chapter ends with: "Next" links and "Built on by" links.
- A term is defined only in the glossary; the first use in a chapter links to it.
- Facts come from the code. Every command and config example is tested before commit.
- Each topic has one home chapter; others link to it, never repeat it.
- Each chapter header lists the code paths it covers and "verified at commit X".
- One section per task. Writer drafts, Reviewer checks, Editor merges.

## Plan
1. Outline debated and locked (v2).
2. Write Part 0 first (00 + glossary seed, then 01), one section at a time.
3. Then Part 1, Part 2, Part 3, in order.
4. Keep up to date: every project change → a book-update task. Full re-read after each part and at each new stage.
5. Source of truth: the book. Later, the README shrinks to pitch + quick start + links (separate task, after Part 2).
6. Later: generate reference pages (CLI help, settings keys) and add a CI drift check.

Open issue for project: ROADMAP lists web plan mode in both Stage 3 and Stage 4.
