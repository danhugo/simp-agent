# 15 Part 4 · Retry

**Goal:** Retry failed model calls with backoff.

**Builds on:** [04 Errors are plain text](04-label-test.md#errors-are-plain-text) · [06 Abort](06-events-abort.md) · [13 Sessions](13-session.md) · [14 Plugins](14-plugins.md) · **Next:** [16 Compaction](16-compaction.md)

## Where we are

This chapter adds retry to the `session` layer. Big picture of Part 4: [part-4-session](13-0-part-4-session.md).

In [13](13-session.md) the user came back the next day and typed "now add tests". The agent is in the middle of the work when the model API answers `429 rate limit` ("too many requests, wait a moment").

## Why do we need retry?

The agent loop ends a run as soon as a model call fails. A failed call does not raise: it comes back as a reply with `stop_reason` `"error"` ([04](04-label-test.md#errors-are-plain-text)), and the loop stops when it sees one ([05](05-agent-loop.md)). So one `429` stops the work, and the user must type "continue" by hand, even though the error would be gone a few seconds later. Retry does that "continue" for the user, automatically, when the error is only a short one.

## How does retry work?

Retry sits in the session, around the agent loop. Remember that a [run](glossary.md#run-agent) is one call of the loop: from the user's message until the loop stops ([05](05-agent-loop.md)). When a `429` ends a run early, the loop has already stopped. The session then looks at the last message. If it is a short failure, the session waits a little and starts a **new run** with the same history, exactly what the user's "continue" would do. It does this a few times at most. The loop itself does not change; it still just stops on the error. Both `prompt()` and `continue_()` of the session go through one method, `AgentSession._run`, so both get retry.

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession._run`

Here is one retry from start to end, in our story:

1. The model API answers `429`. The reply becomes an error message whose text is what the API sent, such as "429 Too Many Requests: rate limit exceeded", and the loop ends the run.
2. The session reads the last message in the history: an error whose text contains `429`. There is no separate error code; the session only checks the words in that text. The check in the next section says this kind of error is worth a retry, so the session tells the app "retry 1 of 3, waiting 2 seconds" (`auto_retry_start`).
3. It waits 2 seconds, then asks the model again with the same history.
4. This time the model answers. The session tells the app "retry done, it worked" (`auto_retry_end`), and the agent goes on adding tests.

The next sections explain the parts: which errors are worth a retry, how the new run starts, how long to wait, and what Stop does during the wait.

## Which errors are worth trying again?

The question is simple: **will waiting help?** It helps for errors that go away by themselves: a rate limit, an overloaded server, a dropped connection. It never helps for a missing API key, a user who has spent their budget, or a request that is too big for the model; trying again only wastes time. The session decides with three checks, in this order:

1. **Did our own code mark the error as final?** When our own code stops a call on purpose, it adds a label to the error, called its [kind](glossary.md#error_kind): `fatal` (for example, no API key), `budget` (the user has spent their limit, see [23](23-limits.md)) or `policy`. An error with one of these labels is never retried. For example, "budget: daily limit $5 reached" cannot change until tomorrow. Our code already knows that, so it says so with the label instead of leaving the session to guess from words.
2. **Is the request too big for the model?** The error says something like "prompt is too long" (a context overflow). The same request would fail again, so there is no retry here; [17](17-overflow.md) fixes it by making the history smaller.
3. **Does the error text look short-lived?** Each provider writes its errors differently, but almost all of them contain words like `429`, a `5xx` code, "rate limit", "overloaded" or "timed out". One pattern search over the text finds these words for every provider. If it finds one, the error is worth a retry.

Real code: [ai/__init__.py](../../packages/simp_agent/src/simp_agent/ai/__init__.py) — `is_retryable` (the three checks), `NON_RETRYABLE` (the final labels)

## What does the new run send to the model?

We call the agent's `continue_()`. It asks the model again with the same history; we do not send the user's text a second time.

The failed reply stays in the history, because history is append-only ([13](13-session.md)). The user and the store still see the error. But the model does not: before each call, `transform_messages` drops assistant turns with `stop_reason` `"error"` or `"aborted"` ([01](01-pick-clean.md#2-clean-transform_messages)), so the model is not confused by its own broken reply.

## How long do we wait?

Each wait is twice as long as the one before: 2 seconds, then 4, then 8. This is exponential [backoff](glossary.md#backoff) (in code, `retry_base_delay * 2 ** (attempt - 1)`). A busy server gets more room after each failure, instead of being hit again at the same speed.

Two plain settings of the session control it: `retry_base_delay` (default 2 seconds) and `max_retries` (default 3). With the defaults, the waits are 2, 4 and 8 seconds, and then the session gives up. `max_retries=0` turns retry off. The counter starts at 0 in each run, so the next prompt gets 3 full tries again.

## What if the user presses Stop during the wait?

The agent's Stop from [06](06-events-abort.md) stops *what is running*: a model call or a tool. During the wait, nothing is running, so that Stop has nothing to stop, and when the wait ends the retry would start anyway. The user pressed Stop and the agent goes on: that is the bug to avoid.

So the session has its own Stop flag, and its wait means "sleep up to N seconds, but wake up at once if Stop is pressed". When the user presses Stop, the session's `abort()` sets this flag (and also stops the agent, in case a model call is running). The wait wakes up early, and the session ends without retrying. If nobody presses Stop, the time runs out and the retry goes ahead. Each run starts with a fresh flag, so an old Stop does not cancel the next prompt.

In code, the wait is one line: `await asyncio.wait_for(self._abort.wait(), delay)`. It waits for the flag, but at most `delay` seconds; when the time runs out it raises `TimeoutError`, which `_run` catches as "no Stop, go on".

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession.abort`

## How does the user see it?

Without a sign, the screen looks frozen during the wait. So the session sends two [events](glossary.md#auto_retry_start--auto_retry_end). Before each wait it sends `auto_retry_start` with the attempt number, the max, the delay and the error. At the end it sends one `auto_retry_end` with `success` true or false. Both are sent only if something was retried. The CLI uses `auto_retry_start` to show "retrying". The server turns both into notices for the web UI ([20](20-server-run.md)).

**Builds on:** [14 Plugins](14-plugins.md) · **Next:** [16 Compaction](16-compaction.md)
