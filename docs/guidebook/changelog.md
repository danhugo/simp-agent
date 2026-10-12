# Book changelog

Changes to this book, newest first. Each entry names the project commit the text was checked against.

## 2026-10-12
- Added [26 Security model and known gaps](26-security.md) (verified at `ad5a9bd`, from code; nothing attacked). Dated gaps list. Linked from 25 and README. Glossary unchanged.
- Added [25 Day-to-day ops](25-ops.md) (verified at `131851b`, from code and deploy files; launchd not run). Glossary unchanged.
- Added [24 Money and limits](24-money.md) (verified at `cbea25f`, from code; not run). Linked from 01, 11, 20, 22, 23, README. Glossary: added budget, kill switch, run. Fixed 'Built on by' links in 22 and 23.
- Added [23 Sandboxes](23-sandboxes.md) (verified at `194c41e`, from code; Docker not run). Linked from 21, 22, README.
- Added [22 Users and accounts](22-users.md) (verified at `5b091ec`, from code; not run). Glossary: access token now links to 22 and mentions rotate re-enables.
- Added [21 Configuration reference](21-configuration.md) (verified at `2c311ce`, from code). Linked from README.
- Added [20 Operator tutorial](20-operator-tutorial.md) (verified at `a8615b1`; Docker steps not run, no Docker on the test machine). Linked 20 from 01 and README.
- Added [13 Working well with the agent](13-working-well.md) (verified at `a8615b1`): AGENTS.md/CLAUDE.md, writing requests, long sessions and compaction; tips tagged CLI/web/both. Glossary: added context file, context window.
- Added [12 CLI vs web feature table](12-cli-vs-web.md) (verified at `6f55ff0`); ch 10 and 11 now link to it instead of comparing.
- Added [11 The web UI](11-web.md) (verified at `9fdc61d`). Glossary: added plan mode. Linked 11 from 10 and README.
- Added [10 The CLI](10-cli.md) (verified at `8efbd9c`). Glossary: added follow-up, steer, tool approval; linked 10 from 00, 01, README.
- Added [01 Quick start](01-quick-start.md) (verified at `d3d03f6`): CLI path, web path,
  no-key path with `--fake-llm`. Glossary: added access token, fake LLM, print mode, REPL.
  Linked 01 from 00 and the README outline.
- Added [00 Introduction and core ideas](00-introduction.md) (verified at `d74b7ee`).
- Seeded the [glossary](glossary.md): agent loop, compaction, execution environment, history,
  message, plugin, profile, provider, sandbox, session, tool, turn.
- Review fixes: Stage 5 / replicas wording, stale README status, outline line 01 (no CLI fake mode), glossary term system prompt.
- Review round 2: README status line now says "Written: 00, 01"; wrapped the Profile glossary line.
- Note: links to chapters not yet written are plain text; they become links when those chapters exist.
