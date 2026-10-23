# 17 Part 4 · Context overflow

**Goal:** Recover when the model says the context is too big.

**Builds on:** [16 Compaction](16-compaction.md) · **Next:** [18 Profiles and built-in plugins](18-profiles-plugins.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent --> coding --> session --> plugins --> testing
    session -.used by.-> apps["apps: cli, server (+ web)"]
    style session fill:#ffd54f,stroke:#333,stroke-width:2px
```

*This chapter adds overflow recovery to the `session` layer (marked). The detection lives in `ai`.*

Big picture of Part 4: [part-4-session](13-0-part-4-session.md).

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/ai/__init__.py` — `is_context_overflow`, `_OVERFLOW`, `is_retryable`
- `packages/simp_agent/src/simp_agent/session/__init__.py` — `AgentSession._run` (the overflow branch), `compact`
- `packages/simp_agent/tests/test_queues_compaction.py` — `test_overflow_compacts_and_retries_once`, `test_second_overflow_stops`

## Problem

We keep the story of [16](16-compaction.md). The user works in one long session on the fizzbuzz project, and the model has a 200 000-token [context window](glossary.md#context-window). Before each model call, auto compaction checks the size of the history and makes it smaller when it gets close to the limit.

But that check is only a guess. `estimate_tokens` counts real `usage` from the last answer, and for newer messages it uses "4 characters ≈ 1 token". Code and JSON often have more tokens per character than that. The window number in a profile ([18](18-profiles-plugins.md)) can also be wrong. So one day the estimate says 185 000 tokens, the check says "fine", and the user asks the agent to read one more large file. The provider counts 210 000 tokens and answers with an error: "prompt is too long: 210000 tokens > 200000 maximum". The stream ends with an assistant error message ([03](03-parse.md)).

This is a **[context overflow](glossary.md#context-overflow)**: the provider refuses a call because the request is bigger than the context window. The retry of [15](15-retry.md) cannot fix it, because the same request fails the same way every time. And without a fix the session is stuck: every new prompt makes the history even bigger.

The fix is to repair after the error. Chapter 16 **prevents** an overflow before the call, and this chapter **repairs** one after the call:

| | When | How it knows | What it does |
|---|---|---|---|
| Prevent: auto compaction ([16](16-compaction.md)) | before each model call, in `_prepare` | `should_compact` on an estimate | compact, then call |
| Repair: overflow recovery (this chapter) | after a failed call, in `_run` | `is_context_overflow` on the provider error | compact once, then call again |

Prevention handles most cases. Repair is the safety net for the times the guess was wrong. The provider is the only one who knows the real token count, so its error is the final word.

## Naive version

```text
FUNCTION run(session, text):
    WAIT for session.prompt(text)
    WHILE the last message is an error:
        IF its error text has "too long":
            WAIT for session.compact()
            WAIT for the agent to continue
        ELSE:
            STOP
```

This fixes our one overflow with one provider. It breaks in three ways.

First, each provider says it differently. Anthropic says "prompt is too long", but OpenAI says "maximum context length" or "context_length_exceeded", so the check misses them. Second, it can loop forever. If one compaction cannot make the request small enough (for example, one huge recent turn that `find_cut` in [16](16-compaction.md#where-find_cut) must keep), it compacts, fails, and compacts again, and it pays for a summary call each time. Third, if `compact()` itself fails, it still calls the model again and gets the same error.

There is also a trap in the code we already have. The retry loop of [15](15-retry.md) must never treat an overflow as a short failure, or it would wait and send the same too-big request again.

| Problem | Fix | Section |
|---|---|---|
| many wordings | one regex in `ai` | [Detecting overflow](#detecting-overflow) |
| retry would resend it | `is_retryable` says no for overflow | [Detecting overflow](#detecting-overflow) |
| endless loop | an `overflowed` flag: compact once per run | [Compact and continue, once](#compact-and-continue-once) |
| compaction fails | `compact()` returns `False`, so stop | [Compact and continue, once](#compact-and-continue-once) |

## Real design

### Detecting overflow

Real code: [ai/__init__.py](../../packages/simp_agent/src/simp_agent/ai/__init__.py) — `_OVERFLOW`, `is_context_overflow`, `is_retryable`

```text
_OVERFLOW = one regex, ignore case, any of:
    "prompt (is) too long", "request_too_large", "exceeds the context window",
    "maximum context length", "context_length_exceeded", "too many tokens",
    "token limit exceeded"

FUNCTION is_context_overflow(error):
    RETURN true IF _OVERFLOW is found in (error or "")   // no text -> false

FUNCTION is_retryable(error, kind):
    IF kind is in NON_RETRYABLE: RETURN false            // see 15
    RETURN NOT is_context_overflow(error) AND _RETRYABLE is found in (error or "")
```

One regex holds the wording of every provider, so the session never needs to know which provider it talks to. It lives in `ai`, next to the retry regex of [15](15-retry.md#which-errors-are-retryable), because both read provider error text. The `error or ""` part makes both functions safe when there is no error text: they just return false.

Look at the last line of `is_retryable`. It says "not an overflow" before it checks the retry words. This matters because some overflow messages also match retry words; "too many tokens" looks a lot like the "too many requests" of a rate limit. With this rule an error is an overflow or retryable, never both, so each error goes to exactly one fix. The limit of this design: when a provider uses a new wording, we must add a new pattern.

### Compact and continue, once

The loop in `AgentSession._run` was built in [15](15-retry.md#the-retry-loop-in-_run). That chapter skipped its first branch; here it is.

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession._run`

```text
overflowed = false, attempt = 0
WHILE last message is an assistant error:
    IF self.auto_compact AND NOT overflowed AND is_context_overflow(last.error):
        overflowed = true                  // never compact twice in one run
        IF NOT (WAIT for self.compact()): STOP loop
    ELSE IF ...retryable...:               // retry with backoff, chapter 15
        ...
    ELSE:
        STOP loop
    ADD (WAIT for a.continue_()) to new
```

The branch checks three things. `self.auto_compact` is the same switch as in [16](16-compaction.md#in-the-session): an app that turns off auto compaction also turns off overflow recovery, so there is one switch, not two. `not overflowed` makes the repair run only once per run. If one compaction was not enough, a second one with the same settings would cut at the same place and give the same result, so the flag stops the endless loop and the repeated cost. Then `compact()` runs. As [16](16-compaction.md#in-the-session) showed, it turns every failure ("nothing to compact", "summary call failed") into `False`. With no smaller history, a new call would only overflow again, so we stop.

If compaction worked, the loop ends with `a.continue_()`, the same as a retry: no new user text, just call the model again. Why does the second call now fit? Because `compact()` appended a `CompactionEntry`, and `build_view` now sends the summary plus the recent messages instead of the full history ([16](16-compaction.md#the-marker-compactionentry-and-build_view)). The overflow error itself stays in the history, because the history is append-only. But `transform_messages` drops error turns from what is sent ([01](01-pick-clean.md#2-clean-transform_messages)), so the model never sees "prompt is too long".

Clients see the same `compaction_start` and `compaction_end` events as in [16](16-compaction.md). In the UI, a repair looks like a normal auto compaction with one error turn before it.

### Edge cases

The full order of checks for both branches is in [15](15-retry.md#order-of-checks-and-edge-cases). Four cases matter for overflow.

A **second overflow** in the same run skips the overflow branch, because `overflowed` is already true. An overflow is never retryable, so the loop stops, and the run ends with the error as the last message. With **`auto_compact=False`** the same thing happens at the first overflow: no compaction and no wasted retry. If the **recent part is too big** on its own, `compact()` does not cut harder; it keeps `keep_recent_tokens` as usual, so the second call overflows and the run stops. A clear error is better than a loop. Last, an **overflow followed by a rate limit** works in one run, because the two counters are separate: `overflowed` is a flag and `attempt` counts retries. Overflow → compact → `429` → wait → success.

## Test

`packages/simp_agent/tests/test_queues_compaction.py::test_overflow_compacts_and_retries_once`:

```python
OVERFLOW = AssistantMessage(stop_reason="error", error="prompt is too long: 210000 tokens > 200000 maximum")
...
async def test_overflow_compacts_and_retries_once():
    stream = FakeProvider(OVERFLOW, AssistantMessage([TextContent("SUM")]), DONE)
    seen = stream.messages
    a = AgentSession(Model(), [], stream_fn=stream, system_prompt="s")  # big window: only the overflow forces compaction
    a.compaction.keep_recent_tokens = 5000
    a.agent.messages = history()
    await a.prompt("next")
    assert len(seen) == 3 and a.messages[-1] is DONE
    assert seen[2][0].content.startswith(SUM_HEAD) and OVERFLOW not in seen[2]
```

`history()` builds five messages of about 4 000 tokens each, so there is an old part that compaction can cut. The model has the big default window, so `should_compact` says no and only the overflow can start a compaction. `FakeProvider` ([04](04-label-test.md)) answers three times: first the overflow error, then `"SUM"` for the summary call, then `DONE`. The test checks that there were exactly 3 calls, that the run ends with `DONE`, and that the third call starts with the summary (`SUM_HEAD`) and does not hold the overflow error.

The next test, `test_second_overflow_stops`, gives `OVERFLOW, SUM, OVERFLOW`. It checks that there are still only 3 calls and the run ends with the error: the "only once" rule.

Run both:

```sh
uv run pytest packages/simp_agent/tests/test_queues_compaction.py -k overflow -q
```

## Why this way

> **Detect by text, compact once, then stop.** The provider is the only one who knows the real token count, so its error is the final word. A regex covers all providers. Compacting once and continuing fixes the common case (the estimate was a bit low). Stopping after one try avoids a loop that costs money and never ends. The cost: an unknown error wording is not seen as an overflow, and a session whose recent turns alone are too big still fails. The user then sees the error and can start a new session.

## Exercises

1. **Overflow, then a 429.** Write a test with `FakeProvider(OVERFLOW, AssistantMessage([TextContent("SUM")]), AssistantMessage(stop_reason="error", error="429 too many requests"), DONE)`. Set `retry_base_delay=0` and use `history()`. Check there are 4 calls and the last message is `DONE`.
   *Hint:* copy `test_overflow_compacts_and_retries_once`. Pass `retry_base_delay=0` to `AgentSession(...)`.
2. **Recovery off.** Same as the first test, but pass `auto_compact=False`. How many calls do you expect? (Answer: 1. Overflow is not retryable, so the loop breaks at once.)
   *Hint:* check `len(seen)` and `a.messages[-1].stop_reason == "error"`.

## Recap

Auto compaction ([16](16-compaction.md)) prevents an overflow with a guess; overflow recovery repairs one when the guess was wrong. `is_context_overflow` reads the provider error with one regex for all providers, and `is_retryable` says no to overflows, so the retry path never resends a too-big request. In `_run`, the overflow branch comes first: it compacts once and calls the model again. If compaction fails, or the call overflows a second time, the run stops with the error. The error stays in the history but is dropped from what the model sees.

Next, [18](18-profiles-plugins.md) shows where `Model.context_window` comes from: profiles.

**Builds on:** [16 Compaction](16-compaction.md) · **Next:** [18 Profiles and built-in plugins](18-profiles-plugins.md)
