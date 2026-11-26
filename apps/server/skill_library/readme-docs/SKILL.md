---
name: readme-docs
label: README & docs writing
description: "Write or improve project documentation: README, getting-started guides, API docs, how-tos, changelogs, docstrings, architecture notes. Use when the user wants code or a project explained in writing."
license: MIT
source: simp
version: 1
---

# README & Docs Writing

## First, read the project

`ls`, package files (`package.json`, `pyproject.toml`, `Makefile`), entry points, existing docs, tests, CI config, `.env.example`. Run `--help` of CLIs. Docs must match what the code actually does: verify every command you document by running it in the sandbox when possible.

## README structure

```markdown
# Project name
One sentence: what it does and for whom.

(optional badge line / screenshot)

## Features            3–6 bullets, concrete
## Quick start         copy-pasteable: install → configure → run, < 5 commands
## Usage               the 2–3 most common tasks with examples and real output
## Configuration       table: variable | default | description
## Development         setup, tests, lint, project layout (short tree)
## Deployment          if relevant
## Troubleshooting     known errors → fixes
## Contributing / License
```

Small project? Keep only title, one-liner, quick start, usage, license.

## Doc types (Diátaxis)

Keep them separate: **tutorial** (learn by doing, one happy path), **how-to** (solve one task, assumes knowledge), **reference** (complete, dry: API, CLI flags, config), **explanation** (why/how it works, trade-offs).

## Style

- Second person, present tense, active voice: "Run `make test`."
- Lead with the goal of each section; show then tell (example first).
- Code blocks with language tags; commands without `$` prompts so they copy cleanly; show expected output.
- Define terms once; consistent names; relative links between docs.
- No "simply", "just", "obviously".

## API / code docs

- Function docstrings: what it does, params with types and units, return, errors raised, a short example. Match the project's style (Google / NumPy / JSDoc).
- HTTP API: endpoint, method, auth, params, request/response examples, error codes.

## Changelog (Keep a Changelog)

`## [1.2.0] - 2026-11-26` then `### Added / Changed / Fixed / Removed`, user-facing wording. Build from `git log --oneline v1.1.0..HEAD`.

## Architecture notes

Purpose, components and responsibilities, data flow (ASCII or Mermaid diagram), key decisions with reasons, how to extend.

Write files into the repo in `/work`, show the user a summary of what you documented and anything you couldn't verify.
