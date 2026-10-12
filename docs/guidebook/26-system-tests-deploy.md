# 26 Part 5 · System tests and deploy

> Skeleton only. Prose not written yet.

**Goal:** Test the whole system and run it on one machine.

**Builds on:** [25-web-client](25-web-client.md) · **Next:** [27-limits-choices-extend](27-limits-choices-extend.md)

## Planned sections

- fake.py / fakellm.py
- End-to-end tests
- ops backup
- launchd

## Code it covers

- `apps/server/src/simp_server/fake.py`
- `apps/server/src/simp_server/fakellm.py`
- `apps/server/src/simp_server/ops.py`
- `apps/web/e2e/`
- `deploy/launchd/`

## Test it will show

- `make e2e; apps/server/tests/test_ops.py`
