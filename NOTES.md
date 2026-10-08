# simp-agent notes

Layers: `ai.py` (messages, `stream` dispatch by `model.api`) → `providers/` (anthropic, openai_completions) → `agent.py` (loop, `Agent`) → `tools.py` + `cli.py` (coding layer).

Not yet (present in pi, skipped here):
- parallel tool execution
- proxy transport
- compaction split-turn cut (pi isSplitTurn): we only cut at user/assistant messages, so one huge turn cannot be compacted
- more providers (anthropic-messages, openai-completions, openai-responses built in), TUI
- retry loop with backoff: core only classifies (`ai.is_retryable`, `ai.is_context_overflow`); the app decides

Hardening (done):
- `ai.transform_messages` runs before every LLM call: drops error/aborted assistant turns (kept in history for the UI) and adds a "No result provided" error result for every tool call without one.
- stop_reason `length`: tool calls are not run; error results are added.
- abort during streaming closes the provider stream (generator cancel -> SDK `async with` exit) and keeps partial text.
- subscribers may be async; a raising subscriber ends the run with an error message.
- `Agent.prompt` while streaming raises RuntimeError.

Queues + compaction (done):
- `Agent.steer()` / `follow_up()`; steering polled at loop start, after each tool batch, and after `prepare_next_turn`.
- History is append-only. Compaction appends `CompactionEntry(summary, first_kept_index)`; `build_view()` gives the LLM view.
- On context overflow, `Agent` compacts once and continues; a second overflow ends with the error.

Pluggability (done; "everything is a plugin"):
- `get_api_key(provider)` (sync/async) on Agent/LoopConfig, called before every LLM call (and compaction); key goes to `stream(..., api_key=)`. Strict: built-in providers NEVER read env; no key -> error "no API key for provider X" (error_kind fatal). The CLI passes its own env-reading `get_api_key` (`cli.env_api_key`).
- Tools get `execute(args, ctx)`; `ctx` = cancel, env, cwd, `on_update(text)` (async; emits `tool_execution_update`). `env.ExecutionEnv` Protocol; core ships only `LocalEnv`. `exec` has an extra optional `on_output` callback so bash can stream.
- `Agent(messages=...)` restores history; `Agent.continue_()` runs with no new message (last must be user/tool_result, else ValueError).
- `ai.register_provider(api, stream_fn)`; `ai.to_dict` / `ai.from_dict` for all messages + CompactionEntry. A CompactionEntry also fires `message_end`, so stores see it.
- Example plugin in cli.py: JSONL session store (`~/.simp-agent/sessions/<id>.jsonl`), `--resume <id> [task]` (no task = continue).

Recommended command for the human's gpt-6-luna server (key only via env OPENAI_API_KEY):
`uv run simp-agent --api openai-completions --base-url <url>/v1 --model openai/gpt-6-luna --context-window 922000 --max-tokens 32000 --max-tokens-field max_completion_tokens --reasoning-effort none "task"`

Reasoning / thinking (done, follows pi):
- `ThinkingContent(thinking, signature, redacted)`; `AssistantMessage` records api/provider/model; usage has `reasoning` (already inside `output`).
- `transform_messages(msgs, model)`: signed or redacted thinking replays only to the same provider+api+model (kept even if empty); other models get non-empty thinking as text, empty dropped.
- openai-responses: store=false, no previous_response_id; reasoning items replay from the encrypted item JSON in the signature. Tool call id = "call_id|item_id".
- anthropic: compat `reasoning_effort` -> adaptive thinking + effort; compat `thinking_budget` -> budget + interleaved beta.
- openai-completions: reasoning_content/reasoning/reasoning_text -> thinking (not replayed).
- Compaction summary skips thinking. CLI shows thinking dim; `--no-thinking` hides it.

gpt-6-luna with reasoning text (chat/completions gives no reasoning text, Responses does). settings.json profile:
`"luna": {"api": "openai-responses", "model": "openai/gpt-6-luna", "base_url": "<url>/v1", "context_window": 922000, "max_tokens": 32000, "compat": {"reasoning_effort": "low"}}`

Plugin sockets (stage 0):
- `SessionStore.append` may be async (awaited, order kept). AgentSession does not call `store.load()`; the app passes `messages=store.load()`.
- `AssistantMessage.error_kind` in {fatal, budget, policy} -> `is_retryable(error, kind)` is False; the session never retries.
- Tools are re-read every turn (`agent.tools` is a per-session list). When names change between turns, a user note
  `<system-reminder>Tools added: x; removed: y</system-reminder>` is appended to history (pi declareToolChanges).
- System prompt = ordered sections: `add_prompt_section(id, str | fn(ctx) -> str, order)`, rebuilt every turn,
  sorted by (order, first add) so it stays stable. Defaults: `coding` (0), `context_file` AGENTS.md (10); `system_prompt=` -> `base` (0).
- `append_entry(type, data)` -> `CustomEntry`: stored + replayed, never sent to the LLM, not in the compaction summary.
- Loop hooks: `after_tool_call(call, result, ctx) -> result | None` (also after a deny); `AgentTool.prepare_arguments(args)` before validation.
- Rules: subscribers must be fast (push to a queue). `abort()` before `prompt()` has no effect. One AgentSession per conversation.

Plugins: `AgentSession(plugins=[...], plugin_config={name: dict})`. A plugin is any object with `name` and optional
methods (sync or async). `setup(api, config)` + `session_start` run on the first prompt (or `await session.start()`).
Order = registration order. Errors in a hook -> `plugin_error` event, other plugins continue (except tool_call).

| hook | returns | chaining |
|---|---|---|
| `setup(api, config)` | - | once |
| `session_start()` / `session_shutdown()` | - | observe (`await session.shutdown()`) |
| `input(text)` | `{"handled": True}` / `{"text": new}` / None | handled stops the chain, prompt returns [] |
| `before_agent_start(ctx)` | `{"messages": [...]}` / None | messages sent with the prompt; may add prompt sections via api |
| `context(messages)` | messages / None | each gets the previous output (copies; history unchanged) |
| `tool_call(call)` | `{"block": reason}` / `{"args": new}` / None | first block wins; an exception = block (fail closed) |
| `tool_result(call, result)` | partial dict (`content`, `is_error`) / None | merged in order |
| `on_event(e)` | - | sees every session event |

PluginAPI: register_tool / unregister_tool, add_prompt_section / remove_prompt_section, append_entry (async),
send_message(text, "steer" | "follow_up" | "prompt"), set_model, abort, get_messages, env, cwd, emit(type, data) (async).
Examples in `plugins/`: `RedactSecrets` (tool_result + context), `PlanMode` (blocks write/edit/bash, prompt section, state in a custom entry).
