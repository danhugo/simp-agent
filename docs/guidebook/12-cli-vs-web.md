# 12 CLI vs web feature table

**For:** Users who want to know which app has which feature.
**You need first:** [10 The CLI](10-cli.md) and [11 The web UI](11-web.md).
**You will learn:** one table of every user feature, CLI and web side by side. Each cell links to the section that explains it.
**Code covered:** `apps/cli/src/simp_cli/` (no plan mode, titles, notifications, spend or upload there); `apps/server/src/simp_server/server.py`; `apps/web/src/`.
Verified at commit `6f55ff0`.

This is the only place where the two apps are compared. Chapters 10 and 11 describe one app each and link here.

## 1. The table

"—" means the app does not have the feature.

| Feature | CLI | Web |
|---|---|---|
| Chat | [REPL](10-cli.md#3-the-repl) and [print mode](10-cli.md#2-print-mode) (one task) | [Chat box](11-web.md#3-chat) |
| [Steer](glossary.md#steer) / [follow-up](glossary.md#follow-up) while running | plain text / `>>` text ([REPL](10-cli.md#3-the-repl)) | default / **Queue as follow-up** ([Chat](11-web.md#3-chat)) |
| Stop a run | Ctrl-C ([REPL](10-cli.md#3-the-repl)) | **Stop** or Esc ([Chat](11-web.md#3-chat)) |
| [Tool approval](glossary.md#tool-approval) | `y` / `a` / no ([section 5](10-cli.md#5-tool-approval-and---yes)) | **Allow** / **Always** / **Deny** cards ([Chat](11-web.md#3-chat)) |
| Approve everything | `--yes` ([section 5](10-cli.md#5-tool-approval-and---yes)) | — (no such switch) |
| Compact ([compaction](glossary.md#compaction)) | `/compact` ([Commands](10-cli.md#commands)) | **Compact** button ([section 5](11-web.md#5-compact)) |
| [Plan mode](glossary.md#plan-mode) | — | **Plan** button ([section 4](11-web.md#4-plan-mode)) |
| Continue after an error or restart | — (you can send a new message) | **Continue** button ([section 6](11-web.md#6-continue-after-an-interruption)) |
| Resume an old session | `-c`, `--resume ID`, `-r` (`-r` works only in the REPL; print mode ignores it) ([section 6](10-cli.md#6-sessions-where-they-are-saved)) | click it in the list ([section 2](11-web.md#2-sessions)) |
| New session | `/new` ([Commands](10-cli.md#commands)) | **New session** button ([section 2](11-web.md#2-sessions)) |
| Choose a model | `--model`, `--api`, `--base-url` ([section 4](10-cli.md#4-settings-and-profiles)) | only pick a profile ([section 2](11-web.md#2-sessions)) |
| Status and usage | bottom bar: model, `~N tokens`, run state ([REPL](10-cli.md#3-the-repl)) | state badge per session ([section 2](11-web.md#2-sessions)) |
| List sessions | `/sessions` (this folder only) ([Commands](10-cli.md#commands)) | left bar ([section 2](11-web.md#2-sessions)) |
| Delete a session | delete the file ([section 6](10-cli.md#6-sessions-where-they-are-saved)) | `×`, then **Delete?** ([section 2](11-web.md#2-sessions)) |
| Session titles | — (you see the id) | made by the model ([section 2](11-web.md#2-sessions)) |
| Show all messages | `/history` ([Commands](10-cli.md#commands)) | scroll the chat ([Chat](11-web.md#3-chat)) |
| Files of the session | your own folder, no panel | **Files** panel: browse, download, upload ([section 7](11-web.md#7-files)) |
| Notifications | — | **Notify** ([section 8](11-web.md#8-notifications)) |
| Spend display and limits | — | `$spent / $limit` ([section 9](11-web.md#9-spend-display)) |
| [Profiles](glossary.md#profile) | `~/.simp-agent/settings.json`, `--profile` ([section 4](10-cli.md#4-settings-and-profiles)) | pick one for a new session, if the server has several ([section 2](11-web.md#2-sessions)) |
| Sign-in | — (one user, your own machine) | token, password or signup code ([section 1](11-web.md#1-sign-in)) |
| [Fake LLM](glossary.md#fake-llm) (no key) | — | yes, see [01](01-quick-start.md#4-path-b--chat-in-the-browser) and [section 11](11-web.md#11-try-it-with-no-key) |
| Themes | terminal colours | dark / light ([section 10](11-web.md#10-themes)) |

## 2. Where sessions live

The two apps do not share sessions. The CLI writes files under `~/.simp-agent/sessions/`; the web uses the server's database. A session made in one app does not show in the other.

## 3. Why the difference

The CLI is one user on their own machine: tools run in your real folder, so it asks you before each risky tool and has no sandbox, login or budget. The web talks to a server that has many users, a [sandbox](glossary.md#sandbox), budgets and saved state, so it has the features that need them (spend, Continue, titles, Files, notifications).

Which to choose: quick work in a folder you trust, use the CLI. Shared, long or safer work, use the web.

---

**Back:** [11 The web UI](11-web.md).
**Next:** [13 Working well with the agent](13-working-well.md).
**Builds on:** [10 The CLI](10-cli.md), [11 The web UI](11-web.md).
