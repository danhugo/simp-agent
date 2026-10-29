# 09 Part 2 · Steering

**Goal:** Let the user add messages while the agent works.

**Builds on:** [08 Events and abort](08-events-abort.md) · **Next:** [10 Hooks and approval](10-hooks-approval.md)

## Where we are

```mermaid
flowchart LR
    ai --> agent["agent ★ steer / follow_up queues (this chapter)"] --> coding --> session --> plugins --> testing
```

Big picture of Part 2: [part-2-agent](06-part-2-agent.md).

## Example: two new wishes during one run

Take the README run from [Part 2](06-part-2-agent.md#example-the-user-asks-about-a-file) again, and follow it in time:

```mermaid
sequenceDiagram
    participant U as User
    participant A as Agent
    participant M as Model
    U->>A: "What is in README.md?"
    A->>M: model call 1
    M-->>A: call read README.md
    Note over A: read README.md runs
    U->>A: steer: "Also read CHANGELOG.md"
    A->>M: model call 2 (sees the steer)
    M-->>A: call read CHANGELOG.md
    A->>M: model call 3
    U->>A: follow-up: "Then write a short summary to NOTES.md"
    M-->>A: answer about both files
    A->>M: model call 4 (sees the follow-up)
    M-->>A: call write NOTES.md
    Note over A: write NOTES.md runs
    A->>M: model call 5
    M-->>A: "Done."
```

![Steer and follow-up on a timeline: when the user types vs. when the model sees it](img/07-steer-timeline.png)

The picture shows the same run on a timeline: time runs left to right, through 5 turns and 11 messages. The steer and the follow-up wait in their queue (the dashed bars) and enter the history only at a safe point. The small squares before each model call show which messages that call sends: orange is the steer, sent from turn 2 on, and purple is the follow-up, sent from turn 4 on.

While `read README.md` runs, the user remembers something and types "Also read CHANGELOG.md". Near the end, they type "Then write a short summary to NOTES.md". This whole chapter is about how these two messages get into the run.

## Problem

In [08](08-events-abort.md) the user got a Stop button, but they do not want to stop. They want to add to the work. And they cannot start a second run: `Agent` allows one [run](glossary.md#run-agent) at a time, and a second `prompt()` raises `RuntimeError` ([08](08-events-abort.md#the-agent-class-state-on-top-of-the-loop)).

The two messages need different times. "Also read CHANGELOG.md" should reach the model **soon**, so the model can change its plan. "Then write a summary" should wait **until the current job is done**. So we give each its own kind of message. A [steer](glossary.md#steer) is delivered as soon as it is safe, in the middle of the run. A [follow-up](glossary.md#follow-up) waits until the agent would stop, then starts more work in the same run.

Why "as soon as it is safe"? [08](08-events-abort.md#starting-point-05s-loop-with-nobody-listening) showed that every tool call must be followed by its tool result, or the vendor returns a 400 error. So we cannot put the user's message into the history at the moment they type it:

```text
assistant: call c1 read README.md
user:      "Also read CHANGELOG.md"     <- WRONG: between the call and its result
tool:      result of c1
```

We must wait until every tool call has its result. We call such a place a [safe point](glossary.md#safe-point):

```text
assistant: call c1 read README.md
tool:      result of c1
user:      "Also read CHANGELOG.md"     <- safe point: c1 has its result
// model call 2 sees the message and calls read CHANGELOG.md
```

Note the cost: the tool that is running still finishes. Steer changes the model's **next** decision; it does not stop work. To stop work, the user presses Stop ([08](08-events-abort.md#abort-one-asyncioevent)).

Code in this chapter (commit `2fc2776`):

- `packages/simp_agent/src/simp_agent/agent/__init__.py`: `LoopConfig.get_steering` / `get_follow_up`, the two `while` loops of `agent_loop`, the steering read in `_llm_turn`, and on `Agent`: `steer`, `follow_up`, `_take`, `clear_queues`, `has_queued`
- `packages/simp_agent/tests/test_queues_compaction.py`: the queue tests

## Starting point: 06's `Agent` and loop

So where can "Also read CHANGELOG.md" go today? We start from what [08](08-events-abort.md) ended with. `Agent._run` refuses a second run while one is going, and `agent_loop` reads the user's messages only once, at the start: it sends `agent_start`, adds the prompts (the only place user messages come in), runs one turn per pass while the model asks for tools (model call, tool calls, abort exit), and sends `agent_end`.

So with 06's code the message has nowhere to go. The easy patch is to keep the text in `Agent` and call `prompt()` again when the run ends. That keeps the history valid, but it comes **too late**: the model has already answered about README.md alone. It also keeps **one place for two needs**: the urgent steer and the "later" follow-up wait together, so the agent cannot treat them differently. Everything waiting goes out together, so there is **no choice of batch size**, but sometimes the user wants each message handled as its own task. And each delivery is a new run, with a new `agent_start` and `agent_end` [event](glossary.md#event), so a UI that shows "busy" until `agent_end` gives **a flickering UI**.

## Step by step: grow the loop

How do we fix all of this without a second run? Four small steps.

**Step 1: two queues.** `Agent` keeps two lists, `steering` and `follow_ups`. The UI picks one by calling `steer(text)` or `follow_up(text)`. This fixes "one place for two needs".

**Step 2: read steering inside the run.** Instead of waiting for the run to end, the loop asks "is a steer waiting?" at every safe point, so "Also read CHANGELOG.md" reaches model call 2. This fixes "too late".

**Step 3: follow-ups extend the same run.** When the agent would stop, the loop asks "is a follow-up waiting?". If yes, it adds the message and goes on. There is only one `agent_start` and one `agent_end`. This fixes "a flickering UI".

**Step 4: take one message, or all.** Each read takes either the oldest waiting message only, or all of them. This fixes "no choice of batch size".

## Real design

### The loop from 05, with two new places

Where in the loop do steps 2 and 3 go? Here is `agent_loop` from [07](07-agent-loop.md#agent_loop-the-loop), with the events of [08](08-events-abort.md#how-the-loop-sends-them). The block numbers are the ones of the [Part 2 map](06-part-2-agent.md#the-blocks). Only the lines marked `NEW` are new; the hook calls and abort exits are cut.

Two names first. `pending` is the list of user messages the loop has just taken from a queue and will add at the top of the next turn. `has_calls` says "the last reply asked for tools". The loop sets it to true before the first turn, because there is no reply yet and the first turn must run.

1. Send `agent_start` (block 1) and add the prompts.
2. **NEW, steering read (1):** `pending = config.get_steering()`, for steers typed before the run. Set `has_calls` to true.
3. **NEW, outer loop (for follow-ups), forever:**
   1. Inner loop, one pass = one turn, while `has_calls` or `pending` is not empty:
      send `turn_start`; add every message in `pending` and empty it (block 2, take steering); wait for `_llm_turn` (blocks 3 + 4: build the view, call the model) and add its reply `msg`; check the reply and run the tools (blocks 5-8); send `turn_end` with `msg`; set `has_calls` to "msg asked for tools"; then **NEW, steering read (3):** `pending = config.get_steering()` (block 9, safe point).
   2. **NEW, follow-up read (block 9):** `pending = config.get_follow_up()`. If it is empty, stop.
4. Send `agent_end` with the new messages and return them.

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`agent_loop`)

The **steering read (3)** sits at the end of each turn, after all the tools of that reply have run. There every tool call has its result, so it is a safe point. The inner loop goes on while the model asked for tools **or** a steer is waiting, so a steer can even start a new turn when the model was done.

The **follow-up read** sits outside the inner loop. The inner loop ends only when the agent would stop, so only then does the loop ask for follow-ups; reading them earlier would cut into the current job. If one is waiting, `pending` is not empty and the inner loop starts again. If not, the run ends.

There is one more, small steering read (2) inside block 3, in `_llm_turn`. Before each model call, the `prepare_next_turn` hook builds the `view`, the list of messages the model will see ([07](07-agent-loop.md#_llm_turn-one-model-call)). That hook can be slow: compaction runs there and makes its own model call ([20](20-compaction.md)). A steer typed during it should join this turn, not wait for the next. So `_llm_turn` first makes `view` a copy of what `prepare_next_turn(messages)` returned, then calls `config.get_steering()` (steering read 2) and adds each message twice: into the history, and into this turn's `view`, which was built before the read.

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`_llm_turn`)

Here are the two loops as one picture. The three steering reads have the same labels as above: (1) before the run, (2) inside `_llm_turn`, (3) at the end of each turn.

```mermaid
flowchart TD
    S["agent_start"] --> P["add(prompts)"]
    P --> R1["steering read (1)<br/>pending = get_steering()"]
    R1 --> TS
    subgraph INNER["inner loop: one pass = one turn"]
        TS["turn_start"] --> AP["add(pending)"]
        AP --> LT["_llm_turn<br/>steering read (2), then the model call"]
        LT --> TL["tools (blocks 5-8)"]
        TL --> TE["turn_end"]
        TE --> R3["steering read (3)<br/>pending = get_steering()"]
        R3 --> Q1{"has_calls OR pending?"}
        Q1 -- yes --> TS
    end
    Q1 -- no --> FU
    subgraph OUTER["outer loop: follow-ups"]
        FU["follow-up read<br/>pending = get_follow_up()"] --> Q2{"follow-up waiting?"}
    end
    Q2 -- "yes: back into the inner loop" --> TS
    Q2 -- no --> E["agent_end"]
```

The [timeline picture](#example-two-new-wishes-during-one-run) shows the path of "Also read CHANGELOG.md" from the keyboard to model call 2.

### Where `get_steering` gets its messages

`steer()` only wraps the text in a `UserMessage`, appends it to `Agent.steering` and returns at once; it never cuts the running tool and never waits for the loop. The queue lives in `Agent`, not in the loop. The loop only gets two **functions** through `LoopConfig` ([07](07-agent-loop.md#loopconfig-the-settings)): `get_steering` and `get_follow_up` (both return an empty list by default). `Agent._run` sets them to "take from my list", using `_take` and the queue mode (next part). Because they are functions, each call looks at the list as it is **now**, so a `steer()` in the middle of the run is seen at the next read.

### The `Agent` side: two lists and a mode

What does `Agent` ([08](08-events-abort.md#the-agent-class-state-on-top-of-the-loop)) keep behind these hooks?

Two lists, `steering` and `follow_ups`, both empty at the start, and two modes, `steering_mode` and `follow_up_mode`, both `"one-at-a-time"` by default (the other value is `"all"`). Then five small methods:

1. `steer(text)` adds `UserMessage(text)` to `steering`.
2. `follow_up(text)` adds `UserMessage(text)` to `follow_ups`.
3. `clear_queues()` empties both lists.
4. `has_queued()` returns true if either list is not empty.
5. `_take(queue, mode)` takes the first n messages (all of them in `"all"` mode, else at most 1), removes them from the queue so a message is never sent twice, and returns them.

Real code: [packages/simp_agent/src/simp_agent/agent/__init__.py](../../packages/simp_agent/src/simp_agent/agent/__init__.py) (`Agent.steer`, `follow_up`, `clear_queues`, `has_queued`, `_take`)

`steer` and `follow_up` are plain sync methods, like `abort`. They only append to a list, so a key handler can call them at any time. `has_queued` lets a UI show "2 messages waiting".

The [queue mode](glossary.md#queue-mode) decides how many messages one read takes. Why have a choice? Say the user types three steers quickly while `read README.md` runs: "Also read CHANGELOG.md", "and LICENSE", "skip the tests folder". With `"one-at-a-time"` (the default), the read at the end of turn 1 takes only the first one. Turn 2 sees "Also read CHANGELOG.md"; the next read takes "and LICENSE" for turn 3, and so on. Each message gets its own turn, so the model handles each as its own task. With `"all"`, the read takes all three, and turn 2 sees them together. That is fewer model calls, and better when the messages are parts of one wish.

Higher layers only pass text down. The session ([17](17-session.md)) has its own `steer` and `follow_up` that call the `Agent` ones, and the CLI ([24](24-cli.md)) and the server ([25](25-server-run.md)) call the session.

### Errors and abort leave the queues alone

What if the run ends early? If a turn ends with `error` or `aborted`, `agent_loop` returns at once ([08](08-events-abort.md#abort-one-asyncioevent)), before the steering read and the follow-up read. So waiting messages stay in the queues. The `Agent` docstring says:

> Queued messages survive abort(); they wait for the next prompt() or clear_queues().

This is on purpose. The user pressed Stop, not "throw away what I typed". The next `prompt()` reads the steering queue right after its prompt, so a waiting steer goes out with the new prompt. If the UI wants the messages gone, it calls `clear_queues()`.

**Builds on:** [08 Events and abort](08-events-abort.md) · **Next:** [10 Hooks and approval](10-hooks-approval.md): `before_tool_call` and `after_tool_call`, so a caller can check, deny or change a tool call.
