# 15 Part 4 · Retry

**Goal:** Retry failed model calls with backoff.

**Builds on:** [04 Errors are plain text](04-label-test.md#errors-are-plain-text) · [06 Abort](06-events-abort.md) · [13 Sessions](13-session.md) · [14 Plugins](14-plugins.md) · **Next:** [16 Compaction](16-compaction.md)

## Where we are

This chapter adds retry to the `session` layer. Big picture of Part 4: [part-4-session](13-0-part-4-session.md).

In [13](13-session.md) the user came back the next day and typed "now add tests". The agent is in the middle of the work when the model API answers `429 rate limit` ("too many requests, wait a moment").

## Why does a 429 stop the run, and where should retry live?

As [04](04-label-test.md#errors-are-plain-text) showed, the stream does not raise for a failed call. The reply is an `AssistantMessage` with `stop_reason` `"error"` and the error text in `error`. The agent loop ([05](05-agent-loop.md)) sees that and ends the run. So one `429` stops the work, and the user must type "continue" by hand, even though the error would be gone a few seconds later.

Retry does not go inside the model call: the loop has already turned the failure into a message and ended. It goes one level up, in the session. After the run ends, the session looks at the last message and, if it is a short failure, starts the loop again. Both `prompt()` and `continue_()` of the session go through one method, `AgentSession._run`, so both get retry.

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession._run`

## Which errors are worth trying again?

Only errors that can go away by themselves: a rate limit, an overloaded server, a dropped connection. A missing API key fails every time, so trying again only wastes time.

The function `is_retryable(error, kind)` in `ai` decides with two inputs. The first is the error text. Providers do not share error types, but their text almost always has words like `429`, a `5xx` code, "overloaded" or "timed out". One regex over the text works for every provider.

The second is the [`error_kind`](glossary.md#error_kind). The text cannot tell "the provider rate-limits you" from "our own budget stops you", so our own code marks its own errors with a kind. `stream()` sets `"fatal"` when there is no API key, and the server sets `"budget"` when a user is over their limit ([23](23-limits.md)). If the kind is in `NON_RETRYABLE`, the error is never retried, even when the text looks retryable.

A context overflow ("prompt is too long") is not retried either, because the same too-big request would fail again. It has its own fix in [17](17-overflow.md).

Real code: [ai/__init__.py](../../packages/simp_agent/src/simp_agent/ai/__init__.py) — `is_retryable`, `NON_RETRYABLE`

## How do we try again?

We call the agent's `continue_()`. It asks the model again with the same history; we do not send the user's text a second time.

The failed reply stays in the history, because history is append-only ([13](13-session.md)). The user and the store still see the error. But the model does not: before each call, `transform_messages` drops assistant turns with `stop_reason` `"error"` or `"aborted"` ([01](01-pick-clean.md#2-clean-transform_messages)), so the model is not confused by its own broken reply.

## How long do we wait?

The wait doubles each time: `retry_base_delay * 2 ** (attempt - 1)`. This is exponential [backoff](glossary.md#backoff). A busy server gets more room after each failure, instead of being hit again at the same speed.

Two plain settings of the session control it: `retry_base_delay` (default 2 seconds) and `max_retries` (default 3). With the defaults, the waits are 2, 4 and 8 seconds, and then the session gives up. `max_retries=0` turns retry off. The counter starts at 0 in each run, so the next prompt gets 3 full tries again.

## What if the user presses Stop during the wait?

During the wait, no model call is running. So the agent's abort from [06](06-events-abort.md) has nothing to stop, and the retry would run anyway.

The session therefore has its own abort event, an `asyncio.Event`. The wait is not a plain sleep; it waits for this event, but at most `delay` seconds:

```python
await asyncio.wait_for(self._abort.wait(), delay)
```

The path is short. The user presses Stop, the app calls the session's `abort()`, and `abort()` sets the event and also tells the agent to abort (for the case where a model call is running). The set event ends the wait at once, and `_run` leaves the loop with no retry. If no one aborts, the time runs out, `wait_for` raises `TimeoutError`, `_run` catches it, and the retry goes ahead. `_run` makes a fresh event at the start of each run, so an old abort does not stop the next prompt.

Real code: [session/__init__.py](../../packages/simp_agent/src/simp_agent/session/__init__.py) — `AgentSession.abort`

## How does the user see it?

Without a sign, the screen looks frozen during the wait. So the session sends two [events](glossary.md#auto_retry_start--auto_retry_end). Before each wait it sends `auto_retry_start` with the attempt number, the max, the delay and the error. At the end it sends one `auto_retry_end` with `success` true or false. Both are sent only if something was retried. The CLI uses `auto_retry_start` to show "retrying". The server turns both into notices for the web UI ([20](20-server-run.md)).

**Builds on:** [14 Plugins](14-plugins.md) · **Next:** [16 Compaction](16-compaction.md)
