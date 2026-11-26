---
name: systematic-debugging
label: Systematic debugging
description: "Find the root cause of any bug, test failure, build error or unexpected behaviour before proposing a fix. Use for any technical problem, especially after a quick fix already failed."
license: MIT (see LICENSE.txt)
source: https://github.com/obra/superpowers/tree/main/skills/systematic-debugging
version: 1
---

# Systematic Debugging

**Iron law: no fixes without root-cause investigation first.** Symptom fixes are failure. Systematic is faster than guess-and-check, even under time pressure, and simple bugs have root causes too.

## Phase 1: Root cause investigation

1. **Read the error completely**: full stack trace, line numbers, file paths, codes. It often contains the answer.
2. **Reproduce reliably** with `bash`: exact command, every time? If not reproducible, gather more data; do not guess.
3. **Check recent changes**: `git diff`, `git log -p -5`, new dependencies, config, environment.
4. **Multi-component systems** (CI → build → deploy, API → service → DB): before fixing, log what enters and exits each boundary, run once, and find WHERE it breaks. Then investigate that component.
5. **Trace data flow backwards** from the bad value to its origin; fix at the source. See this skill's `root-cause-tracing.md`.

## Phase 2: Pattern analysis

- Find similar **working** code in the same codebase (`rg`).
- Read any reference implementation completely; do not skim.
- List every difference between working and broken, however small.
- Note dependencies: config, env vars, versions, assumptions.

## Phase 3: Hypothesis and test

- State one hypothesis: "X is the root cause because Y."
- Test it with the smallest possible change, one variable at a time.
- Wrong? Form a new hypothesis. Do not stack fixes.
- Don't know? Say so, research (`web_search` the exact error message), or ask the user.

## Phase 4: Implement

1. Write a failing test or a one-off repro script first (see the `test-driven-development` skill).
2. One fix for the root cause. No "while I'm here" changes.
3. Verify: the repro passes, other tests still pass, the original symptom is gone. Show the command output.
4. Fix didn't work? Back to Phase 1 with the new information.
5. **3+ failed fixes** = likely a wrong design (each fix reveals a new problem elsewhere). Stop and discuss the architecture with the user before fix #4.

After the fix, consider validating at several layers so the bug class cannot recur: see `defense-in-depth.md`.

## Red flags: stop and return to Phase 1

- "Quick fix for now, investigate later" / "just try changing X"
- several changes at once, then run tests
- "it's probably X" without evidence; proposing fixes before tracing data flow
- "one more attempt" after 2+ failures
- the user says "stop guessing", "is that actually happening?", "we're stuck"

## Truly environmental?

If investigation shows a timing, external or environment cause: document what you checked, add handling (retry, timeout, clear error) and logging. But most "no root cause" cases are incomplete investigation.

## Quick reference

| Phase | Do | Done when |
|---|---|---|
| 1 Root cause | read errors, reproduce, check changes, gather evidence | you know WHAT and WHY |
| 2 Pattern | compare with working examples | differences listed |
| 3 Hypothesis | one theory, minimal test | confirmed or replaced |
| 4 Implement | failing test, single fix, verify | bug gone, tests pass |
