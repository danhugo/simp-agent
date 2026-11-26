---
name: sql-helper
label: SQL helper
description: "Write, explain, debug and optimize SQL (PostgreSQL, MySQL, SQLite, SQL Server, BigQuery); design schemas; query CSV/Excel files with SQLite. Use for any SQL or database question."
license: MIT
source: simp
version: 1
---

# SQL Helper

## Ask/decide first

Which **dialect** (Postgres, MySQL, SQLite, SQL Server, BigQuery, Oracle)? Table and column names (ask for `CREATE TABLE` or a sample)? If unknown, state assumptions and use standard SQL.

## Write queries well

- Explicit columns, not `SELECT *` in production code.
- CTEs (`WITH`) for readable multi-step logic; one step per CTE with a clear name.
- Explicit `JOIN ... ON`; say why LEFT vs INNER. Check join cardinality (row count before/after).
- Aggregates: every non-aggregated column in `GROUP BY`; filter groups with `HAVING`.
- Window functions for running totals, ranks, previous values: `SUM(x) OVER (PARTITION BY a ORDER BY d)`, `ROW_NUMBER()`, `LAG()`.
- NULLs: `COALESCE`, `IS NULL` (never `= NULL`); `COUNT(col)` skips NULLs.
- Dates: half-open ranges `d >= '2026-01-01' AND d < '2026-02-01'` (index-friendly, no end-of-day bugs).
- Parameters (`%s`, `?`, `$1`), never string-concatenated user input.
- Format: keywords uppercase, one clause per line, comment the non-obvious.

## Test it for real

Run against SQLite in the sandbox with sample data to check logic (most standard SQL works):
```python
import sqlite3, pandas as pd
con = sqlite3.connect(":memory:")
pd.read_csv("/work/orders.csv").to_sql("orders", con, index=False)
print(pd.read_sql("SELECT status, COUNT(*) n FROM orders GROUP BY status", con))
```
Postgres-only features (e.g. `DISTINCT ON`, `FILTER`, JSONB): note it; test the logic with an equivalent. The same trick answers questions about the user's CSV/Excel files with SQL.

## Debug

Read the exact error and position; check names/quotes (Postgres: `"Col"` is case-sensitive, strings in `'single'`); run CTEs one at a time; compare row counts at each step; look for duplicates from joins.

## Optimize

- Get the plan: `EXPLAIN ANALYZE` (Postgres), `EXPLAIN` (MySQL/SQLite). Look for sequential scans on big tables, bad row estimates, nested loops over many rows, sorts spilling to disk.
- Index columns used in `WHERE`, `JOIN`, `ORDER BY` (composite index: equality columns first, then range). Don't wrap indexed columns in functions (`WHERE date(created_at) = ...` → range).
- Avoid `SELECT DISTINCT` hiding join bugs; replace correlated subqueries with joins or window functions; `EXISTS` over `IN` for big subqueries; paginate with keyset (`WHERE id > last_id`) not large `OFFSET`.

## Schema design

Primary keys on every table; foreign keys with appropriate `ON DELETE`; normalise to 3NF then denormalise deliberately; proper types (`numeric` for money, `timestamptz` for times); `NOT NULL` and `CHECK` constraints; naming: snake_case, plural or singular consistently. Provide the DDL plus a short explanation and sample queries.

## Explaining a query

Walk through it in execution order: FROM/JOIN → WHERE → GROUP BY → HAVING → SELECT → ORDER BY → LIMIT, and say what one output row means.

Be careful with write statements (`UPDATE`, `DELETE`, migrations): show a `SELECT` preview of affected rows first, wrap in a transaction, and suggest a backup.
