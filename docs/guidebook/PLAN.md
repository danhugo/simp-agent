# Guidebook plan (v1, draft for Critic review)

Edition pin: master `1b03493`. Every code reference is `path:line@sha` (sha = the commit
the reader is looking at). No reference without a sha.

## Goal and reader

A Python developer who knows HTTP and pytest but has never built an LLM agent can
rebuild simp-agent from scratch and explain how it works and WHY each choice was made,
with trade-offs vs alternatives.

Language: Vietnamese prose (simple sentences), code / identifiers / commit messages in
English. (Owner to confirm.)

## Rules (non-negotiable)

1. Never invent facts. Every technical claim cites code (`path:line@sha`), a test
   (`[test: file::name]`), a doc (`[doc: file:line]`) or a commit (`[commit: sha]`).
2. Every "why" carries a tag: `[doc]`, `[commit]`, `[test]`, `[pi: path:line]` (what pi
   does), or `[inferred]`. `[inferred]` must name the alternative and is never the only
   support for a chapter's main decision.
3. Code is quoted from the repo, not retyped (snippet markers when tooling exists).
4. Diagrams: Mermaid in markdown. SVG only for the 1-2 big architecture overviews.
5. Each chapter ends with something that RUNS (a command + expected output or a test).

## Spine: the rebuild path follows the real git history

| Milestone | Commit(s) | What the reader builds | Runs |
|---|---|---|---|
| M1 | 3603861 | ai layer, agent loop, 4 tools, print-mode CLI | `simp-agent "task"` with a fake provider |
| M2 | f41b8a0 | history repair, real abort, async subscribers, truncated tool calls, error classify | hardening tests |
| M3 | 01b12ad, d78f9d7, 89c9634, 3faebe1 | steering/follow-up queues, compaction (append-only + view) | queue/compaction tests |
| M4 | dd6b6f4, f266baf, a5b7ba7 | provider dispatch, OpenAI-compatible, Responses + reasoning | provider parser tests |
| M5 | 5173569, 691e2cc, fd7db38 | pluggability refactor, subpackages, AgentSession, layer test | layer test |
| M6 | 7ce90b0, 14653a9, 90dae6f, 471fdb9 | approvals, REPL + live region, bash timeout, full tool set | CLI + tui tests |
| M7 | e947f83, a07bb25 | plugin sockets + example plugins + security review fixes | socket tests |
| M8 | e097e49, 68e4ce1, 95ec9d5 | uv workspace, ExecutionEnv file API, DockerSandbox + conformance | conformance suite |
| M9 | 66dad59, 63cb4aa, 2254c0c, 8ef834d | protocol v1, FastAPI server, hardening | server tests |
| M10 | 7da8a86, 9a5e204, 5138221 | web UI (SSE client contract), e2e | e2e |
| M11 | Stage 2 + Stage 3 commits | budgets, accounts, ops, backups, evals | stage tests |

(Analyst verifies this table: which commits build and pass their tests; fix the rows.)

## Outline (one chapter per milestone, plus framing)

- Ch0 Orientation: what an agent harness is; pi; the layers; how to read this book; setup with a fake LLM (no API key).
- Ch1-Ch11 = M1..M11. Primer boxes at first use: asyncio (Ch1), JSON Schema (Ch1), SSE (Ch9), Docker isolation (Ch8), React state (Ch10).
- Ch12 Testing strategy (fakes, conformance suites, pty+pyte, Playwright, flake hunting with the real race bugs found).
- Ch13 Security lessons (the key leak via a workspace file, option injection, image exfiltration, DNS rebinding, redaction).
- Ch14 Troubleshooting (built from real bug-fix commits and test names).
- Appendices: glossary; decision log (all rationale tags in one table); "pi did X" boxes live inside chapters.

## Chapter template

Goal -> What you build (milestone diff summary) -> Walkthrough (quoted code with refs) ->
Flow (Mermaid sequence/flowchart) -> Why (tagged) -> Alternatives and trade-offs ->
pi box -> Run it (command + expected output) -> What breaks (troubleshooting from real
bugs) -> Exercises (2-3, each with a failing test if possible).

## Team and process (gradual, not one-shot)

- Analyst: per milestone, a research brief in `docs/guidebook/_research/Mx.md`: files,
  key functions with refs, flows, every rationale source found (tagged), open questions.
- Writer: drafts one chapter at a time from the brief, in `docs/guidebook/chNN-*.md`.
- Critic: fact-checks each chapter (every ref resolves, claims match code, snippets run,
  "Run it" works at that milestone, inferred-vs-documented tags are honest).
- Dev1 (tooling): `scripts/check_book.py` (resolve every `path:line@sha`, run extracted
  code blocks, check milestone commands), mkdocs build later.
- Lead: edits, accepts, keeps the decision log.
Per chapter: brief -> draft -> fact-check -> revise -> accept. Batches of 1-2 chapters;
the next batch starts only after the previous is accepted.

## Out of scope for v1

English translation, React internals beyond the SSE client contract, publishing site
(markdown in `docs/guidebook/` first; mkdocs later).
