# ADR-0012 — REPEATABLE READ + `pg_export_snapshot` for consistent introspection

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

The Inspector issues ~12 catalog queries (tables, columns, indexes,
constraints, views, matviews, functions, triggers, policies, sequences,
enums, types, extensions). If the schema changes between queries — e.g.
another connection runs a migration — the resulting `Database` aggregate is
inconsistent.

`asyncio.gather`-ing multiple awaits on the **same** connection serializes
them inside psycopg, so true parallelism requires multiple connections.
Multiple connections + naive transactions see different MVCC snapshots.

## Decision

Snapshot consistency is achieved with **REPEATABLE READ** plus
**`pg_export_snapshot()`**:

1. Open connection **C0**, `BEGIN ISOLATION LEVEL REPEATABLE READ`
2. `SELECT pg_export_snapshot()` → `snap_id`
3. Open N additional connections **C1..CN**, each `BEGIN ISOLATION LEVEL
   REPEATABLE READ` then `SET TRANSACTION SNAPSHOT '<snap_id>'`
4. Run each catalog query on its own connection — all N connections share
   one MVCC view
5. `COMMIT` (or `ROLLBACK`, since we only read)

**MVP simplification (deferred via P1-INFRA-07):** start with a single
connection in REPEATABLE READ — queries serialize, but consistency is free.
Switch to the multi-connection variant only if benchmarks show the
single-connection approach is too slow for production-sized schemas
(>10 000 objects).

## Consequences

- **Positive:**
  - True snapshot isolation across all catalog queries
  - Concurrent migrations on other connections cannot corrupt our read
  - Pattern is the same one `pg_dump --jobs` uses — battle-tested
- **Negative:**
  - More connections under load
  - The snapshot ID has a server-side lifetime; failure handling adds
    complexity (mitigated by short read timeouts)
- **Neutral:**
  - Read-only transactions don't conflict with writers in PG MVCC.

## References

- https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-SNAPSHOT-SYNCHRONIZATION
