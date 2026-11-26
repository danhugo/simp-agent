---
name: git-workflow
label: Git workflow
description: "Use git safely: clone, branch, commit with good messages, rebase/merge, resolve conflicts, undo mistakes, inspect history, prepare pull requests (via the GitHub portal). Use for any git or version-control question."
license: MIT
source: simp
version: 1
---

# Git Workflow

## Safety rules

- Check state before acting: `git status`, `git branch -vv`, `git log --oneline -10`.
- Never force-push, `reset --hard`, delete branches, or rewrite pushed history without the user's explicit OK. Prefer `git push --force-with-lease` if they agree.
- Never commit secrets (`.env`, keys, tokens); check `git diff --cached` before committing.
- Work on a branch, not directly on `main`/`master`, unless the user says otherwise.
- Pushing needs credentials; the sandbox may not have them. For GitHub, use the GitHub portal (if connected) to create branches, commits or PRs, or give the user the commands to run.

## Everyday flow

```bash
git switch -c feat/short-name             # new branch
git add -p                                # stage hunks deliberately
git commit -m "feat: add CSV export to reports"
git fetch origin && git rebase origin/main   # update branch (or merge if the team prefers)
```

**Commit messages:** imperative subject ≤ 72 chars ("fix: handle empty invoice list"), blank line, body explaining *why*. Conventional prefixes if the repo uses them (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`). One logical change per commit.

## Conflicts

1. `git status` lists conflicted files. Open each; understand both sides (`git log --oneline --left-right HEAD...MERGE_HEAD -- file`).
2. Edit to the correct combined result; remove markers; run tests.
3. `git add file` → `git rebase --continue` (or `git commit` for a merge). Bail out: `git rebase --abort` / `git merge --abort`.

## Undo cheatsheet

| Situation | Command |
|---|---|
| Unstage a file | `git restore --staged f` |
| Discard local edits to a file | `git restore f` (destructive: confirm) |
| Fix last commit message / add forgotten file | `git commit --amend` (only if not pushed) |
| Undo last commit, keep changes | `git reset --soft HEAD~1` |
| Revert a pushed commit | `git revert <sha>` |
| Recover "lost" commits | `git reflog`, then `git switch -c rescue <sha>` |
| Stash work | `git stash push -m msg` / `git stash pop` |

## Investigate

- Who/when changed a line: `git blame -L 40,60 f`; when a string appeared: `git log -S 'text' --oneline`.
- Find the commit that broke something: `git bisect start; git bisect bad; git bisect good <sha>`; then `git bisect run <test cmd>`.
- Compare branches: `git log --oneline main..feat`, `git diff main...feat --stat`.

## Pull requests

Title like a commit subject; body: what and why, how tested, screenshots/notes, linked issue. Keep PRs small. Create it through the GitHub portal if connected, otherwise give the user the text.

## .gitignore

Add build outputs, dependencies (`node_modules/`, `.venv/`), OS files, secrets. Already-tracked file? `git rm --cached f` then commit.
