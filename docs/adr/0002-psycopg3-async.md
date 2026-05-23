# ADR-0002 — Use psycopg 3 (async) as the PostgreSQL driver

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

We need an async PostgreSQL driver to introspect `pg_catalog` concurrently
and to apply migrations. The two viable choices are **psycopg 3** (with its
`AsyncConnection` API) and **asyncpg**.

## Decision

We will use **psycopg 3** (`psycopg[binary,pool]>=3.2`) for all PostgreSQL
interaction. The connection pool is `psycopg_pool.AsyncConnectionPool`.

## Consequences

- **Positive:**
  - First-class type adaptation (`format_type`, custom types, composite types)
  - Same API surface for sync and async — simpler test fixtures
  - Server-side cursors and COPY supported natively
  - Long-term maintained by the PostgreSQL project committers
  - Pool implementation is in the same project (no API mismatch)
- **Negative:**
  - Marginally slower than asyncpg on simple query benchmarks (acceptable —
    introspection is dominated by query planning, not driver overhead)
- **Neutral:**
  - Binary wheel via `psycopg[binary]` removes the need for `libpq-dev`.

## Alternatives considered

- **asyncpg** — fastest pure-async driver, but its protocol implementation
  diverges from `libpq`, leading to occasional quirks with newer PG features.
  Its type system is also less amenable to Pydantic mapping.

## References

- https://www.psycopg.org/psycopg3/docs/
