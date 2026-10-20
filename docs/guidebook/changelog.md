# Book changelog

Changes to this book, newest first. Each entry names the project commit the text was checked against.

## 2026-10-20
- ch01 "From naive to real" rewritten: one step per problem from "Where it breaks" (table, late import, never raise), tiny examples, no code names or chapter jumps inside steps; "Real code" labelled fix 1/2/3, repeated "Two things here" removed. ch03 problem bullets reordered to match steps; ch04 adds the missing "replies cannot react" problem and drops code names from steps. (checked at `1d8b39d`)
- ch01: rewrote "Thinking: who can read it back" with a scenario; defined `same`, redacted, signature, plain text; split the answer-text branch; fixed the table (signed thinking becomes plain text for another model, not dropped).
- ch01-04 polish (coherence review): ch03 links object fields to ref-objects; `LoopConfig.stream_fn` fake note moved from ch01 to ch04 "Why a fake"; ch01 naive Pick drops orphan-call bullet, "errors as strings" note moved into Clean, repeated Clean bullets removed; JSON round-trip / CustomEntry links to ref-objects in glossary, ch13, ch22. (checked at `d06ae9d`)
- ch01 re-ordered by wiki block-flow-chapters-v2: Problem → IN Model + Context (short) → 1 Pick → OUT stream-function shape → 2 Clean (opens messages only as Clean needs) → Test. Full dataclass fields, `to_dict`/`from_dict` JSON, `CompactionEntry`/`CustomEntry` and round-trip tests moved to new [ref-objects](ref-objects.md). Fixed recap thinking rule (signed thinking is dropped for other models). ch02/03 `compat` now linked to ref-objects; ch02 test note no longer explains ch04 classifiers. Glossary homes and anchors updated. (checked at `c200786`)
- Part 1 re-cut by block flow (wiki block-flow-chapters): 01-messages, 02-fake-provider, 03-stream-parser, 04-providers became [01 Pick + Clean](01-pick-clean.md) (messages, Tool/Context/Model, stream-function shape, registry, `transform_messages`), [02 Translate + Send](02-translate-send.md) (vendor request side, `stream` wrapper), [03 Parse](03-parse.md) (all three parsers), [04 Label + test the pipeline](04-label-test.md) (`ai.stream`, error classification, `FakeProvider`). No facts removed; joins rewritten. All links, README, part-1-ai table and SVG chapter tags, glossary homes updated. (checked at `223ddb0`)
- Part 1 block flow: ch 01–04 "Where we are" now show the Pick→Clean→Translate→Send→Parse→Label strip with this chapter's blocks marked, plus a "Builds · IN · OUT" line and an "OUT of this chapter →" bridge at the end. ch 04 Real design reordered to flow order (Model, 1 Pick, 2 Clean + Thinking, 3/4 providers, 6 Label, error classification as an extra); anchors fixed. ch 03 notes Parse in the other two providers. (checked at `04e1df1`)

## 2026-10-19
- Big picture review fixes: Part 3 project file is its own prompt section (diagram + SVG), block 3 runs before every model call; FakeLLM line in Part 5 SVG; "Next" links go to the next Part page.
- Added [Part 3 big picture](part-3-coding.md) (diagram img/part-3-coding.svg, block table, objects, worked example). Linked from README and "Where we are" in 09-12. (checked at `ca8d944`)
- Added [Part 4 big picture](part-4-session.md) (diagram img/part-4-session.svg, block table, objects, worked example). Linked from README and "Where we are" in 13-18. (checked at `2fc2776`)
- Added [Part 1 big picture](part-1-ai.md) (diagram img/part-1-ai.svg, block table, objects, worked example). Linked from README and "Where we are" in 01-04. Glossary: added Model, Tool, AssistantMessage, Stream event.
- Added [Part 2 big picture](part-2-agent.md) (diagram img/part-2-agent.svg, block table, objects, worked example). Linked from README and "Where we are" in 05-08. Glossary: added LoopConfig, Agent (class).
- Part 1 big picture: picture now splits Translate and Send, numbers match the table (Label = 6), Agent-decides box is grey and points to Part 2; paths fixed to `ai/providers/*.py`; Clean row notes it skips compaction/custom entries. README explains big-picture pages.

## 2026-10-15
- ch 19–21: python blocks that explain logic are now plain-English pseudo-code, each with a "Real code:" link (file + function). Shell commands, tests and the ch 21 naive version and Steps 1–4 (used by Exercise 1) stay real code. (checked at `2fc2776`)
- ch 10–13: code that explains logic is now easy pseudo-code (`text` blocks) with a "Real code:" link to the file and function; naive versions, step excerpts, tests, TOML, shell and CLI usage stay real code. (checked at `0ca2c62`)
- ch 00–03: logic code blocks turned into plain-English pseudo-code, each with a "Real code:" link (file + function); data shapes, wire formats, tests and shell commands kept. (checked at `0ca2c62`)
- ch 03: tool-call chunk example now uses the real Chat Completions shape (`type`, `function`, own `finish_reason` chunk, `choices: []` + usage). ch 04: real Responses and Anthropic SSE examples for the same tool call, each event mapped to its code line. (checked at `8c3b8b5`)

## 2026-10-13
- re-read fixes D: glossary code-name headings in backticks (anchors unchanged); commit hashes added to re-read fixes entries.
- re-read fixes C: ch 00–03 "Code in this chapter" pins moved to `2fc2776` (from `68e4ce1`, `e097e49`, `a55fe8d`); shown code checked, no snippet changed. (`bd0e7b9`)
- re-read fixes B: glossary merges CompactionEntry and Overflow recovery into pointers; new entries In-flight buffer, Gap / dup delta, Bearer token, Monotonic clock (linked from 09, 10, 20, 23, 25); all glossary headings start with a capital; ch 19–27 Builds on / Next labels use the "20 The server run" form; ch 21 links Offset; ch 26 "any mode not in the server list". (`1d3d508`)
- re-read fixes: ch 26 code list adds `accounts.spec.ts` and `admin.spec.ts`; ch 20 seq and Reconnect cut to one line + link to ch 21; ch 22 "Durable events" links to Step 4; ch 25 "Why this way" keeps only the tradeoff. (`ee6ade4`)
- ch 20 live events: `ToolOutput` is saved in `ToolResult` (commit `c4ea9d0`); ch 20 review fixes: deltas note, changelog, snapshot link (commit `096a193`).
- one-line "Code in this chapter" form in ch 02, 14–18 and README (commit `8357dbe`).
- ch 21 + glossary SSE: browser reads SSE with a fetch-based reader, not `EventSource` (lines 150, 154, 197); links to ch 25 "fetch-based SSE". (`2e7a21c`)
- ch 25/26 dedup: the e2e reload test (serve.sh, app.spec.ts, make e2e) now lives only in ch 26 "End-to-end tests with Playwright"; ch 25 "Test" covers only `state.test.ts` and links to 26; ch 25 Step 3 and "fetch-based SSE" link to ch 21 "Replay" for the server side.
- ch 20–22: removed repeated seq/durable/live/snapshot text; ch 20 and 22 keep a short summary and link to ch 21 (commit `82f7715`).
- ch 12 + README: "each later Part adds a case" reworded; the book has only 4 eval tasks (3 code edits, 1 read-and-answer), adding more is optional (commits `4694e08`, `423175a`).
- v3 ch 14–27 review (checked at `2fc2776`): "Where we are" heading and "Code in this chapter" added to ch 22, 23, 25; glossary: Jitter, Sandbox slot, Static token, Per-device token, Allow list, with links from first use (also fail closed, view, incremental summary); old v2 links to removed files turned into plain text.
- v3 ch 27 Choices, limits and extending finished: symbols checked at `2fc2776`; added "Where we are" and "Code in this chapter"; glossary: pi, Protocol (Python), Ponytail comment (Plugin, PluginAPI already in glossary); removed "Terms to add" list.
- v3 ch 26 System tests and deploy finished: symbols checked at `2fc2776`; added "Where we are" and "Code in this chapter"; glossary: End-to-end test, Playwright, Deterministic, Online backup, launchd (WAL mode links to WAL); removed "Terms to add" list.
- v3 ch 24 Docker sandbox finished: symbols checked at `2fc2776`; added "Where we are" and "Code in this chapter"; glossary: Sandbox, Container, Hardening, Bind mount (process group links to Process-group kill); removed "Terms to add" list; removed duplicate ch 23 line.
- v3 ch 25 Web client finished: symbols checked at `2fc2776`; glossary: Reducer, Offset (SSE, Durable event, Snapshot already in glossary); removed "Terms to add" list.
- v3 ch 23 Limits finished: symbols checked at `2fc2776`; diagram matches ch 22; fizzbuzz example; glossary: Budget guard, Run budget, Daily budget, Kill switch, Eviction, Idle release; removed "Terms to add" list.
- v3 review fixes, ch 13–18 (checked at `2fc2776`): ch 18 naive profiles use `id` (old code raised `TypeError`); ch 16 Exercise 2 uses `Model()` and checks no `compaction_start`, Step 2/3 wording; ch 17 overflow guard called a safety guard; ch 14 Step 7 and prompt-section repeat cut (links ch 13), "User denied:" explained; ch 15 problem 5 dropped; transform_messages links go to ch 04; ch 13 Step 7 (prompt sections, start()); "Where we are" in ch 15, 17 and "Code in this chapter" in ch 13–18; README template lists both parts.
- v3 ch 22 Store and auth finished: symbols checked at `2fc2776`; glossary: Store, Auth, Token (auth), WAL, scrypt, recover; removed "Terms to add" list.
- v3 ch 19–21: added "## Where we are" heading over the diagram and the "Code in this chapter" list (paths checked at `2fc2776`), like ch 13.
- v3 ch 21 Transport finished: symbols checked at `2fc2776`; 5 cited server tests passed; glossary: SSE, seq, Last-Event-ID, Heartbeat, Future; removed "Terms to add" list (Durable event, Live event, Snapshot already in glossary).
- v3 ch 20 Server protocol and Run finished: symbols checked at `2fc2776`; glossary: Protocol, Run, Run state, Discriminator, Durable event, Live event, Snapshot, JSON Schema; removed "Terms to add" list; "fails loudly" replaced.
- v3 ch 19 CLI finished: symbols checked at `2fc2776`; glossary: Print mode, REPL, Component, ANSI codes; removed "Terms to add" list (Steer already in glossary).
- v3 review fixes, Parts 2–3 (ch 05–12, checked at `2fc2776`): each chapter gets a "Step by step: from naive to real" section with real code excerpts; ch 05–10 get a "Why this way" box. Changelog: added the missing "written" lines for ch 14–18 and put all lines newest first.
- v3 review fixes, Part 4 (ch 13–18, checked at `2fc2776`; 7 cited test commands, 27 passed): hard words replaced in ch 13, 15, 18 ("baked in", "jittered", "fails loudly", "opaque"). Ch 14: `tool_result` also runs after a blocked or denied call.
- v3 polish ch 18: moved "Terms to add" list into glossary.md.
- v3 polish ch 17: moved "Terms to add" list into glossary.md.
- v3 polish ch 16: moved "Terms to add" list into glossary.md.
- v3 polish ch 15: moved "Terms to add" list into glossary.md.
- v3 polish ch 14: moved "Terms to add" list into glossary.md.
- Ch 13: now owns prompt sections (add_prompt_section, _build_prompt, start()) after the ch 11 cut.
- ch 11: cut the session detail about prompt sections down to a summary plus a link to ch 13.
- v3 ch 13 Sessions written (SessionStore append/load, AgentSession owns Agent via hooks, save on message_end, resume with messages=store.load(), prompt/continue_, append_entry/CustomEntry, CLI JsonlStore; test_session.py store test); glossary: Session, AgentSession, SessionStore, JSONL, _maybe_await, Append-only history.
- Review fixes ch 09-12: added Exercises sections; plain-language fixes; Look ahead box in 11.
- v3 ch 12 Evals written (evals/run.py: TOML tasks, run_task in temp dir with LocalEnv, event counting, 25-turn / 300 s limits, $PYTHON checks, results JSON; host-shell warning; test_run.py with FakeProvider); glossary: Eval, Eval task, Profile.
- v3 ch 11 The system prompt written (system_prompt, CONTEXT_FILES / load_context_file via env, prompt sections and _build_prompt, prompt function in _llm_turn; test_session.py context file test); glossary: System prompt, Context file, Prompt section.
- v3 ch 10 Coding tools written (read with offset hint, write, edit exact-once/no-overlap/all-or-nothing, ls via ls -1Ap, grep/find with rg/fd and 127 fallback, bash with optional host cap and tail, truncate_head/tail; test_tools.py, test_bash.py); glossary: Truncation.
- v3 ch 09 Execution environment written (ExecutionEnv protocol, LocalEnv with to_thread IO, path safety via resolve, exec stream/cancel/timeout, process-group kill with run_kill, EnvConformance suite; test_env.py); glossary: Path safety, Process-group kill.
- v3 ch 08 Hooks and approval written (before_tool_call / after_tool_call, deny as error result, _maybe_await, Agent hooks, AgentSession approval with always and abort race; tests in apps/cli/tests); glossary: Tool hook, Tool approval.
- v3 ch 07 Steering written (get_steering / get_follow_up, inner and outer loop, three steering read points, queues survive abort, Agent.steer / follow_up / _take modes; test_queues_compaction.py); glossary: Steer, Follow-up, Queue mode; ch 19 link fixed to #steer.
- v3 ch 06 Events and abort written (send/add/_emit_all events, cancel checks, _stream, partial kept on abort, Agent class; test_harden.py); glossary: Event, Abort.
- v3 review fixes, Part 1 (ch 00–04, still checked at `2fc2776`): ch 01–04 each get a "Step by step: from naive to real" section and two exercises. Ch 02: standalone FakeProvider example first, loop use moved to a forward note (ch 05/07), says the fake skips `transform_messages`. Ch 01: `is_retryable` and `transform_messages` link to ch 04. Ch 03: shows the test `run()` helper. Hard words replaced ("on cue", "opaque", "in flight", "append-only"). Ran the new ch 02/04 examples.
- v3 ch 05 The agent loop written (AgentTool, ToolContext, run_tool, LoopConfig, agent_loop, _llm_turn; test_core.py); glossary: Turn, Agent tool, Tool context, Execution environment.

## 2026-10-12
- v3: wrote [18 Profiles and built-in plugins](18-profiles-plugins.md) (checked at `2fc2776`; `test_profile.py`, `test_sockets.py -k "redact or plan_mode"`): profiles and `build_model`, `build_plugins`, RedactSecrets, PlanMode.
- v3: wrote [17 Context overflow](17-overflow.md) (checked at `2fc2776`; `test_queues_compaction.py -k overflow`): one detector for all providers, kept out of retry, compact and retry once, stop if compaction fails.
- v3: wrote [16 Compaction](16-compaction.md) (checked at `2fc2776`; `test_compaction_serialize.py`, `test_queues_compaction.py`): CompactionEntry and `build_view`, `estimate_tokens`/`should_compact`, `find_cut`, `serialize_conversation`, incremental `summarize`, file tracking, `compact` in the session.
- v3: wrote [15 Retry](15-retry.md) (checked at `2fc2776`; `test_session.py -k "retry_429 or abort_during_backoff"`): retryable errors, the retry loop in `_run`, abort during backoff, order of checks.
- v3: wrote [14 Plugins](14-plugins.md) (checked at `2fc2776`; `test_sockets.py::test_plugin_context_chain_and_error_isolated`): plugin as any object with optional hook methods, the hook list, PluginAPI, prompt sections, plugin events.
- v3 ch 04 Providers written (registry, lazy import, transform_messages and thinking replay, three providers, is_retryable / is_context_overflow); glossary: Agent loop, Provider registry, Context overflow.
- v3 ch 03 The stream parser written (parse in openai_completions.py: text, tool-call assembly, stop reasons, usage); glossary: Delta, Usage.
- v3: wrote [02 A fake provider](02-fake-provider.md) (checked at `2fc2776`; ran `test_no_tool_call_one_turn` and `test_tool_call_then_second_turn`, 2 passed, and the standalone example): stream function contract, `stream_fn` injection, naive fake, FakeProvider script/records/callable replies/start+done|error, use in tests. Glossary: provider, stream function, scripted reply.
- v3: wrote [01 Messages](01-messages.md) (checked at `2fc2776`; ran `test_from_dict_old_and_new` and `test_entry_roundtrip_and_old_format`, 2 passed): message and block types, CompactionEntry/CustomEntry, Tool/Context/Model, to_dict/from_dict. Test file corrected from skeleton (`test_core.py` has no round-trip test). Glossary: message, context, compaction entry, custom entry.
- v3: wrote [00 Overview](00-overview.md) (checked at `2fc2776`; `test_layers.py` run, 1 passed): what simp-agent is, layer map, layer test, apps, build path, capability table, fizzbuzz running example. Glossary: coding agent, layer, tool call.
- v3: rewritten as a build book. Old chapters 00–38 removed; new README outline and 28 chapter skeletons; glossary reset. Pinned at `2fc2776`.
- Re-read fixes B: footers ("Built on by") for 12, 21, 24 (24 now has the standard footer); removed the internal ROADMAP note from README; split long paragraphs in 11, 22, 23, 25, 26 into bullets (same meaning).
- Re-read fixes A: glossary adds MCP, operator, SSE, WebSocket, workspace; "operator" instead of "admin" in 24 and 36 (quoted messages and code names kept); first-use glossary links in 00, 01, 10, 20, 31, 34, 36, 37, 38; 10 notes that print mode ignores `-r`.
- Added `38 Decision records` (verified at `5c0f47c`, from ROADMAP, NOTES, Stage 2/3 plans; nothing run): small core + plugins, SSE + POST, SQLite, Docker sandbox, one machine, soft budgets. Linked from 32, 37, README (status now 30–38). Fixed stale 'not written yet' in 30. Glossary unchanged.
- Added `37 Testing and evals` (verified at `85f9d25`; ran `uv run pytest -q` 190 passed/11 skipped no Docker, `make e2e` 16 passed, `simp-server fake`, `evals/run.py --help`; no real eval run): three levels, FakeProvider/FakeEnv, EnvConformance use, Fake LLM vs fake server, e2e setup, eval tasks and host-shell warning. Glossary: Fake LLM home links to 37. Linked from 33, 34, 35, 36, README.
- Added `36 Extending: server plugins` (verified at `82ecfa7`, from code; not run): the three slots and their Protocols, `DEFAULT_PLUGINS`, `load_plugin` and override order, LocalSandbox/DockerSandbox, `check_sandbox`, `EnvConformance`, the real Store method list, `StaticTokenAuth`. Glossary: plugin entry links to 36. Linked from 30, 32, 35, README.
- Added `35 Extending: tools and agent plugins` (verified at `17cae3b`, from code; not run): tools list (`make_tools`), `PluginAPI`, all hooks with order and error rules (`tool_call` fails closed), `context` view, prompt sections, custom entries, `RedactSecrets` and `PlanMode` walk-through, loading; Stage 4 stubs marked planned. Glossary: added custom entry, hook, prompt section; plugin and tool Home now link to 35. Linked from 30, 31, 33, 34, README.
- Added `34 Extending: providers` (verified at `53753a9`, from code and `test_register_provider`; echo example run, no real API called): provider contract (events, never raise, no env), error classes, 3 built-ins, profile `api`, `register_provider`. Glossary: provider home links to 34. Linked from 33 and README.
- Added `33 Developer tutorial` (verified at `c51fc79`; every code block run in the repo, then removed; server not started): `word_count` tool plugin, test with `FakeProvider`, register in `build_plugins`, turn on via profile `plugins`. Notes: CLI loads no plugins, no outside plugin loading, profile `plugins` vs `[plugins]` table. Glossary: plugin links to 33. Linked from 32 and README (outline line fixed: profile `plugins`, not `[plugins]`).
- Added `32 The server inside` (verified at `b6f09f5`, from code; not run): Run, command queues, SSE + POST with seq/offset/snapshot (links protocol.md), SQLite tables, idle release, protocol.gen.ts + drift test. Recovery points to 25, settings to 21. Glossary: added durable event, live event, snapshot; run notes the `Run` class. Linked from 30, 31, README.
- Added `31 How one turn flows` (verified at `2c2cdc7`, from code; not stepped through): ai.stream, agent loop, `length` behaviour, retry/backoff, overflow recovery, compaction home. Glossary: added stop reason; 'Home: 31' entries now link. Linked from 13, 30, README.
- Added `30 Architecture` (verified at `57cabfc`, `test_layers.py` run and passing). Glossary: added layer. Linked from 27 and README.
- Fixed ch 25 after review: recovery happens when a session is first loaded, not at start; links and folder-name note. Replaced stale "not written yet" notes in 20, 22, 23, 24, 25.
- Added `27 Troubleshooting` (verified at `273796c`, error texts from code; not all triggered by hand). Linked from 26 and README. Glossary unchanged.
- Added `26 Security model and known gaps` (verified at `ad5a9bd`, from code; nothing attacked). Dated gaps list. Linked from 25 and README. Glossary unchanged.
- Added `25 Day-to-day ops` (verified at `131851b`, from code and deploy files; launchd not run). Glossary unchanged.
- Added `24 Money and limits` (verified at `cbea25f`, from code; not run). Linked from 01, 11, 20, 22, 23, README. Glossary: added budget, kill switch, run. Fixed 'Built on by' links in 22 and 23.
- Added `23 Sandboxes` (verified at `194c41e`, from code; Docker not run). Linked from 21, 22, README.
- Added `22 Users and accounts` (verified at `5b091ec`, from code; not run). Glossary: access token now links to 22 and mentions rotate re-enables.
- Added `21 Configuration reference` (verified at `2c311ce`, from code). Linked from README.
- Added `20 Operator tutorial` (verified at `a8615b1`; Docker steps not run, no Docker on the test machine). Linked 20 from 01 and README.
- Added `13 Working well with the agent` (verified at `a8615b1`): AGENTS.md/CLAUDE.md, writing requests, long sessions and compaction; tips tagged CLI/web/both. Glossary: added context file, context window.
- Added `12 CLI vs web feature table` (verified at `6f55ff0`); ch 10 and 11 now link to it instead of comparing.
- Added `11 The web UI` (verified at `9fdc61d`). Glossary: added plan mode. Linked 11 from 10 and README.
- Added `10 The CLI` (verified at `8efbd9c`). Glossary: added follow-up, steer, tool approval; linked 10 from 00, 01, README.
- Added `01 Quick start` (verified at `d3d03f6`): CLI path, web path,
- Added `00 Introduction and core ideas` (verified at `d74b7ee`).
- Seeded the [glossary](glossary.md): agent loop, compaction, execution environment, history,
- Review fixes: Stage 5 / replicas wording, stale README status, outline line 01 (no CLI fake mode), glossary term system prompt.
- Review round 2: README status line now says "Written: 00, 01"; wrapped the Profile glossary line.
- Note: links to chapters not yet written are plain text; they become links when those chapters exist.
- Pseudo-code: logic blocks in ch04-09 are now plain-English pseudo-code with a "Real code:" link; tests and real signatures stay as Python.
- Pseudo-code: ch14-18 logic blocks now easy pseudo-code with a 'Real code' link; test/usage code kept.
- Pseudo-code: ch22-24, 26, 27 logic blocks now easy pseudo-code with a 'Real code' link; tests, schemas, interfaces and extend examples kept.
- Pseudo-code fix: ch01-03, ch08 logic blocks now text pseudo + Real code lines.
- Part 5 big picture page: part-5-system.md + img/part-5-system.svg (10 blocks, ch19-26); linked from README and ch19-26.
