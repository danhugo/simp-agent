# 17 Part 4 · Context overflow

> Skeleton only. Prose not written yet.

**Goal:** Recover when the model says the context is too big.

**Builds on:** [16-compaction](16-compaction.md) · **Next:** [18-profiles-plugins](18-profiles-plugins.md)

## Planned sections

- Detecting overflow (is_context_overflow)
- Compact and retry

## Code it covers

- `packages/simp_agent/src/simp_agent/session/__init__.py`

## Test it will show

- `packages/simp_agent/tests/test_session.py (overflow recovery)`
