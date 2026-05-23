# ADR-0004 — `pg_catalog`-only introspection (no `pg_dump`)

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

The Inspector must read a complete schema description from a running
PostgreSQL 18 instance. The two viable strategies are:

1. **Shell out to `pg_dump --schema-only`** and parse the SQL.
2. **Query `pg_catalog`** directly via SQL.

## Decision

We will exclusively use SQL queries against `pg_catalog` views and `pg_*`
system catalogs (`pg_class`, `pg_attribute`, `pg_constraint`, `pg_index`,
`pg_proc`, `pg_trigger`, `pg_policy`, etc.). `pg_dump` is **not** a runtime
dependency.

Canonical SQL fragments (function bodies, view definitions, index defs,
constraint defs, trigger defs) are obtained via `pg_get_*def()` helpers,
which produce text already normalized by PostgreSQL itself.

## Consequences

- **Positive:**
  - No subprocess, no `pg_dump` binary on the host
  - Async fan-out via `asyncio.gather` is natural
  - Stable, versioned catalog views — schema-of-the-schema is itself a contract
  - Easy to test with `testcontainers` (no extra binary in the image)
  - Incremental fetch possible (per object kind)
- **Negative:**
  - We must hand-write 10+ catalog queries and keep them current with PG18
  - Function bodies must be preserved verbatim from `pg_proc.prosrc` — no
    re-parsing (see ADR for function body normalization)
- **Neutral:**
  - Queries live in `src/pgschemadiff/infrastructure/postgres/catalog/*.sql`
    loaded via `importlib.resources`.

## Alternatives considered

- **`pg_dump`** — comprehensive but produces SQL that is version-specific,
  ordering-dependent, and requires a SQL parser (e.g. `pglast`) to round-trip.
  Adds a subprocess dependency that complicates CI.
- **`information_schema`** — portable across RDBMSes but lossy for
  PostgreSQL-specific features (RLS, partition bounds, opclasses, INCLUDE).

## References

- https://www.postgresql.org/docs/18/catalogs.html
