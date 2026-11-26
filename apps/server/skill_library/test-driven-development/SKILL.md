---
name: test-driven-development
label: Test-driven development
description: "Write tests first (red, green, refactor) when adding a feature or fixing a bug in code; also how to write good tests for existing code."
license: MIT (see LICENSE.txt)
source: https://github.com/obra/superpowers/tree/main/skills/test-driven-development
version: 1
---

# Test-Driven Development

Write the test first. Watch it fail. Write the minimal code to pass. If you never saw the test fail, you don't know it tests the right thing.

Use for new features, bug fixes, refactors and behaviour changes. Skip only for throwaway prototypes, generated code or config, and say so.

## Red, green, refactor

1. **RED: one failing test** for one behaviour, with a clear name, using real code (mocks only when unavoidable: network, clock, paid APIs).
   ```python
   def test_retries_failed_operation_three_times():
       attempts = []
       def op():
           attempts.append(1)
           if len(attempts) < 3: raise RuntimeError("fail")
           return "ok"
       assert retry(op) == "ok"
       assert len(attempts) == 3
   ```
   Bad: `test_retry_works` that only asserts a mock was called 3 times.
2. **Verify RED** with `bash` (`pytest path::test -x`, `npm test -- file`). It must *fail* (not error) for the expected reason: the feature is missing. Passes already? You're testing existing behaviour; fix the test. Errors? Fix the error and re-run.
3. **GREEN: simplest code that passes.** No extra options, no "improvements" (YAGNI).
4. **Verify GREEN:** the new test and the whole suite pass; output is clean (no new warnings).
5. **REFACTOR** only while green: remove duplication, improve names; re-run tests after each change.
6. Next behaviour: back to RED.

Code written before its test? Delete it and re-implement from the test; don't "adapt" it.

## Bug fixes

First write a test that reproduces the bug and fails. Then fix. The test stays as a regression guard.

## No test framework yet?

Python: `pytest` (`pip install pytest` if missing) with `tests/test_*.py`. Node: `node --test` (built in). Otherwise a small script with `assert` that exits non-zero on failure.

## Rationalizations to reject

| Excuse | Reality |
|---|---|
| "Too simple to test" | Simple code breaks too; the test takes 30 seconds. |
| "I'll test after" | Tests written after pass immediately and prove nothing. |
| "Manual check is enough" | It isn't repeatable and won't catch regressions. |
| "Deleting my code is wasteful" | Sunk cost; untested code is the real waste. |

## Writing good tests

See this skill's `writing-good-tests.md`: test behaviour not implementation, your code not the framework, one reason to fail per test, names that describe the behaviour.

## Done checklist

- every new function/behaviour has a test that you saw fail first;
- minimal code; all tests pass with pristine output;
- edge cases and errors covered;
- report the test command and its output to the user.
