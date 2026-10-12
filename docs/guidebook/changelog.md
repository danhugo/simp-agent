# Book changelog

Changes to this book, newest first. Each entry names the project commit the text was checked against.

## 2026-10-13
- v3 review fixes, Part 1 (ch 00–04, still checked at `2fc2776`): ch 01–04 each get a "Step by step: from naive to real" section and two exercises. Ch 02: standalone FakeProvider example first, loop use moved to a forward note (ch 05/07), says the fake skips `transform_messages`. Ch 01: `is_retryable` and `transform_messages` link to ch 04. Ch 03: shows the test `run()` helper. Hard words replaced ("on cue", "opaque", "in flight", "append-only"). Ran the new ch 02/04 examples.

## 2026-10-12
- v3: wrote [02 A fake provider](02-fake-provider.md) (checked at `2fc2776`; ran `test_no_tool_call_one_turn` and `test_tool_call_then_second_turn`, 2 passed, and the standalone example): stream function contract, `stream_fn` injection, naive fake, FakeProvider script/records/callable replies/start+done|error, use in tests. Glossary: provider, stream function, scripted reply.
- v3: wrote [01 Messages](01-messages.md) (checked at `2fc2776`; ran `test_from_dict_old_and_new` and `test_entry_roundtrip_and_old_format`, 2 passed): message and block types, CompactionEntry/CustomEntry, Tool/Context/Model, to_dict/from_dict. Test file corrected from skeleton (`test_core.py` has no round-trip test). Glossary: message, context, compaction entry, custom entry.
- v3: wrote [00 Overview](00-overview.md) (checked at `2fc2776`; `test_layers.py` run, 1 passed): what simp-agent is, layer map, layer test, apps, build path, capability table, fizzbuzz running example. Glossary: coding agent, layer, tool call.
- v3: rewritten as a build book. Old chapters 00–38 removed; new README outline and 28 chapter skeletons; glossary reset. Pinned at `2fc2776`.
- Re-read fixes B: footers ("Built on by") for 12, 21, 24 (24 now has the standard footer); removed the internal ROADMAP note from README; split long paragraphs in 11, 22, 23, 25, 26 into bullets (same meaning).
- Re-read fixes A: glossary adds MCP, operator, SSE, WebSocket, workspace; "operator" instead of "admin" in 24 and 36 (quoted messages and code names kept); first-use glossary links in 00, 01, 10, 20, 31, 34, 36, 37, 38; 10 notes that print mode ignores `-r`.
- Added [38 Decision records](38-decisions.md) (verified at `5c0f47c`, from ROADMAP, NOTES, Stage 2/3 plans; nothing run): small core + plugins, SSE + POST, SQLite, Docker sandbox, one machine, soft budgets. Linked from 32, 37, README (status now 30–38). Fixed stale 'not written yet' in 30. Glossary unchanged.
- Added [37 Testing and evals](37-testing.md) (verified at `85f9d25`; ran `uv run pytest -q` 190 passed/11 skipped no Docker, `make e2e` 16 passed, `simp-server fake`, `evals/run.py --help`; no real eval run): three levels, FakeProvider/FakeEnv, EnvConformance use, Fake LLM vs fake server, e2e setup, eval tasks and host-shell warning. Glossary: Fake LLM home links to 37. Linked from 33, 34, 35, 36, README.
- Added [36 Extending: server plugins](36-server-plugins.md) (verified at `82ecfa7`, from code; not run): the three slots and their Protocols, `DEFAULT_PLUGINS`, `load_plugin` and override order, LocalSandbox/DockerSandbox, `check_sandbox`, `EnvConformance`, the real Store method list, `StaticTokenAuth`. Glossary: plugin entry links to 36. Linked from 30, 32, 35, README.
- Added [35 Extending: tools and agent plugins](35-tools-plugins.md) (verified at `17cae3b`, from code; not run): tools list (`make_tools`), `PluginAPI`, all hooks with order and error rules (`tool_call` fails closed), `context` view, prompt sections, custom entries, `RedactSecrets` and `PlanMode` walk-through, loading; Stage 4 stubs marked planned. Glossary: added custom entry, hook, prompt section; plugin and tool Home now link to 35. Linked from 30, 31, 33, 34, README.
- Added [34 Extending: providers](34-providers.md) (verified at `53753a9`, from code and `test_register_provider`; echo example run, no real API called): provider contract (events, never raise, no env), error classes, 3 built-ins, profile `api`, `register_provider`. Glossary: provider home links to 34. Linked from 33 and README.
- Added [33 Developer tutorial](33-dev-tutorial.md) (verified at `c51fc79`; every code block run in the repo, then removed; server not started): `word_count` tool plugin, test with `FakeProvider`, register in `build_plugins`, turn on via profile `plugins`. Notes: CLI loads no plugins, no outside plugin loading, profile `plugins` vs `[plugins]` table. Glossary: plugin links to 33. Linked from 32 and README (outline line fixed: profile `plugins`, not `[plugins]`).
- Added [32 The server inside](32-server-inside.md) (verified at `b6f09f5`, from code; not run): Run, command queues, SSE + POST with seq/offset/snapshot (links protocol.md), SQLite tables, idle release, protocol.gen.ts + drift test. Recovery points to 25, settings to 21. Glossary: added durable event, live event, snapshot; run notes the `Run` class. Linked from 30, 31, README.
- Added [31 How one turn flows](31-turn-flow.md) (verified at `2c2cdc7`, from code; not stepped through): ai.stream, agent loop, `length` behaviour, retry/backoff, overflow recovery, compaction home. Glossary: added stop reason; 'Home: 31' entries now link. Linked from 13, 30, README.
- Added [30 Architecture](30-architecture.md) (verified at `57cabfc`, `test_layers.py` run and passing). Glossary: added layer. Linked from 27 and README.
- Fixed ch 25 after review: recovery happens when a session is first loaded, not at start; links and folder-name note. Replaced stale "not written yet" notes in 20, 22, 23, 24, 25.
- Added [27 Troubleshooting](27-troubleshooting.md) (verified at `273796c`, error texts from code; not all triggered by hand). Linked from 26 and README. Glossary unchanged.
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
- v3 ch 03 The stream parser written (parse in openai_completions.py: text, tool-call assembly, stop reasons, usage); glossary: Delta, Usage.
- v3 ch 04 Providers written (registry, lazy import, transform_messages and thinking replay, three providers, is_retryable / is_context_overflow); glossary: Agent loop, Provider registry, Context overflow.
- v3 ch 05 The agent loop written (AgentTool, ToolContext, run_tool, LoopConfig, agent_loop, _llm_turn; test_core.py); glossary: Turn, Agent tool, Tool context, Execution environment.
- v3 ch 06 Events and abort written (send/add/_emit_all events, cancel checks, _stream, partial kept on abort, Agent class; test_harden.py); glossary: Event, Abort.
- v3 ch 07 Steering written (get_steering / get_follow_up, inner and outer loop, three steering read points, queues survive abort, Agent.steer / follow_up / _take modes; test_queues_compaction.py); glossary: Steer, Follow-up, Queue mode; ch 19 link fixed to #steer.
- v3 ch 08 Hooks and approval written (before_tool_call / after_tool_call, deny as error result, _maybe_await, Agent hooks, AgentSession approval with always and abort race; tests in apps/cli/tests); glossary: Tool hook, Tool approval.
- v3 ch 09 Execution environment written (ExecutionEnv protocol, LocalEnv with to_thread IO, path safety via resolve, exec stream/cancel/timeout, process-group kill with run_kill, EnvConformance suite; test_env.py); glossary: Path safety, Process-group kill.
- v3 ch 10 Coding tools written (read with offset hint, write, edit exact-once/no-overlap/all-or-nothing, ls via ls -1Ap, grep/find with rg/fd and 127 fallback, bash with optional host cap and tail, truncate_head/tail; test_tools.py, test_bash.py); glossary: Truncation.
- v3 ch 11 The system prompt written (system_prompt, CONTEXT_FILES / load_context_file via env, prompt sections and _build_prompt, prompt function in _llm_turn; test_session.py context file test); glossary: System prompt, Context file, Prompt section.
- v3 ch 12 Evals written (evals/run.py: TOML tasks, run_task in temp dir with LocalEnv, event counting, 25-turn / 300 s limits, $PYTHON checks, results JSON; host-shell warning; test_run.py with FakeProvider); glossary: Eval, Eval task, Profile.
