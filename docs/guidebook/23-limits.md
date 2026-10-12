# 23 Part 5 · Limits

**Goal:** Stop runaway cost and free idle resources.

**Builds on:** [22-store-auth](22-store-auth.md) · **Next:** [24-docker-sandbox](24-docker-sandbox.md)

```mermaid
flowchart LR
    ai --> agent --> coding --> session --> plugins --> testing
    session -.used by.-> apps["apps: cli, server (+ web)"]
    style apps fill:#ffd54f,stroke:#333,stroke-width:2px
```

*This chapter adds limits to the `server` app (marked): a money budget, a kill switch and idle release.*

## Problem

After [22](22-store-auth.md) the server has users, sessions and a durable store. Many people can now run the agent at the same time. That brings two new risks.

**Money.** Every model call costs money. The agent loop ([05](05-agent-loop.md)) calls the model again and again until the model stops asking for tools. A confused model can loop for a long time. Say a user asks "write `fizzbuzz.py` and make the tests pass". The model writes the file, runs the tests, they fail, it edits, runs again, and so on. Fifty calls later the bill is real. Nobody is watching.

**Memory and containers.** Each open session on the server is a `Run` ([20](20-server-run.md)) in memory. Each `Run` also holds a sandbox: a folder now, a Docker container in [24](24-docker-sandbox.md). Users open a session, then close the browser tab and go home. If the server keeps every `Run` forever, it fills up RAM and leaves containers running.

So we need three things:

1. A **budget**: refuse a model call when a user or a run has spent too much.
2. A **kill switch**: the admin can stop *all* model calls at once.
3. **Idle release**: close runs nobody uses, and load them back later.

## Naive version

The simplest idea: after each run ends, add up the cost and stop the user if it is too high.

```python
PRICE_IN, PRICE_OUT = 3.0, 15.0        # USD per 1M tokens
DAY_LIMIT = 2.0
spent = {"u1": 0.0}

def cost(usage):
    return (usage["input"] * PRICE_IN + usage["output"] * PRICE_OUT) / 1e6

def fake_model_call(i):
    return {"input": 200_000, "output": 5_000}   # a long context: costs $0.675

def run(user, max_calls=50):
    if spent[user] >= DAY_LIMIT:              # check once, at the start
        return "refused"
    total = 0.0
    for i in range(max_calls):                # the agent loop: model wants more tools
        total += cost(fake_model_call(i))
    spent[user] += total                      # count only at the end
    return f"spent ${total:.2f}"

print(run("u1"))   # spent $33.75   <- limit was $2
print(run("u1"))   # refused        <- too late
```

It breaks in three ways:

1. **The check is too early, the count is too late.** One run of 50 calls spends $33.75 although the limit is $2. The check only runs before the run starts.
2. **A crash loses the count.** `spent` is in memory and is added only at the end. If the process dies mid-run, the money is spent but not recorded.
3. **No way to stop it.** If something goes wrong for all users at once (a bug, a leaked key), the admin cannot stop every running loop without killing the server.

The fix for 1 and 2: record cost after **every** model call, in the store, and check **before every** model call.

## Real design

### Cost from profile prices

`apps/server/src/simp_server/budget.py`:

```python
@dataclass
class Limits:
    user_day_usd: float = 2.0
    run_usd: float = 0.5


def limits(settings: dict) -> Limits:
    return Limits(**settings.get("budget", dict()))


def cost(profile: dict, usage: dict) -> float:
    return (usage.get("input", 0) * profile.get("price_in", 0) + usage.get("output", 0) * profile.get("price_out", 0)) / 1e6
```

There are two limits. `user_day_usd` is the most one user may spend in one day. `run_usd` is the most one **[run](glossary.md#run-budget)** may spend. They come from the `[budget]` table in `settings.toml`. If the table is missing, the defaults are $2 a day and $0.5 a run.

Prices live in each profile ([18](18-profiles-plugins.md)) as `price_in` and `price_out`, in USD per 1 million tokens. `cost` multiplies the token counts from the model's `usage` by these prices. A profile with no prices costs $0. That is a quiet hole, so the server warns at start:

```python
        for name, pr in settings["profiles"].items():
            if "price_in" not in pr or "price_out" not in pr:
                log.warning("profile %s has no prices: its calls cost $0 and never hit a budget", name)
```

### Record cost after every call

In `apps/server/src/simp_server/server.py`, the `Run` writes a usage row each time an assistant message ends:

```python
                u = {"input": m.usage.get("input", 0), "output": m.usage.get("output", 0)}
                ...
                await self.mgr.store.add_usage(self.user_id, self.sid, self.model.id, **u, cost=budget.cost(self.profile, u))
```

The row goes to the SQLite store from [22](22-store-auth.md). So the count survives a crash. The session title call (a small extra model call) records its usage the same way. Money spent is money counted, no matter which call spent it.

The store can sum it:

```python
    async def spent(self, user_id: str, since: float, session_id: str | None = None) -> float:
        sql, args = "SELECT COALESCE(SUM(cost), 0) AS c FROM usage WHERE user_id=? AND at>=?", [user_id, since]
```

`since` is a timestamp. For the day limit it is `budget.day_start()`, local midnight today. For the run limit it is the time the run started, plus the session id.

### The budget guard: wrap the stream

Now the check. Where do we put it? The agent calls the model through one function, `stream_fn` ([04](04-providers.md)). If we wrap that one function, every model call passes the check. That wrapper is the **[budget guard](glossary.md#budget-guard)**:

```python
def guard(stream_fn, check):
    async def fn(model, ctx, **kw):
        if msg := await check():
            yield {"type": "error", "message": AssistantMessage(stop_reason="error", error=msg, error_kind="budget")}
            return
        async for ev in stream_fn(model, ctx, **kw):
            yield ev

    return fn
```

`check` is an async function. It returns `None` when all is fine, or a text when the call must be refused. If refused, the guard does **not** call the real model. It yields one `error` event with an `AssistantMessage` that has `stop_reason="error"`. For the agent this looks like a normal failed model call ([03](03-stream-parser.md)). So the loop stops in the normal way. No new code path in the agent.

Note `error_kind="budget"`. Retry ([15](15-retry.md)) would normally try a failed call again. In `ai/__init__.py` the comment says `"fatal" | "budget" | "policy" = never retried (see is_retryable)`. Retrying a call that the budget refused would only be refused again.

The `Run` gives the guard to its session:

```python
    @property
    def guarded_stream(self):
        return budget.guard(self.mgr.stream_fn, self.over_budget)
```

It is passed as `stream_fn=self.guarded_stream` to `AgentSession` ([13](13-session.md)), and the title call uses `self.guarded_stream` too.

### The check itself

```python
    async def over_budget(self) -> str | None:
        lim, store, msg = self.mgr.limits, self.mgr.store, None
        if self.mgr.paused():
            msg = "budget: server paused by the admin"
        elif not await store.user_active(self.user_id):
            msg = "budget: user revoked"
        elif await store.spent(self.user_id, budget.day_start()) >= lim.user_day_usd:
            msg = f"budget: daily limit ${lim.user_day_usd:g} reached"
        elif await store.spent(self.user_id, self.run_start, self.sid) >= lim.run_usd:
            msg = f"budget: run limit ${lim.run_usd:g} reached"
        if msg:
            log.warning("over budget: %s", msg, extra=self._ctx())
        return msg
```

Four reasons to refuse, checked in order:

1. The server is paused (the kill switch, below).
2. The user was revoked ([22](22-store-auth.md)). A revoked user's running loop stops at its next model call.
3. The user spent the day limit since midnight.
4. This run spent the run limit since `run_start`.

The check is `>=` on money **already spent**. It does not guess the cost of the next call. So one call can go over the limit a little, and the *next* call is refused. That is a simple, honest rule: the limit is reached after the call that reaches it.

What is a "run" here? `run_start` is set in `Run.start`:

```python
    async def start(self, text, fresh: bool = True) -> None:  # text: a prompt, or a coroutine factory (continue_, compact)
        if fresh:  # a queued follow-up stays inside the same run budget
            self.run_start = time.time()
```

A new prompt starts a fresh run budget. But a follow-up ([07](07-steering.md)) that arrived while the loop was busy is started with `fresh=False`. So a user cannot get around the run limit by queueing many follow-ups.

When the guard refuses, the last message is an assistant message with `stop_reason == "error"`. The run then ends in state `"error"`, not `"idle"`. The client sees why from the error text.

### Kill switch: one file

A **[kill switch](glossary.md#kill-switch)** stops all model calls on the server at once. Here it is a file named `PAUSED` in the data directory:

```python
    def paused(self) -> bool:
        return (Path(self.settings["data_dir"]) / "PAUSED").exists()
```

The admin uses the CLI:

```python
    sub.add_parser("pause", help="kill switch: refuse every LLM call until resume")
    sub.add_parser("resume", help="lift the kill switch")
    ...
    if a.mode in ("pause", "resume"):
        f = Path(load_settings()["data_dir"]) / "PAUSED"
        f.touch() if a.mode == "pause" else f.unlink(missing_ok=True)
```

`pause` creates the file. `resume` deletes it. Why a file and not an API call or a flag in memory?

- It works from a shell on the machine, even when the HTTP side is broken.
- It needs no running server process to talk to, and it survives a restart.
- The guard checks it before every call, so running loops stop at their next model call.

Pause does not kill tools that are already running. It only refuses the next model call. That is enough: without the model, the loop cannot ask for more tools.

Users can see their state through `/api/usage`:

```python
    @app.get("/api/usage")
    async def usage(u=Depends(user)):
        return {"today_usd": round(await store.spent(u["id"], budget.day_start()), 4),
                "day_limit_usd": mgr.limits.user_day_usd, "paused": mgr.paused()}
```

### Idle release: evict runs nobody uses

Now memory and containers. The `SessionManager` keeps loaded runs in `self.runs`, and the last time each was used in `self.last_used`:

```python
        self.idle_s = settings.get("idle_minutes", 15) * 60
        self.cap = settings.get("max_open_sessions", 8)
```

To **[evict](glossary.md#eviction)** a run means: remove it from memory and close its sandbox. Its files and its event log stay in the store.

```python
    async def evict(self, sid: str) -> None:
        """Free RAM and the container; files and log stay, the next get reloads from the store."""
        run = self.runs.pop(sid)
        self.last_used.pop(sid, None)
        await self.sandbox.close(run.ref)
```

But we must never evict a run that is in use:

```python
    def evictable(self, run: Run) -> bool:
        return (not run.busy and not run.subs and (run.task is None or run.task.done())
                and (run.title_task is None or run.title_task.done()))
```

A run is safe to evict only if it is not busy, no client is subscribed to its stream ([21](21-transport.md)), its task is done, and its title task is done. An open browser tab counts as "in use", even if the user types nothing.

`evict_idle` evicts every evictable run that was not used for `idle_s` seconds:

```python
    async def evict_idle(self) -> None:
        async with self.lock:
            now = time.monotonic()
            for sid, run in list(self.runs.items()):
                if self.evictable(run) and now - self.last_used.get(sid, 0) >= self.idle_s:
                    await self.evict(sid)
```

A background task calls it every `evict_every` seconds (default 60). It is started in the app lifespan with `mgr.evict_loop(...)`. `evict_loop` catches and logs errors, so one failed eviction does not stop the loop.

There is also a hard cap. In `SessionManager.get`, if `max_open_sessions` runs are already loaded, the least recently used evictable run is evicted to make room. If none can be evicted, the server answers `503 "too many active sessions, try again later"`.

What happens when the user comes back? `get` sees the session is not in `self.runs`. It opens the sandbox again, builds a new `Run` from the stored entries, and calls `recover()` ([22](22-store-auth.md)). The user sees the same history and the same files. Eviction is invisible, except for a short load time.

## Test

`apps/server/tests/test_budget.py::test_run_budget_stops_tool_loop`:

```python
PROFILE = '[profiles.test]\napi = "fake"\nmodel = "m"\nprice_in = 1000000\nprice_out = 0\n'  # $1 per input token
...
async def test_run_budget_stops_tool_loop(tmp_path):
    # price_in = $1 per input token and each reply reports 1 input token -> every LLM call costs $1
    fp = FakeProvider(*[usage_reply("", [ToolCall(f"c{i}", "bash", {"command": "true"})]) for i in range(5)])
    app, mgr, user, _, run = await make(tmp_path, fp, "[budget]\nrun_usd = 1.5\nuser_day_usd = 100\n")
    await run.command(p.Prompt(text="go"))
    while run.busy:  # allow every bash call
        if run.pending and not run.answer.done():
            run.answer.set_result("allow")
        await asyncio.sleep(0.01)
    assert fp.calls == 2  # $1 + $1 > $1.5 -> third call refused before reaching the provider
    assert run.state == "error"
    assert any(e["type"] == "notice" and "budget" in e["text"] for e in run.log) or \
        any(e["type"] == "assistant_message" and e.get("error") and "budget" in e["error"] for e in run.log)
    assert await mgr.store.spent(user["id"], 0) == 2
    await mgr.store.close()
```

What it checks:

- The `FakeProvider` ([02](02-fake-provider.md)) has five replies. Each asks for a `bash` tool call, so the loop wants to go on and on: this is the runaway loop from the naive version.
- The price is $1 per input token and each reply reports 1 input token. So each call costs $1. The run limit is $1.5.
- After call 1: spent $1, under the limit. After call 2: spent $2, over. Call 3 is refused **before** it reaches the provider. So `fp.calls == 2`.
- The run ends in state `"error"`, and the log says "budget".
- The store recorded exactly $2. The count is in the database, not in memory.

Run it:

```sh
uv run pytest apps/server/tests/test_budget.py::test_run_budget_stops_tool_loop -q
```

Other tests in the same file cover the day limit (`test_day_budget_and_pause`), the kill switch (`test_pause_refuses_llm_calls`, which checks `fp.calls == 0`), and follow-ups that share one run budget (`test_run_budget_spans_follow_ups`). For idle release, see `apps/server/tests/test_lifecycle.py::test_idle_run_evicted_and_reloaded`: with `idle_minutes = 0`, an open stream keeps the run; after the stream goes away the run is evicted, the sandbox is closed, and a new `get` gives back the same log and the same file `f.txt`. `test_busy_run_not_evicted` checks that a running loop is never evicted.

## Why this way

> **Guard the one door, count in the store.** Every model call goes through `stream_fn`, so one small wrapper (`budget.guard`) covers the agent loop, retries and the title call. The library does not know about money; the server adds it from outside. The refusal looks like a normal model error, so the agent needs no new code. Cost is written to the store after each call, so a crash cannot hide spending. The cost of this choice: the check uses money already spent, so the last call can go a little over the limit. The kill switch is a file because the admin must be able to use it when everything else is broken. Eviction keeps only state the store can rebuild, so freeing memory loses nothing.

## Recap

- `budget.cost` turns token usage into USD from profile prices. Each call's cost is saved with `store.add_usage`.
- `budget.guard` wraps `stream_fn`. Before each model call it runs `Run.over_budget`. If that returns a reason, the call is refused with `error_kind="budget"` and is never retried.
- Four reasons: server paused, user revoked, day limit, run limit. Follow-ups share the run budget.
- The kill switch is a `PAUSED` file in the data dir. `simp-server pause` / `resume` create and delete it.
- `SessionManager.evict_idle` frees runs that are idle, not busy and have no subscribers. A cap of `max_open_sessions` evicts the least recently used run or returns 503. Evicted runs load back from the store.

**Builds on:** [22-store-auth](22-store-auth.md) · **Next:** [24-docker-sandbox](24-docker-sandbox.md)

## Terms to add to glossary

- **budget guard** — a wrapper around `stream_fn` that checks limits before each model call and refuses the call with an error message if a limit is reached.
- **run budget** — the most money one run (a prompt plus its queued follow-ups) may spend; `run_usd` in settings.
- **daily budget** — the most money one user may spend since local midnight; `user_day_usd` in settings.
- **kill switch** — the `PAUSED` file in the data dir; while it exists every model call on the server is refused.
- **eviction** — removing an unused `Run` from memory and closing its sandbox; files and log stay in the store and load back on the next use.
- **idle release** — evicting runs that were not used for `idle_minutes`.
