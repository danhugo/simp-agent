# 23 Part 5 · Limits

> Skeleton only. Prose not written yet.

**Goal:** Stop runaway cost and free idle resources.

**Builds on:** [22-store-auth](22-store-auth.md) · **Next:** [24-docker-sandbox](24-docker-sandbox.md)

## Planned sections

- Budget guard
- Kill switch (pause/resume)
- Idle release

## Code it covers

- `apps/server/src/simp_server/budget.py`
- `apps/server/src/simp_server/server.py`

## Test it will show

- `apps/server/tests/test_budget.py, test_lifecycle.py`
