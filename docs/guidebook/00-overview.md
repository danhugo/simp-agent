# 00 Overview: what we build

**Goal:** See the whole of simp-agent before building it piece by piece.

**Builds on:** — (start here) · **Next:** [01 Pick + Clean](01-pick-clean.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent --> coding --> session --> plugins --> testing
```

Nothing is built yet. This chapter is the map: what simp-agent is, its six layers, and the order we build them in.

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/tests/test_layers.py` — `LAYERS`, `APPS`, `test_layers`

## What simp-agent is

simp-agent is a small **[coding agent](glossary.md#coding-agent)**. You give it a task in plain words, like "write `fizzbuzz.py`". It asks a language model what to do. The model answers with text, or with **[tool calls](glossary.md#tool-call)** such as "read this file" or "run this command". simp-agent runs those tools, sends the results back to the model, and repeats until the model says it is done.

That repeat is the heart of every coding agent:

```mermaid
flowchart LR
    U[User task] --> M[Model]
    M -->|text only| D[Done]
    M -->|tool calls| T[Run tools]
    T -->|tool results| M
```

Everything else in this book exists to make this loop **safe**, **testable**, **long-lived** and **usable** from a terminal or a browser.

The project has three kinds of code:

| Part | Folder | What it is |
|---|---|---|
| The library | `packages/simp_agent/src/simp_agent/` | The agent itself. No UI, no server. |
| The apps | `apps/cli/`, `apps/server/`, `apps/web/` | Ways to use the library: a terminal app, an HTTP server, a browser client. |
| Checks and running | `evals/`, `deploy/` | Real tasks that measure the agent, and files to run the server on one machine. |

## The layer map

The library is split into six **[layers](glossary.md#layer)**. Each layer is one folder under `packages/simp_agent/src/simp_agent/`:

```mermaid
flowchart LR
    ai --> agent --> coding --> session --> plugins --> testing
    session -.used by.-> apps["apps: cli, server (+ web)"]
```

Read the arrow as "is used by". `ai` is used by `agent`, `agent` by `coding`, and so on.

| Layer | What it holds (real names) |
|---|---|
| `ai` | Message types (`UserMessage`, `AssistantMessage`, `ToolCall`, ...), `stream()`, `register_provider()`, and the real providers in `ai/providers/`. |
| `agent` | `agent_loop()`, the `Agent` class, `AgentTool`, the `ExecutionEnv` protocol and `LocalEnv` (`agent/env.py`), compaction helpers. |
| `coding` | The coding tools (`make_tools()` in `coding/tools.py`), `system_prompt()`, `load_context_file()`. |
| `session` | `AgentSession`: owns an `Agent` and adds retry, compaction, overflow recovery, saving (`SessionStore`) and plugins (`PluginAPI`). |
| `plugins` | Two built-in plugins, `RedactSecrets` and `PlanMode`, and `build_plugins()`. |
| `testing` | `FakeProvider`, `FakeEnv` and `EnvConformance`: helpers for tests. |

### The one rule: import only downward

A layer may import the layers to its left, never the ones to its right. And the library never imports the apps. So `ai` knows nothing about tools, and `agent` knows nothing about files on disk or about sessions.

**Why?** Each layer can be understood and tested alone. When you read chapter 05 (the loop), you do not need to know about sessions. When something breaks in `ai`, you know nothing above it caused the bug. And you can replace a top part (for example, the CLI) without touching the core.

This rule is not just a promise. A test checks it on every run.

## Test it: the layer test

`packages/simp_agent/tests/test_layers.py` reads every `.py` file in the library, finds its imports with Python's `ast` module, and fails if a file imports a layer to its right, or an app (`simp_cli`, `simp_server`):

```text
LAYERS = ai, agent, coding, session, plugins, testing    // left to right
APPS   = simp_cli, simp_server

FUNCTION test_layers():
    bad = empty list
    FOR EACH .py file in the library:
        src = the layer this file sits in (or none)
        FOR EACH import in the file:
            IF it imports an app:
                ADD "imports app ..." to bad
                go to next import
            dst = the layer it imports (or none)
            IF dst is none OR src == dst:
                go to next import                   // same layer, or not ours: fine
            IF src is none OR dst is to the RIGHT of src:
                ADD "imports dst" to bad            // forbidden direction
    FAIL the test if bad is not empty
```

Real code: [packages/simp_agent/tests/test_layers.py](../../packages/simp_agent/tests/test_layers.py) (`test_layers`)

Note two details:

- "dst is to the RIGHT of src" (in the code: `LAYERS.index(dst) > LAYERS.index(src)`) is the forbidden case.
- A file that sits in no layer (`src is None`, for example the package's top `__init__.py`) may not import any layer at all.

Run it:

```sh
uv run pytest packages/simp_agent/tests/test_layers.py -q
```

If you add `from ..session import AgentSession` inside `agent/`, this test fails and prints the file name. That is the point: the layer map stays true as the code grows.

## The apps on top

The apps use the library; they are never used by it.

- **CLI** (`apps/cli/`, package `simp_cli`): a terminal app. It uses only `AgentSession`. Chapter 19.
- **Server** (`apps/server/`, package `simp_server`): runs sessions for many users over HTTP. Key classes in `server.py`: `Run`, `SessionManager`, the `Sandbox`, `Store` and `Auth` protocols. Chapters 20–24.
- **Web client** (`apps/web/`): a TypeScript browser app. It talks to the server through the protocol; its types are generated into `protocol.gen.ts`. Chapter 25.

```mermaid
flowchart TB
    subgraph lib [simp_agent library]
      ai --> agent --> coding --> session --> plugins --> testing
    end
    session --> cli[apps/cli]
    session --> server[apps/server]
    server -->|HTTP protocol| web[apps/web]
    evals[evals/run.py] --> lib
    deploy[deploy/launchd] -.runs.-> server
```

## The build path

We build in the same order as the layers: bottom first. Each chapter adds one capability on top of the last one, and each chapter has a test.

| Part | Chapters | What you have at the end |
|---|---|---|
| 1 · Talk to a model (`ai`) | [01](01-pick-clean.md)–[04](04-label-test.md) | Pick + Clean (with the message types), Translate + Send, Parse, Label + a fake model for tests. |
| 2 · The loop (`agent`) | [05](05-agent-loop.md)–[08](08-hooks-approval.md) | A loop that runs tools, sends events, can be stopped, steered and checked. |
| 3 · Coding (`coding`) | [09](09-exec-env.md)–[12](12-evals.md) | A safe place to touch files, real coding tools, a system prompt, evals. |
| 4 · Sessions (`session`, `plugins`) | [13](13-session.md)–[18](18-profiles-plugins.md) | Saved conversations, plugins, retry, compaction, overflow recovery, profiles. |
| 5 · Apps | [19](19-cli.md)–[26](26-system-tests-deploy.md) | CLI, server, transport, store, limits, Docker sandbox, web client, deploy. |
| Wrap-up | [27](27-limits-choices-extend.md) | Why it is built this way, where it stops, how to extend it. |

**Why bottom first?** Every chapter can then be tested with what already exists. Chapter 04 builds `FakeProvider` at the end of Part 1 on purpose: with a fake model, every later chapter can test the loop, tools and sessions without a network or an API key.

## Capability table

Which chapter adds which feature, and in which layer it lives:

| Feature | Chapter | Where in the code |
|---|---|---|
| Message types | 01 | `ai` |
| Real providers (Translate + Send) | 02 | `ai/providers/` |
| Parse into one message | 03 | `ai` |
| Label + fake model for tests | 04 | `ai`, `testing` (`FakeProvider`) |
| Agent loop | 05 | `agent` (`agent_loop`) |
| Events and abort | 06 | `agent` |
| Steering | 07 | `agent` (`Agent`) |
| Hooks and approval | 08 | `agent`, `session` |
| Execution environment | 09 | `agent/env.py` |
| Coding tools | 10 | `coding/tools.py` |
| System prompt | 11 | `coding` |
| Evals | 12 | `evals/` |
| Sessions and saving | 13 | `session` |
| Plugins | 14 | `session` (`PluginAPI`) |
| Retry | 15 | `session` |
| Compaction | 16 | `agent/compaction.py`, `session` |
| Context overflow | 17 | `session` |
| Profiles, built-in plugins | 18 | `session/profile.py`, `plugins` |
| CLI | 19 | `apps/cli` |
| Server run, transport, store, limits | 20–23 | `apps/server` |
| Docker sandbox | 24 | `apps/server/sandboxes` |
| Web client | 25 | `apps/web` |
| System tests, deploy | 26 | `apps/web/e2e`, `deploy/` |

## The running example

Every chapter uses the same small task, taken from the real eval file `evals/tasks/fizzbuzz.toml`:

```toml
prompt = """Write fizzbuzz.py with a function fizzbuzz(n) that returns a list of strings for 1..n:
"Fizz" for multiples of 3, "Buzz" for multiples of 5, "FizzBuzz" for both, else the number."""
```

The same file has a `check` that imports `fizzbuzz` and asserts the result, so we know when the agent got it right.

We follow this task as the system grows:

- In Part 1 it is just a `UserMessage` sent to a model.
- In Part 2 the model answers with a tool call, and the loop runs it.
- In Part 3 a real `write` tool creates `fizzbuzz.py`, and the eval checks it.
- In Part 4 the conversation is saved and can be resumed.
- In Part 5 you type the task in a terminal or a browser.

## Why this way

> **A small core, layered, with fakes.** simp-agent keeps the core small and strict (layers that only import downward) and puts extra behaviour in plugins and apps. A fake model makes every layer testable from day one. The cost: some features (like approval or saving) are split across layers, so you must know which layer owns what. This chapter's layer map is that guide.

## Recap

- simp-agent is a loop: model → tool calls → tool results → model, until done.
- The library has six layers, `ai` ← `agent` ← `coding` ← `session` ← `plugins` ← `testing`; the apps sit on top.
- `test_layers.py` enforces "import only downward".
- We build bottom up, one capability per chapter, with the fizzbuzz task as the running example.

**Builds on:** — · **Next:** [01 Pick + Clean](01-pick-clean.md)
