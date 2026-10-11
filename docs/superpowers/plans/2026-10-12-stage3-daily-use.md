# Stage 3 (daily use on one machine) Implementation Plan

> **For agentic workers:** each task below is done by one subagent in its own worktree/branch, TDD (failing test first), small local edits in shared files, commit at the end. Read "Global Constraints" and "Ownership" before starting.

**Goal:** Make the self-hosted server pleasant for daily use: fix Stage 2 leftovers, stop leaking containers/RAM, user accounts with sign-up and password login, LLM-named sessions, web parity with the CLI (compact, plan mode), Continue after an interruption, browser notifications, and a small eval script.

**Scope (owner's pick):** roadmap items 0, 1, 5, 6, 9 + accounts/login + LLM session titles. Not in scope: repo upload/zip, approval rules, web fetch, admin page, network for the sandbox, BYOK, replicas.

**Tech:** Python 3.12, FastAPI, aiosqlite, pytest; React + Vite + vitest; Playwright e2e (`make e2e`, home `/tmp/simp-e2e`).

## Global Constraints

- Tests: `uv run pytest -q` must pass (Docker is running on this machine: the docker tests run too). Web: `cd apps/web && pnpm test && pnpm build`. Run `make e2e` only in the final wave (one at a time: it uses fixed ports and `/tmp/simp-e2e`).
- Never touch `~/.simp-server` (the owner's real data). Tests use `tmp_path`; manual checks use a temp `SIMP_SERVER_HOME`.
- Protocol changes: edit `apps/server/src/simp_server/protocol.py`, then regenerate TS with `uv run python -m simp_server.gen_protocol` (writes `apps/web/src/protocol.gen.ts`); commit both.
- Commit message `Stage 3: <what>`, ending with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Match the terse style of the surrounding code; few comments; no new dependencies unless stated.

## Ownership (to keep merges mechanical)

| Task | Owns | May touch lightly |
|---|---|---|
| A runtime | `Run.start/_turn` budget start, `SessionManager` (get/evict/cap), `LocalSandbox`, `sandboxes/docker.py` | README |
| B accounts | `store.py` users/tokens, `StaticTokenAuth`, `/api/signup` `/api/login` `/api/logout`, `main()` seed/users, `App.tsx` Login | README, e2e |
| C commands | `protocol.py`, `Run.command`, `Run.__init__` plugins list, titles (`store.set_title`), snapshot fields | README |
| E evals | new `evals/` package dir | README |
| D web (wave 2) | `Chat.tsx`, `App.tsx` sidebar/Main, `state.ts`, notifications | e2e |

---

### Task A: Stage 2 leftovers + container/RAM lifecycle (items 0 and 1)

1. **Run budget spans follow-ups.** Today `Run.start` resets `run_start`, and `_turn` calls `start()` for a queued follow-up, so each follow-up gets a fresh `run_usd`. Add `start(text, fresh=True)`; `_turn` calls `start(..., fresh=False)` which keeps `run_start`. Test: `run_usd = 1.5`, price $1/call, prompt + 2 queued follow-ups (each one LLM call) → third call refused.
2. **One workspace dir.** `LocalSandbox` uses `<data_dir>/workspaces/<sid>` (same as DockerSandbox). On `open`, if `<data_dir>/sandboxes/<sid>` exists and `workspaces/<sid>` does not, move it (old sessions keep their files). Test both.
3. **Idle eviction.** Settings `idle_minutes` (default 15). `SessionManager` keeps `last_used` per run (updated by `get`, commands, and run end). A background task (started in lifespan, every 60s; interval injectable for tests) evicts runs that are not busy, have no SSE subscribers and are idle longer than the limit: `sandbox.close(ref)` (not `remove`) and drop from `runs`. Next `get` reloads from the store. Test with a tiny interval/limit: run evicted, sandbox `close` called, files kept, `get` works again with the same log.
4. **Container cap.** Settings `max_open_sessions` (default 8). When `get` must load a run and `len(runs) >= cap`, evict the least-recently-used evictable run first; if none is evictable, raise `HTTPException(503, "too many active sessions, try again later")`. Test both branches.
5. README: `idle_minutes`, `max_open_sessions`, workspace dir note.

### Task B: Accounts — sign-up, password login, logout

Decisions (owner can change later):
- Username `[a-z0-9_-]{2,32}`, password ≥ 8 chars, hashed with stdlib `hashlib.scrypt` (n=2**14, r=8, p=1, 16-byte random salt), stored as `scrypt$<salt hex>$<hash hex>`. Constant-time compare (`hmac.compare_digest`).
- Sign-up is gated by settings `signup_code`: if unset, sign-up is disabled (403); if set, `POST /api/signup {name, password, code}` must match it (constant-time). A sign-up that would make LocalSandbox serve several active users without `allow_local_sandbox` is refused (409) with the `check_sandbox` message.
- Login issues a new token per device: new table `tokens(token_sha256 PRIMARY KEY, user_id, created REAL)`. `POST /api/login {name, password}` → `{"token": ...}` (401 on bad name or password, same message for both). `POST /api/logout` deletes the caller's token. Existing `users.token_sha256` (seed/rotate tokens) keeps working.
- `revoke` disables the user: nulls `users.token_sha256`, deletes all their `tokens` rows, and sets `users.disabled = 1` so password login fails too; `rotate` also deletes their `tokens` rows. `user_active` = not disabled. Old DBs: add `password TEXT` and `disabled INTEGER DEFAULT 0` columns on open (same pattern as `usage.cost`).
- CLI: `simp-server seed --name N [--password]` (prompt with `getpass` when the flag is given; still prints a token); `simp-server passwd --name N` sets a password.
- Web: Login page gets two modes, "Sign in" (username + password, plus a "use a token" link keeping the old token field) and "Create account" (username, password, invite code). Keep `aria-label="Token"` and the "That token was not accepted." text so existing e2e still pass. A "Sign out" calls `/api/logout` then clears the token.
- Tests (server): sign-up disabled / wrong code / ok; duplicate name 409; login ok/bad; token works; logout kills only that token; revoke kills login + all tokens; rotate kills login tokens; LocalSandbox refusal on sign-up. E2e (new spec `e2e/accounts.spec.ts`; `serve.sh` sets `signup_code = "e2e-code"`): create account → lands in app → sign out → sign in with password works.

### Task C: Commands, plan mode, LLM session titles (server side of items 5 and 6)

1. Protocol commands: `Compact{}`, `Continue{}`, `SetPlanMode{enabled: bool}`. Server:
   - `Compact`: only when idle; runs `session.compact()` with state `running` then back to `idle` (reuse `set_state`; compaction events already map to protocol). 409 when busy.
   - `Continue`: only when idle or error; starts a run that calls `session.continue_()` instead of `prompt` (refactor `_turn` to take a coroutine factory). Budget guard applies. 409 when busy.
   - `SetPlanMode`: any time; calls the PlanMode plugin's `set_enabled` (always load `plan_mode` in the server plugin list, after `redact_secrets`). Emits a durable `Notice` "plan mode on/off".
2. Snapshot and `SessionInfo` gain `plan_mode: bool`; Snapshot also `title: str`.
3. **Titles.** After the first assistant message of a session whose title is empty, make one extra LLM call (same model, `stream_fn` through the budget guard, max ~30 tokens, system prompt "Name this coding session in 3 to 6 words. Reply with the title only.", input = first user message truncated to 2000 chars). Strip quotes/newlines, cap 60 chars; on any error keep the title empty (log a warning, never fail the run). Save with `store.set_title(user_id, sid, title)`, record its usage/cost, and emit a new durable event `SessionTitle{seq, title}`. Runs in the background (does not delay `idle`). Tests with FakeProvider: title set once, event emitted, error path leaves empty title, budget-refused path leaves empty title.
4. README: commands, plan mode, titles cost note.

### Task E: Eval script (item 9)

- New dir `evals/` at repo root (a plain script, not a workspace package): `evals/run.py` with `uv run python evals/run.py --profile sol [--home ~/.simp-server] [--tasks a,b]`.
- Loads profile + keys the same way the server does (import `load_settings`, `take_keys`, `build_model` from `simp_server.server` / `simp_agent.session.profile`), runs each task with `AgentSession` + `LocalEnv` in a fresh temp dir, approves every tool call, max 25 turns or a 5-minute timeout per task.
- 4 tasks in `evals/tasks/*.toml`: `fizzbuzz` (write `fizzbuzz.py`, check with a hidden test), `fix_bug` (seed a buggy `calc.py` + failing pytest, pass after), `refactor_rename` (rename a function across 3 files, tests pass), `read_answer` (answer a question about a seeded file; check the answer contains a value). Each task: `setup` files, `prompt`, `check` shell command (exit 0 = pass).
- Output: one line per task `name  PASS|FAIL  turns  input/output tokens  $cost  seconds`, then a total; also writes `evals/results/<timestamp>-<profile>.json`. Cost from profile prices (0 if missing, print a warning).
- Test: `evals/test_run.py` runs the harness with `FakeProvider` scripted to solve `read_answer`, asserts PASS and the JSON shape (add `evals` to pytest `testpaths`).

### Task D (wave 2, after C merged): Web UI for commands + notifications

- Sidebar shows `title || id`; live update on `session_title`.
- Chat header: "Plan" toggle (sends `SetPlanMode`, reflects snapshot `plan_mode`), "Compact" button (disabled while busy).
- "Continue" button shown when the last durable event is the "interrupted" notice or state is `error`.
- Notifications: ask permission on first click of a "Notify me" toggle in the header (stored in localStorage); when the tab is hidden, notify on `waiting_approval` and on run end (`idle`/`error`) with the session title.
- Vitest for state reducer changes; e2e (`e2e/app.spec.ts`): plan toggle shows notice and a tool call is blocked; compact button produces a compaction item; titles appear (FakeLLM must answer title requests: in `fakellm.py`, when the system prompt starts with "Name this coding session", reply "Fake title").

## Waves

| Wave | Parallel agents |
|---|---|
| 1 | A, B, C, E |
| 2 | D (needs C), then coordinator merges, full tests, `make e2e`, browser check with the real model |
| 3 | Two reviewer subagents (debate + wide), fixes, ROADMAP update, merge to master |

## Exit criteria

- Run budget holds across follow-ups; old LocalSandbox sessions keep their files.
- After `idle_minutes`, `docker ps` shows only containers of busy/open sessions; the cap returns 503 when every session is busy.
- A new user can create an account with the invite code and sign in with a password; revoke blocks both login and tokens.
- New sessions get an LLM title; plan mode, compact and Continue work from the web; a hidden tab gets a notification.
- `evals/run.py` prints PASS/FAIL and cost per task for a real profile.
