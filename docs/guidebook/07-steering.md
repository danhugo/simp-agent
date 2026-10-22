# 07 Part 2 · Steering

**Goal:** Let the user add messages while the agent works.

**Builds on:** [06 Events and abort](06-events-abort.md) · **Next:** [08 Hooks and approval](08-hooks-approval.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent["agent ★ steer / follow_up queues (this chapter)"] --> coding --> session --> plugins --> testing
```

Big picture of Part 2: [part-2-agent](05-0-part-2-agent.md).

In [06](06-events-abort.md) the user got a **Stop** button. But stop is a hard tool. Often the user does not want to stop. They want to say "wait, use the other file" while the agent is still running a tool. Or they want to queue "now write the tests" for when the current job is done.

This chapter adds two queues to the agent:

- [Steer](glossary.md#steer): a message that should reach the model **as soon as possible**, in the middle of the work.
- [Follow-up](glossary.md#follow-up): a message that should wait **until the agent would stop**, then start more work.

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/agent/__init__.py` — `LoopConfig.get_steering` / `get_follow_up`, the two `while` loops of `agent_loop`, the steering poll in `_llm_turn`, and `Agent.steer`, `follow_up`, `_take`, `clear_queues`, `has_queued`
- `packages/simp_agent/tests/test_queues_compaction.py` — the queue tests

## Problem

In [06](06-events-abort.md) we saw that `Agent` allows **one run at a time**. A second `prompt()` during a run raises `RuntimeError`. That rule is right: two loops writing to one history would mix their messages.

But the user still types while the agent works. A coding run can take minutes. In that time the user may see the agent go the wrong way, or think of the next task. We need a way to take their text **now** and deliver it **at a safe point** later.

What is a safe point? The history must stay valid. The model asked for tools; each tool call must be followed by its tool result ([01](01-pick-clean.md)). If we put a user message **between** a tool call and its result, vendors reject the request. So "deliver now" really means "deliver at the next place where the history is complete".

An example. The model asks for three tools: `read a.py`, `read b.py`, `edit c.py`. While `read a.py` runs, the user types "use d.py, not c.py".

Wrong history (message put in at once):

```text
assistant: call_1 read a.py, call_2 read b.py, call_3 edit c.py
user:      "use d.py, not c.py"        <- between calls and results
tool:      result of call_1
tool:      result of call_2
tool:      result of call_3
```

The vendor rejects this request: the tool results no longer come right after the calls.

Right history (message kept, then put in at the safe point):

```text
assistant: call_1 read a.py, call_2 read b.py, call_3 edit c.py
tool:      result of call_1
tool:      result of call_2
tool:      result of call_3
user:      "use d.py, not c.py"        <- safe point: every call has its result
// next model call sees the message and changes plan
```

As a timeline:

```mermaid
sequenceDiagram
    participant U as User
    participant L as Loop
    participant T as Tools
    L->>T: run call_1 (read a.py)
    U->>L: steer("use d.py, not c.py")
    Note over L: keep it in the queue
    T-->>L: result 1
    L->>T: run call_2 (read b.py)
    T-->>L: result 2
    L->>T: run call_3 (edit c.py)
    T-->>L: result 3
    Note over L: safe point: read the queue, add the message
    L->>L: next model call sees results + message
```

Note the cost: all three tools still run, so `edit c.py` still happens. Steer changes the **next** decision. To stop the tools now, the user needs abort ([06](06-events-abort.md)). Below, we call each place where the loop checks the queue a **read point**.

## Naive version

```text
CLASS NaiveAgent(loop_fn):
    running = false
    inbox = empty list

    FUNCTION say(text):
        IF running:
            ADD UserMessage(text) to inbox      // keep it for later
            RETURN
        START run([UserMessage(text)]) in the background

    FUNCTION run(prompts):
        running = true
        WAIT for loop_fn(prompts)               // runs until the model stops
        running = false
        IF inbox is not empty:                  // deliver at the very end
            msgs = TAKE everything from inbox
            WAIT for run(msgs)
```

Where it breaks:

- **"Change plan" comes too late.** The inbox is read only when the whole run is over. If the agent is about to edit ten files the wrong way, the user's "stop, use the other file" waits until all ten edits are done.
- **One inbox for two needs.** "Change plan" (urgent) and "then write tests" (later) go to the same place. The agent cannot tell them apart.
- **All or nothing.** Three queued messages are sent as one batch. Sometimes the user wants each one handled as its own task.
- **Not one run.** Each delivery is a new `run`, with new `agent_start` / `agent_end` [events](glossary.md#event). A UI that shows "busy" until `agent_end` flickers off and on.

## Step by step: from naive to real

We fix the naive version one problem at a time.

**Step 1 — two queues, not one inbox.** "Change plan" and "then write tests" need different times. So `Agent` keeps two lists, and the user picks one:

```text
FUNCTION steer(text):
    ADD UserMessage(text) to steering

FUNCTION follow_up(text):
    ADD UserMessage(text) to follow_ups
```

**Step 2 — read steering after each tool batch.** The naive inbox waits for the whole run. Now the loop reads steering after every turn, when all tool results are in the history, so the message is safe to add:

```text
// at the end of each turn, inside the inner loop
has_calls = (the model asked for tools)
pending = config.get_steering()
```

**Step 3 — keep going in the same run.** The inner loop goes on while there are tool calls **or** steering. When it ends, the outer loop asks for follow-ups. So there is one `agent_start` and one `agent_end`, and the UI does not flicker:

```text
FOREVER:
    WHILE has_calls OR pending:
        ...                          // one turn
    pending = config.get_follow_up()
    IF pending is empty: STOP
```

**Step 4 — one message or all.** The naive version sends everything as one batch. `_take` uses a mode, so each message can get its own turn:

```text
n = IF mode is "all": length of queue, ELSE: at most 1
```

The result is the real design below.

## Real design

### Two hooks in `LoopConfig`

`agent_loop` itself has no queue. It only asks the caller, through two functions in `LoopConfig`:

```text
get_steering  = a function that returns a list, default: empty list
                // messages typed while working; read after each tool batch
get_follow_up = a function that returns a list, default: empty list
                // read only when the loop would otherwise stop
```

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`LoopConfig`)

Each one returns a list of messages (often empty). (The comment on `get_steering` says "after each tool batch", but as we see below it is read at three points.) The loop calls them at fixed points and adds what they return to the history with `add` ([06](06-events-abort.md#events-one-stream-of-small-dicts)), so each message also gives `message_start` / `message_end` events.

Why functions and not lists? The loop does not care where the messages come from. `Agent` keeps them in lists, but a server could read them from a database or a socket. The loop only needs "give me what is waiting now".

### Two loops: inner for steering, outer for follow-ups

Here is the core of `agent_loop` again, now with the queue parts (`packages/simp_agent/src/simp_agent/agent/__init__.py`; the tool batch is cut, see [05](05-agent-loop.md)):

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`agent_loop`)

```text
SEND event {agent_start}
FOR EACH p in prompts: add(p)
pending = config.get_steering()          // read point 1
has_calls = true
FOREVER:                                 // outer loop: follow-ups
    WHILE has_calls OR pending:          // inner loop: one pass = one turn
        SEND event {turn_start}
        FOR EACH p in pending: add(p)
        pending = empty
        msg = WAIT for _llm_turn(...)    // model call (read point 2 is inside)
        add(msg)
        ...                              // error / abort exit, then the tool batch
        SEND event {turn_end, msg}
        has_calls = (msg asked for tools)
        pending = config.get_steering()  // read point 3
    pending = config.get_follow_up()
    IF pending is empty: STOP
SEND event {agent_end, new messages}
RETURN new messages
```

Read it as two loops:

- **Inner loop** (`while has_calls or pending`): one pass is one [turn](glossary.md#turn). It goes on while the model asked for tools **or** a steering message is waiting. So a steer can start a new turn even when the model was done.
- **Outer loop** (`while True`): runs only when the inner loop ends, which means the agent would stop now. Then it asks for follow-ups. If there are some, `pending` is not empty, so the inner loop starts again. If there are none, the run ends.

The whole thing is **one run**: one `agent_start`, one `agent_end`, however many messages were delivered. The UI stays "busy" the whole time.

### When each queue is read

Steering is read at three points, follow-ups at one:

```mermaid
flowchart TD
    A[agent_start, add prompts] --> S1["get_steering() #1<br/>(typed before the run began)"]
    S1 --> T[turn_start, add pending]
    T --> P[prepare_next_turn]
    P --> S2["get_steering() #2<br/>(typed during a slow prepare)"]
    S2 --> M[model call]
    M --> B[tool batch]
    B --> S3["get_steering() #3<br/>(typed during the model call or tools)"]
    S3 -->|tool calls or steering| T
    S3 -->|neither| F["get_follow_up()"]
    F -->|got some| T
    F -->|empty| E[agent_end]
```

1. **Before the first turn.** `pending = config.get_steering()` right after the prompts. A steer that arrived just before the run starts is sent with the prompt. (Point 2 also runs on the first turn.)
2. **Inside `_llm_turn`, just before the model call.** This is the latest possible moment:

   ```text
   // inside _llm_turn, before the model call
   view = WAIT for config.prepare_next_turn(messages)
   view = copy of (messages IF view is none ELSE view)   // always a copy
   FOR EACH p in config.get_steering():     // read point 2
       add(p)                               // into the history
       ADD p to view                        // and into this turn's view
   ```

   Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`_llm_turn`)

   `prepare_next_turn` may be slow: it is where compaction runs ([16](16-compaction.md)), and when compaction runs, that is one more model call. A message typed during it goes into this turn, not the next. The docstring says it: "prepare_next_turn hook -> steering poll (the hook may be slow) -> …". The message is added to the history **and** to `view`, because `view` was built before the poll.
3. **After the tool batch** (`has_calls, pending = bool(calls), config.get_steering()`). This is the main point, and the one in the example at the top. All tool results are in the history now, so a user message is safe here.

Follow-ups are read at one point only: when the inner loop has ended.

Note what steering does **not** do: it does not stop the running tool or skip the rest of the batch, as the example at the top showed. To stop a tool, the user needs [abort](glossary.md#abort).

### Errors and abort leave the queues alone

If the turn ends with `error` or `aborted`, `agent_loop` returns at once through `_end` ([06](06-events-abort.md#abort-one-asyncioevent)). It does not call `get_steering` or `get_follow_up` again. So waiting messages stay in the queues. The `Agent` docstring says:

> Queued messages survive abort(); they wait for the next prompt() or clear_queues().

This is on purpose. The user pressed Stop, not "throw away what I typed". The next `prompt()` reads the steering queue at point 1, so the old messages go out with the new prompt. If the UI wants them gone, it calls `clear_queues()`.

### The `Agent` side: two lists and a mode

`Agent` owns the real queues:

```text
CLASS Agent:
    steering = empty list
    follow_ups = empty list
    steering_mode = follow_up_mode = "one-at-a-time"   // or "all"

    FUNCTION steer(text):        ADD UserMessage(text) to steering
    FUNCTION follow_up(text):    ADD UserMessage(text) to follow_ups
    FUNCTION clear_queues():     EMPTY steering and follow_ups
    FUNCTION has_queued():       RETURN true IF either list is not empty
```

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`Agent.steer / follow_up / clear_queues / has_queued`)

`steer` and `follow_up` are plain sync methods, like `abort`. They only append to a list; they never wait for the loop. A key handler can call them at any time, during a run or not. `has_queued` lets a UI show "2 messages waiting".

The [mode](glossary.md#queue-mode) decides how many messages one read takes:

```text
FUNCTION _take(queue, mode):
    n = IF mode is "all": length of queue, ELSE: at most 1
    out = the first n messages of queue
    REMOVE those n messages from queue    // so a message is never sent twice
    RETURN out
```

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`Agent._take`)

- `"one-at-a-time"` (default): take the oldest message only. Each queued message gets its own turn, and the model answers each one.
- `"all"`: take everything. The model sees all waiting messages together in one turn.

`_take` removes what it returns (`del queue[:n]`), so a message is never sent twice.

Finally `_run` connects the lists to the loop:

```text
// inside _run, when building LoopConfig
get_steering  = WHEN called: RETURN _take(steering, steering_mode)
get_follow_up = WHEN called: RETURN _take(follow_ups, follow_up_mode)
```

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`Agent._run`)

The lambdas read `self.steering` at call time, not when `_run` starts. So a `steer()` called in the middle of the run is seen at the next read point.

Higher layers pass text down: the session ([13](13-session.md)) has its own `steer` / `follow_up` that call `self.agent.steer(text)` / `self.agent.follow_up(text)`, and the CLI ([19](19-cli.md)) and server ([20](20-server-run.md)) call those. `Agent`'s lists have no size limit; the server adds its own cap (`MAX_QUEUED`) and handles a follow-up that arrives just after the loop decided to stop by starting a new run ([20](20-server-run.md)).

## Test

The tests are in `test_queues_compaction.py`. They use [FakeProvider](04-label-test.md) and its `messages` list, which records what the model was sent on each call.

Steer during a tool:

```text
TEST steer is delivered after the tool batch:
    tool t = WHEN run:
        agent.steer("change plan")         // typed while the tool runs
        RETURN "r"
    provider = FakeProvider(reply that calls t, then DONE)
    agent = Agent with tool t and provider
    WAIT for agent.prompt("go")
    CHECK model call 1 did NOT see "change plan"
    CHECK model call 2 ends with "change plan", right after a ToolResultMessage
    CHECK nothing is queued
```

Real code: [packages/simp_agent/tests/test_queues_compaction.py](../../packages/simp_agent/tests/test_queues_compaction.py) (`test_steer_delivered_after_tool_batch`)

The tool itself calls `steer`, as a user typing during the tool would. The checks: the first model call did not see it (it was typed later); the second call has it as the last user message, **right after the tool result**, so the history is valid; and the queue is empty after.

Follow-ups in both modes:

```text
TEST follow-ups in both modes:
    FOR EACH (mode, expected calls) in ("one-at-a-time", 3), ("all", 2):
        provider = FakeProvider(DONE, DONE, DONE)
        agent = Agent with no tools and provider
        agent.follow_up_mode = mode
        agent.follow_up("f1")
        agent.follow_up("f2")
        WAIT for agent.prompt("go")
        CHECK number of model calls == expected calls
        CHECK the last call ends with "f1", "f2"
        CHECK nothing is queued
```

Real code: [packages/simp_agent/tests/test_queues_compaction.py](../../packages/simp_agent/tests/test_queues_compaction.py) (`test_follow_up_one_at_a_time_and_all`)

Two follow-ups are queued before the prompt. In `"one-at-a-time"` mode the model is called three times: for `go`, then `f1`, then `f2`. In `"all"` mode it is called twice: for `go`, then `f1` and `f2` together. In both cases the last call has both messages in history, and nothing is left in the queue. Note that the follow-ups did **not** go with the prompt: they waited until the model answered `go`.

`test_steer_during_compaction_same_turn` checks read point 2. The fake summary call (the slow `prepare_next_turn` of [16](16-compaction.md)) calls `steer("late")`. The test asserts there are only two model calls and the second already ends with `"late"`: the steer joined the same turn instead of making a new one.

```bash
uv run pytest packages/simp_agent/tests/test_queues_compaction.py
```

## Why this way

> **Two queues, because there are two needs.** "Change what you are doing" must arrive soon; "then do this" must wait. One inbox cannot do both.
>
> **Deliver only at safe points.** Steering is read before a model call and after a full tool batch, never in the middle. So every tool call keeps its result and the history stays valid. It also means steer never kills work; that is abort's job ([06](06-events-abort.md)).
>
> **The loop asks; the caller keeps.** `agent_loop` only calls `get_steering()` / `get_follow_up()`. It has no queue state. `Agent` keeps simple lists; other hosts can keep them anywhere.
>
> **All in one run.** Queued messages extend the current run instead of starting a new one, so there is one `agent_start` and one `agent_end`, and `prompt()` stays one-at-a-time.

## Exercises

1. Call `agent.steer("s1")` **before** `agent.prompt("go")`, with a `FakeProvider` of two `DONE` replies. How many model calls happen? Which user messages does the first call see?
2. Queue `agent.follow_up("later")`, then prompt with a `FakeProvider` whose first reply has `stop_reason="error"`. Is `"later"` still queued (`has_queued()`)? Prompt again and check when it is sent.

## Recap

- [Steer](glossary.md#steer) = deliver soon. [Follow-up](glossary.md#follow-up) = deliver when the agent would stop.
- `LoopConfig` has two hooks, `get_steering` and `get_follow_up`. The loop calls them; it keeps no queue itself.
- The inner loop runs while there are tool calls **or** steering; the outer loop asks for follow-ups when the inner loop ends.
- Steering is read before the first turn, just before each model call (after `prepare_next_turn`), and after each tool batch. It never cuts a tool batch.
- On error or abort the queues are not read, so messages survive for the next `prompt()` (or `clear_queues()`).
- `Agent.steer` / `follow_up` append to lists; `_take` takes one message (`"one-at-a-time"`) or all (`"all"`) per read.

**Builds on:** [06 Events and abort](06-events-abort.md) · **Next:** [08 Hooks and approval](08-hooks-approval.md) — `before_tool_call` and `after_tool_call`, so a caller can check, deny or change a tool call.
