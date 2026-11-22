# Skills in the core agent — design

Date: 2026-11-23 · Status: draft for review

## Problem

PR #37 added skills (pptx/docx/xlsx/pdf), but only in the server. The server adds a prompt
section that says "Read /opt/simp/skills/<name>/SKILL.md". The agent's `read` tool refuses that path:

- E2B: `SANDBOX_DIRS = ("/work", "/home/user", "/tmp")` (`apps/server/src/simp_server/sandboxes/e2b.py:39`)
  → `PermissionError: path escapes root: /opt/simp/skills/pptx/SKILL.md`.
- Docker: file tools read the host workspace dir (`sandboxes/docker.py:183`), so any path outside it fails.

`packages/simp_agent` has no idea what a skill is. We want skills as a core feature.

## Goals

1. A skill loads in one of two ways:
   - **Explicit**: the user picks a skill (a button in the chat box, or `/pptx`). It loads at once, with no tool call.
   - **Agent-chosen**: the user writes a normal prompt; the model sees a catalog (name + description) and
     calls `load_skill(name)` when the task fits.
2. Only the catalog sits in the prompt. Full SKILL.md text enters context only when loaded (progressive disclosure).
3. Built-in skills and, later, user-added skills go through one interface.
4. No change to the agent loop itself; use the existing plugin hooks.

Non-goals: keyword/regex triggers; embedding-based skill selection; a skill marketplace.

## Design

### Core: `simp_agent/plugins/skills.py`

```python
class SkillSource(Protocol):
    def list(self) -> list[dict]: ...                       # [{name, label, description, sandbox_dir}]
    async def read(self, name: str, path: str = "SKILL.md") -> str: ...

class DirSkillSource:      # <root>/<name>/SKILL.md with frontmatter; sandbox_dir given per source
class MultiSkillSource:    # several sources; later ones override earlier ones by name

class Skills:              # the plugin
    def __init__(self, source: SkillSource, enabled: Callable[[], set[str]] | None = None): ...
```

Hooks used (all already exist in `session/__init__.py`):

| Hook | What the plugin does |
|---|---|
| `setup(api, cfg)` | `register_tool(load_skill)`; `add_prompt_section("skills", catalog_fn, 6)` |
| prompt section (rebuilt every turn) | Catalog of enabled skills: `- pptx: <description>` + one line on how to use `load_skill` |
| `before_agent_start(payload)` | For each name in `payload["skills"]` (explicit pick): read SKILL.md, return it as an extra `UserMessage` |
| tool `load_skill(name, path?)` | Agent-chosen load; also reads extra files the SKILL.md points to |

`load_skill(name, path="SKILL.md")`:
- `name` must be in the enabled set, else an error listing the enabled names.
- `path` must be relative and stay inside the skill folder (no `..`, no absolute path); text files only; size cap
  (same truncation as `read`).
- Returns:
  ```
  [Skill: pptx · SKILL.md]
  Folder in the sandbox: /opt/simp/skills/pptx (read-only; run scripts by full path, work in /tmp, save to /work)
  <file text>
  ```
- Always returns the full text. No "already loaded" dedupe: it adds state and breaks after compaction.

### Core: session change

`AgentSession.prompt(text, images=(), skills=())` passes `skills` into the `before_agent_start` payload.
Nothing else in the loop changes.

### Core: compaction

`compaction.py` already collects `<read-files>` / `<modified-files>` from tool calls. Add `<loaded-skills>` the same
way (from `load_skill` calls and from explicit picks). After compaction the full SKILL.md text is gone and the summary
carries one short line per skill, e.g. `pptx (call load_skill("pptx") to read it again)`.

### Where skills are stored

| Kind | Stored in | Read by `load_skill` from | Seen in the sandbox at |
|---|---|---|---|
| Built-in | `apps/server/skills` (baked into the template) | server disk (`DirSkillSource`) | `/opt/simp/skills/<name>` |
| User-added (later) | user workspace `.skills/<name>/` (R2 / local) | workspace store (`workspace.read`) | `/work/.skills/<name>` (s3fs mount) |

The server builds `MultiSkillSource([builtin, user])`. A user skill with the same name overrides the built-in one.
Reading instructions never needs the sandbox; only running scripts does.

### Server

- Remove `skills.prompt_section` and the "Read /opt/simp/skills/..." text.
- Pass `Skills(source, enabled=lambda: all_names - store.disabled_skills_sync(user_id))` into `AgentSession(plugins=...)`
  only when the sandbox has skills (`has_skills`).
- Chat message protocol: add `skills: list[str]` to the user message (`protocol.py` → `protocol.gen.ts`).
- Keep `GET /api/skills` and enable/disable as they are.

### Web

- Chat box: a skill picker button (lists enabled skills from `GET /api/skills`) and `/` completion. A picked skill
  shows as a chip above the box (like attachments), and is sent as `skills: ["pptx"]`; `/pptx` text is stripped.
- Crafts › Skills tab: unchanged for now; "Add skill" (upload a folder/zip into `.skills/`) is a later step.

## Errors

- Explicit pick of an unknown or disabled skill: the server rejects the message before calling the LLM.
- `load_skill` on an unknown/disabled name or a bad path: tool error text; the model can recover.
- Source read failure (disk/R2): tool error text; no retry loop.

## Tests

- Core: catalog lists only enabled skills; `load_skill` happy path, unknown name, `..` path, absolute path,
  oversized file; explicit `skills=` adds SKILL.md before the first LLM call (faux provider);
  compaction summary contains `<loaded-skills>`.
- Server: `/api/skills` unchanged; chat message with `skills` reaches `session.prompt`; disabled skill rejected.
- Web: picker sends `skills`; chip remove works.

## Rollout

1. Core plugin + session param + compaction (one PR, with tests).
2. Server wiring + protocol + remove the old prompt section (same or next PR); fixes the production error.
3. Web picker.
4. Later: user-added skills (`.skills/` in the workspace, upload UI).

## Review (2026-11-23) and decisions

Approved and in scope:
1. SKILL.md calls scripts by relative path (`python scripts/recalc.py`), but the agent works in /work. `load_skill`
   rewrites `scripts/` to the absolute sandbox folder (`/opt/simp/skills/<name>/scripts/`).
5. Compaction must see explicit picks too. Both paths use the same header `[Skill: <name> · <path>]`; compaction
   lists loaded skills (`<loaded-skills>`) by finding that header in tool results and user messages.
8. Gaps: keep the `no_tools` gate (server.py:264); `before_agent_start` payload gains `skills`; `load_skill` needs
   no sandbox; disabling a skill mid-chat takes effect next turn.

Not now: hotfix in `SANDBOX_DIRS`, template drift, user-skill prompt-injection guards (with user skills), size caps /
dedupe, metrics for skipped skills. With no dedupe and no cap, `load_skill` returns the whole file (no truncation).
