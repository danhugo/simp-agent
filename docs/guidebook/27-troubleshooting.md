# 27 — Troubleshooting

> **Who this is for:** an operator whose server shows an error.
> **What you need first:** [22 Users and accounts](22-users.md), [23 Sandboxes](23-sandboxes.md), [24 Money and limits](24-money.md). Words: [access token](glossary.md#access-token), [sandbox](glossary.md#sandbox), [budget](glossary.md#budget), [session](glossary.md#session), [provider](glossary.md#provider).
> **What you will learn:** for each common error: what you see, why it happens, how to fix it, and which chapter explains it.
> **Code paths covered:** `apps/server/src/simp_server/server.py` (`over_budget`, `check_sandbox`, `host_guard`, session cap, login), `apps/server/src/simp_server/sandboxes/docker.py`, `packages/simp_agent/src/simp_agent/ai/__init__.py`.
> **Verified at commit:** `273796c` (error texts copied from code; the errors were not all triggered by hand).

**Back:** [26 Security model and known gaps](26-security.md) · **Next:** [30 Architecture](30-architecture.md)

Each entry has the same shape: **You see** → **Why** → **Fix** → **Home chapter**. First check the server log ([25](25-ops.md)); it often names the cause.

## 1. 401 after `rotate` (or `revoke`)

- **You see:** HTTP 401 `bad token`. In the web page: "That token was not accepted." A password login gives 401 "Wrong username or password."
- **Why:** `rotate` and `revoke` delete the old tokens. Only the new token printed by `rotate` works. It is printed once, and the database keeps only a hash, so it cannot be shown again.
- **Fix:** give the user the new token from `rotate`. If you lost it, run `rotate` again. If the user was revoked, `rotate` also turns them back on. A revoked user's password stays wrong-looking until then.
- **Home:** [22 Users and accounts](22-users.md#6-revoke-and-rotate).

## 2. Budget errors

- **You see** one of these in the chat as an error:
  - `budget: daily limit $N reached`
  - `budget: run limit $N reached`
  - `budget: server paused by the admin`
  - `budget: user revoked`
- **Why:** before every model call the server checks, in this order: the `PAUSED` file, user revoked, daily limit, run limit. The first one that fails stops the call. These errors are never retried.
- **Fix:**
  - *daily limit*: wait for the next local day, or raise `user_day_usd` in `settings.toml` and restart.
  - *run limit*: start a new run (send a new message), or raise `run_usd`.
  - *paused*: run `uv run simp-server resume` (it deletes the `PAUSED` file).
  - *user revoked*: see section 1.
- **Also:** if a profile has no `price_in` / `price_out`, its calls cost $0 and never hit a limit. The server logs a warning at start.
- **Home:** [24 Money and limits](24-money.md#3-the-check).

## 3. 503 "too many active sessions, try again later"

- **You see:** HTTP 503 `too many active sessions, try again later` when opening or using a session.
- **Why:** `max_open_sessions` (default 8) sessions are loaded and **all** are busy, so none can be unloaded to make room.
- **Fix:** try again in a moment. For a larger team, raise `max_open_sessions` and make sure the machine has memory for the containers.
- **Home:** [21 Configuration reference](21-configuration.md#6-capacity).

## 4. The server refuses to start: LocalSandbox with several users

- **You see:** the server exits at start with:
  `N users but the sandbox is LocalSandbox (no isolation). Run `simp-server build-sandbox` and set [plugins] sandbox = "simp_server.sandboxes.docker:DockerSandbox" (or SIMP_SANDBOX=docker), or set allow_local_sandbox = true.`
- **Why:** with `LocalSandbox`, the agent's commands run as the server user. That is only safe for one person, so the server will not start with more than one user.
- **Fix:** the safe way is Docker: run `uv run simp-server build-sandbox`, then set the sandbox plugin as the message says. Use `allow_local_sandbox = true` only if you trust everyone fully.
- **Note:** `rotate` can bring back a revoked user and push you over one user without this check ([22](22-users.md#6-revoke-and-rotate)). The check runs at start only.
- **Home:** [23 Sandboxes](23-sandboxes.md#3-why-docker-for-several-users).

## 5. Docker is not running

- **You see:** the session shows `docker run failed: ...` followed by Docker's own words (for example it cannot reach the daemon, or the image is missing).
- **Why:** each session starts a container with `docker run`. If Docker Desktop is off, the image was not built, or the server user may not use Docker, the command fails.
- **Fix:** start Docker; run `uv run simp-server build-sandbox` if the image is missing; test with `docker ps` as the same user that runs the server. Then send the message again; the session opens a fresh container.
- **Home:** [23 Sandboxes](23-sandboxes.md#7-if-docker-is-not-ready).

## 6. Provider errors and a bad key

- **You see:**
  - `no API key for provider <name>` — the server found no key.
  - Any other error text — it comes from the provider (for example a rejected key, no credit, or a wrong model id).
- **Why:** the key is read from the environment variable named by `api_key_env` in the profile (default `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY` for OpenAI-style APIs). A missing key is a fatal error and is not retried. Other errors are retried only when they look temporary (for example a busy provider); a rejected key is not fixed by waiting.
- **Fix:** set the variable in the environment of the **server process** (a launchd service does not see your shell, see [25](25-ops.md)). Check `model` and `base_url` in the profile. Restart the server. To test without a key use `simp-server fake` ([01](01-quick-start.md)).
- **Home:** [21 Configuration reference](21-configuration.md#3-profilesname).

## 7. "bad host" (403)

- **You see:** HTTP 403 `{"detail": "bad host"}` when you open the server by a name or LAN address.
- **Why:** the server accepts only the names in `allowed_hosts` (default `localhost`, `127.0.0.1`). This blocks DNS-rebinding tricks.
- **Fix:** add the name users type, **without the port**, to `allowed_hosts` and restart. Do not add `*`-style guesses; list the real names.
- **Home:** [21 Configuration reference](21-configuration.md#2-top-level-keys); why: [26 Security](26-security.md).

## 8. Other messages you may meet

| Text | Meaning | Home |
|---|---|---|
| `sign-up is closed or the invite code is wrong` (403) | No `signup_code` is set, or the code differs. | [22](22-users.md) |
| `that username is taken` (409) | Pick another name. | [22](22-users.md) |
| `password: at least N characters` (400) | Password too short. | [22](22-users.md) |
| `N messages already queued` (429) | Too many follow-ups waiting; wait for the run. | [11](11-web.md) |
| `file larger than N bytes` (413) | Upload over the limit. | [11](11-web.md) |
| `run stopped unexpectedly` | Server-side crash in a run; see the log. | [25](25-ops.md) |

## 9. If nothing here fits

1. Read the log ([25](25-ops.md)). 2. Try `simp-server fake` to see if the problem is the provider or the server. 3. Check the gaps list ([26](26-security.md)): it may be a known gap, not a bug.

---

**Built on by:** [30 Architecture](30-architecture.md).
**Builds on:** [21](21-configuration.md), [22](22-users.md), [23](23-sandboxes.md), [24](24-money.md), [25](25-ops.md), [26](26-security.md).
