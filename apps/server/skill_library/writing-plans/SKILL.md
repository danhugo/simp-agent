---
name: writing-plans
label: Writing plans
description: "Turn a spec or goal into a concrete step-by-step implementation plan (files, tasks, tests, checks) before starting multi-step work, in code or in any project."
license: MIT (see LICENSE.txt)
source: https://github.com/obra/superpowers/tree/main/skills/writing-plans
version: 1
---

# Writing Plans

Write the plan for someone who has not seen the project or the spec. They are competent; what they cannot know is what **you decided**: which files, names and signatures, which values from the spec, which tests or checks prove each step. Write those down. Bite-sized tasks. DRY, YAGNI, test first, frequent commits.

Save to `/work/plans/YYYY-MM-DD-<topic>.md` unless the user prefers another place.

## Scope check

If the request covers several independent parts, propose one plan per part. Each plan should produce something that works and can be tested on its own.

## Map the files (code) or deliverables (non-code) first

- One clear responsibility per file; small focused files; files that change together live together.
- In an existing project, follow its patterns (read the code with `rg` first). Don't restructure unasked.

## Task size

A task is the smallest unit with its own test/check that a reviewer could accept or reject on its own. Fold setup, config and docs into the task that needs them.

Each **step** is one action with a checkable result: write the failing test → run it, see it fail → implement → run, see it pass → commit.

## Plan template

```markdown
# <Feature> Plan

**Goal:** one sentence.
**Approach:** 2–3 sentences.
**Tech:** languages, libraries, versions.

## Files
- Create: `src/x.py` — does A
- Modify: `src/y.py:120-150` — adds B

### Task 1: <name>
**Files:** ...
- [ ] Write failing test `tests/test_x.py::test_a` (show the test code)
- [ ] Run `pytest tests/test_x.py -x` → expect FAIL "..."
- [ ] Implement `def a(...) -> ...` (show signature and key logic)
- [ ] Run tests → expect PASS
- [ ] Commit "feat: a"
```

Give exact paths, exact commands with expected output, and real code for anything non-obvious. No "TBD", no "handle errors appropriately": say which errors and how.

## Self-review (do it yourself before showing the plan)

1. **Coverage:** every requirement in the spec maps to a task.
2. **No placeholders.**
3. **Consistency:** names, types and signatures match across tasks.
4. **Order:** each task only depends on earlier ones.

Fix problems inline, then show the user a short summary and the plan path, and ask whether to start. When executing, tick the checkboxes in the file as you go and stop to ask if reality contradicts the plan.

## Non-code plans

Same idea for events, studies, migrations, launches: deliverables instead of files, a "done when" check instead of a test, owners and dates if people are involved.
