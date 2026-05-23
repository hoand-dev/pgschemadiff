# ADR-0010 — Session-scoped Postgres container, per-test database

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

Integration tests need a real PostgreSQL 18 instance. Three strategies:

1. **Container per test function** — perfect isolation; ~3s startup × 200
   tests = 10 min overhead.
2. **Container per session + transaction rollback per test** — fast, but
   DDL in PostgreSQL is not 100% rollback-clean (sequence ownership,
   `CREATE INDEX CONCURRENTLY`, etc.); flaky.
3. **Container per session + per-test temporary database** — one container
   start, fast `CREATE DATABASE` per test, atomic drop on teardown.

## Decision

We use strategy **(3)**: one session-scoped `postgres:18-alpine` container,
plus a per-test fixture that runs `CREATE DATABASE test_<uuid>` and
`DROP DATABASE ... WITH (FORCE)` in teardown.

## Consequences

- **Positive:**
  - ~3s container start amortized across the whole suite
  - Each test sees a virgin database — full DDL isolation
  - `DROP DATABASE WITH (FORCE)` is atomic in PG18
- **Negative:**
  - Slower than transaction rollback (each `CREATE DATABASE` is ~100 ms)
  - Requires Docker on developer machines and CI
- **Neutral:**
  - The fixture is defined in `tests/integration/conftest.py`.

## References

- https://www.postgresql.org/docs/18/sql-dropdatabase.html
- See P1-TEST-01.
