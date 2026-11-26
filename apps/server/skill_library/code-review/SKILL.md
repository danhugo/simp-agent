---
name: code-review
label: Code review
description: "Review code changes (a diff, branch, PR or files) for bugs, security, design and tests, with prioritized findings; and handle review feedback received on your own code rigorously."
license: MIT (see LICENSE.txt)
source: https://github.com/obra/superpowers/tree/main/skills/requesting-code-review
version: 1
---

# Code Review

Adapted from superpowers' requesting-code-review and receiving-code-review.

## Getting the change

- Local repo in `/work`: `git diff --stat BASE..HEAD`, `git diff BASE..HEAD` (BASE usually `origin/main` or the merge base: `git merge-base HEAD origin/main`).
- GitHub PR: use the GitHub portal (if connected) to read the PR, its diff and comments; or `git fetch origin pull/<n>/head:pr-<n>` if the repo is cloned.
- Read the surrounding code too, not just the diff (`rg` the changed functions' callers).

Review is **read-only**: don't modify the working tree unless asked to fix.

## What to check

- **Requirements:** does it do what the issue/spec/PR description says? Anything missing? Where the spec is silent, judge by what a reasonable user would expect.
- **Correctness:** logic errors, off-by-one, null/empty cases, error handling, concurrency, resource leaks, wrong assumptions about inputs.
- **Security:** injection (SQL, shell, HTML), secrets in code, authz checks, unsafe deserialization, path traversal (see `security-best-practices` skill for depth).
- **Design:** clear responsibilities, fits existing patterns, no speculative abstraction, no duplicated code.
- **Tests:** test real behaviour, cover edge cases, would fail if the code broke. Run them if possible and report the result.
- **Production:** migrations, backwards compatibility, performance on realistic sizes, logging.

## Report format

```markdown
**Verdict:** Ready to merge / Needs changes / Needs discussion

**Strengths:** 1–3 specific points.

**Critical** (bugs, security, data loss: must fix)
1. `path/file.py:42` — what is wrong, why it matters, suggested fix.
**Important** (should fix before merge)
**Minor** (nice to have; style only if it hurts readability)

**Set aside:** things you considered out of scope, one line each with reason.
```

Every finding has a file:line, a concrete reason and a fix. Don't pad with style nits; don't claim a bug you didn't verify (say "possible" and why).

## Receiving review feedback

1. Read all of it. Restate each item technically, or ask about unclear items **before implementing anything** (items may be related).
2. Verify each claim against the code. Is it right for *this* codebase?
3. Respond with technical acknowledgment or reasoned pushback. No performative "Great point!" / "You're absolutely right!": just fix it or explain.
4. Implement one item at a time; test each.
5. Feedback from the user: trusted, implement once understood. From external reviewers: verify; push back with evidence if it would break things or violate YAGNI ("this endpoint has no callers; remove instead?").
