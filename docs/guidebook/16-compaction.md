# 16 Part 4 · Compaction

> Skeleton only. Prose not written yet.

**Goal:** Keep long conversations inside the context window.

**Builds on:** [15-retry](15-retry.md) · **Next:** [17-overflow](17-overflow.md)

## Planned sections

- estimate_tokens / should_compact
- find_cut
- serialize_conversation
- Incremental summarize
- File tracking
- build_view and CompactionEntry

## Code it covers

- `packages/simp_agent/src/simp_agent/agent/compaction.py`
- `packages/simp_agent/src/simp_agent/session/__init__.py`

## Test it will show

- `packages/simp_agent/tests/test_compaction_serialize.py, test_queues_compaction.py`
