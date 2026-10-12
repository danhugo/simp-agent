# 01 Part 1 · Messages

> Skeleton only. Prose not written yet.

**Goal:** Define the message types every other part passes around.

**Builds on:** [00-overview](00-overview.md) · **Next:** [02-fake-provider](02-fake-provider.md)

## Planned sections

- Message types (user, assistant, tool result)
- to_dict / from_dict
- Forward link: CompactionEntry (ch 16)

## Code it covers

- `packages/simp_agent/src/simp_agent/ai/__init__.py`

## Test it will show

- `packages/simp_agent/tests/test_core.py (round-trip to_dict/from_dict)`
