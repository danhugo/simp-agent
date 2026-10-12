# 22 Part 5 · Store and auth

> Skeleton only. Prose not written yet.

**Goal:** Save users, sessions and events durably.

**Builds on:** [21-transport](21-transport.md) · **Next:** [23-limits](23-limits.md)

## Planned sections

- SqliteStore
- scrypt passwords
- Token hashes
- Durable events
- recover

## Code it covers

- `apps/server/src/simp_server/store.py`
- `apps/server/src/simp_server/server.py`

## Test it will show

- `apps/server/tests/test_store.py, test_accounts.py`
