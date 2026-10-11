# Web protocol v1

Source of truth: `apps/server/src/simp_server/protocol.py` (Pydantic). Generated: `apps/web/src/protocol.gen.ts`
(`uv run python -m simp_server.gen_protocol`; the test `test_no_ts_drift` fails if it is stale).

## Transport
- `POST /api/hello {protocol_version}` -> `hello` (200) or `hello_error {error, supported}` (400). Unknown versions are rejected.
- `GET/POST /api/sessions` -> `SessionInfo` list / new session.
- `GET /api/sessions/{id}/events` - SSE. Resume with `Last-Event-ID` or `?after=<seq>`.
  On connect the server sends: missed DURABLE events (seq > after), then one `snapshot`, then the live stream.
- `POST /api/sessions/{id}/commands` - one command body; 422 if off-schema, 409 for approve without a matching pending call.

DURABLE events have `seq` (monotonic per session, = SSE `id`). LIVE events have no seq; after a reconnect the
`snapshot.in_flight` holds all text so far, and the next delta has `offset == len(in_flight text)`.

## Core event -> protocol event
| core (AgentSession) event | protocol event | notes |
|---|---|---|
| `message_end` (UserMessage) | `user_message` | durable |
| `message_update` / `start` | - | server sets a new `in_flight.msg_id` |
| `message_update` / `text_delta` | `text_delta {msg_id, offset, delta}` | live; server keeps offset per msg_id |
| `message_update` / `thinking_delta` | `thinking_delta {msg_id, offset, delta}` | live |
| `message_update` / `thinking_start/end`, `toolcall_*` | - | tool calls arrive in the final `assistant_message` |
| `message_end` (AssistantMessage) | `assistant_message {thinking, text, tool_calls, usage, stop_reason, error}` | durable; clears in_flight text |
| approve(call) callback (session `_before_tool_call`) | `approval_request {call_id, tool, args}` + `run_state waiting_approval` | durable |
| approval answered / abort | `approval_resolved {decision: allow,deny,always,aborted}` + `run_state running` | durable |
| `tool_execution_start` | - | |
| `tool_execution_update {call, text}` | `tool_output {call_id, offset, delta}` | live; core has no offset, server counts chars per call_id |
| `tool_execution_end` / `message_end` (ToolResultMessage) | `tool_result {call_id, tool, content, is_error}` | durable (sent once, from message_end) |
| `compaction_start` | - | |
| `compaction_end` (ok) | `compaction {summary, tokens_before, tokens_after}` | durable |
| `compaction_end` (error) | `notice {level: error}` | durable |
| `auto_retry_start` / `auto_retry_end` | `notice {level: warning / info}` | durable |
| `plugin_error`, plugin `emit()` | `notice` | durable |
| `message_end` (CustomEntry) | - | not shown in v1 |
| `agent_start` / `agent_end` | - | run_state comes from the server's run task, not these events |
| `turn_start` / `turn_end` | - | |

## Run state (server-owned)
The server sets `running` when it accepts a prompt (or starts a queued follow-up). When the run ends: `idle`, or `error`
if the last assistant stop_reason is error; after an abort: `idle` + notice "run aborted". If the run task itself fails
(store error, cancel), the state is forced to `error` + an error notice, so it never stays busy.
`idle -> running -> (waiting_approval <-> running) -> aborting -> idle | error`; `running -> idle | error`; `error -> running | idle`.
Abort: cancel the run, settle a pending approval as `aborted`, clear queued follow-ups, emit `run_state` + `notice`.

## Commands
`prompt{text}` (while busy = follow_up), `steer{text}`, `follow_up{text}`, `abort{}`, `approve{call_id, decision: allow|deny|always}`.

## Fake server
`uv run simp-server fake [--port 8765] [--delay 0.05]` - same API, replays a recorded run
(thinking, text, bash tool call, approval request, tool output, final text). No LLM, no Docker.

## Web UI (`apps/web`)
`uv run simp-server fake` then `cd apps/web && pnpm dev` (proxy `/api` -> `SIMP_SERVER`, default 127.0.0.1:8765). `pnpm test` = reducer tests.
The web also uses `GET /api/profiles -> [str]` (new-session picker) and `POST /api/sessions {profile}`; the fake server has both.
