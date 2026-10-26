# P5-BENCH-01 — Benchmark suite (10k objects) design

**Status:** Approved by reviewer; implementation complete (CI `de0c099`).
**Date:** 2026-10-26
**Task:** `docs/TASKS.md` P5-BENCH-01 · roadmap row "P5-BENCH-01 10k benchmark"
**Plan:** `docs/plans/2026-10-26-p5-bench-01-implementation-plan.md`

## Goal

Measure the compare-and-generate pipeline on a schema with at least 10,000
catalog objects and hold it under **10 seconds end to end** (inspect source +
inspect target + diff + order + assess + generate + render) on the CI
`ubuntu-24.04` runner. Profile before optimizing: this task adds measurement
only. Any optimization is a separate, reviewer-approved follow-up.

## Non-goals

- No production code changes. If the budget is missed, report the hotspot with
  numbers and stop.
- No apply benchmark (apply time is dominated by PostgreSQL DDL, not this tool).
- No TUI benchmark, no memory benchmark, no historical trend storage.
- No new dependencies (`pytest-benchmark` is already in the `dev` extra).

## Definitions

- **Object:** one entry the inspector returns in a `Database` snapshot: schema
  member tables, columns, constraints, indexes, sequences, views, materialized
  views, functions, procedures, triggers, policies, enum/composite/domain types.
  Counted by walking the snapshot (`count_objects(database) -> int`), never by
  the generator's intent. Extensions and schemas themselves are not counted.
- **Workload:** one frozen dataclass, `BenchWorkload`, that both builders read,
  so the in-memory and end-to-end benchmarks describe the same shape.

## Workload shape

`BenchWorkload` (defaults chosen so the source snapshot holds >= 10,000 objects):

| Field | Default | Meaning |
|---|---|---|
| `schema` | `"bench"` | single schema, inspected with `schemas=["bench"]` |
| `tables` | 800 | tables `t0000…` |
| `columns_per_table` | 10 | `id bigint` + 9 typed columns (int, text, timestamptz, numeric, boolean mix) |
| per table | — | primary key on `id`, one secondary btree index, one `CHECK` constraint |
| `views` | 80 | simple views over one table each |
| `functions` | 80 | `LANGUAGE sql` functions |
| `sequences` | 80 | standalone sequences (not owned) |

The change set (target is the "current" database, source is "desired"; the
migration makes target look like source) is about 10% of objects and is spread
across kinds so every pipeline stage does real work:

| Change | Count | Expected delta |
|---|---|---|
| tables only in source | 40 | `CreateTable` (+ its index/constraints) |
| tables only in target | 40 | `DropTable` (DESTRUCTIVE) |
| added column | 200 | `AddColumn` |
| widened column `integer → bigint` | 100 | `AlterColumnType` |
| secondary index changed (different column) | 100 | index replace/drop+create |
| view body changed | 20 | `ReplaceView` |
| function body changed | 20 | `ReplaceFunction` |

Every delta in the workload must classify at or below `DESTRUCTIVE`;
`generate_migration` is called with `max_risk=RiskLevel.DESTRUCTIVE`. If any
delta classifies `BLOCKED`, change the workload, not the classifier.

## Benchmarks

### B1 — in-memory pipeline (no database)

- Builds source and target `Database` snapshots directly from domain models.
- Feeds them through the **real** use case: a fake `SchemaInspector` whose
  `inspect()` returns the prepared snapshot → `compare_schemas_with_snapshots`
  → `generate_migration(max_risk=DESTRUCTIVE)` → `render_bundle`.
- Uses `benchmark.pedantic(..., rounds=3, iterations=1)`; asserts each round
  < 10 s (regression tripwire, generous on purpose).
- Asserts `count_objects(source) >= 10_000` and that the delta count falls in
  an expected window derived from the workload, so the fixture cannot silently
  shrink or the diff silently go empty.
- Marked `@pytest.mark.benchmark`; not `integration`. It therefore also runs in
  the local gate (`-m "not integration"`): it must finish in about 10 s locally.

### B2 — end to end (PostgreSQL 18, CI only)

- Marked `benchmark` and `integration`.
- Reuses the Testcontainers fixtures from `tests/integration/conftest.py`
  (`postgres_container`, `pg_admin_dsn`, `pg_test_dsn`, `pg_test_dsn2`) by
  importing them into `tests/benchmark/conftest.py`. `pytest_plugins` is not
  allowed in a non-root conftest, so re-export by import. No duplicated
  container logic.
- Seeds each database server-side with one generated SQL script per database
  (a `DO $$ … $$` block with loops / `generate_series`), not 10k client round
  trips. Seeding is excluded from the timed span.
- Times the span with a timing proxy around each real `PgCatalogInspector`
  (implements `SchemaInspector.inspect`) passed into
  `compare_schemas_with_snapshots`, so the breakdown is: `inspect_source`,
  `inspect_target`, `diff_and_order` (compare total minus both inspects),
  `generate` (assess + emit + group), `render`. Prints one line:
  `bench e2e objects=… deltas=… inspect_source=…s inspect_target=…s diff_and_order=…s generate=…s render=…s total=…s`.
- Asserts `total < 10.0` and the same object-count / delta-window checks as B1.
- Pools are opened with `composition.open_inspectors` so the production
  connection path is measured.

### Shared code

`tests/benchmark/workload.py`: `BenchWorkload`, `count_objects`,
`build_snapshots(workload) -> (source, target)`, `seed_sql(workload, side) -> str`.
A small unit test (`tests/benchmark/test_workload.py`, unmarked, fast) checks
`count_objects` on a tiny workload and that `seed_sql` for `side="source"` and
`side="target"` differ only by the configured changes (e.g. by counting
`CREATE TABLE` statements).

## Safety

- Seeding SQL is test-only and runs only on the Testcontainers database. Use
  `CURRENT_USER` wherever a role is needed; never a literal role name.
- Identifiers are generated from fixed patterns (`t0000`, `v0000`, …); no
  user input reaches SQL.
- Nothing runs against any other PostgreSQL server.

## CI

New job `benchmark` in `.github/workflows/ci.yml`, same setup as
`integration-test`, running:

```
uv run pytest tests/benchmark -m benchmark -v --benchmark-columns=min,mean,max
```

No coverage flags. Existing jobs are unchanged: they run `tests/unit` and
`tests/integration` only, so benchmarks stay out of them.

## Done when

1. B1 and B2 exist and pass locally (B1) and on CI (B1 + B2).
2. The CI log of the first green run shows the B2 breakdown line; the reviewer
   copies the numbers into the "Results" section below.
3. A `cProfile` run of B1 (top 15 cumulative entries) is attached to the
   implementation report.
4. Gate green: ruff, ruff format, mypy (src + tests), lint-imports, unit tests.

## Results

CI `de0c099`, `ubuntu-24.04`, PostgreSQL 18 (Testcontainers):

| Benchmark | Objects | Deltas | Result |
|---|---|---|---|
| B2 end to end | 12,440 | 680 | inspect_source 1.393 s · inspect_target 1.402 s · diff_and_order 0.405 s · generate 0.439 s · render 0.024 s · **total 3.681 s** |
| B1 in memory | 12,440 | 680 | min 0.778 s · mean 0.789 s · max 0.797 s |

Budget (< 10 s) holds with about 2.7× headroom. Inspection is 76% of the end-to-end time.

Profile of B1 (local): `order_deltas` is the largest cumulative entry (2.2 s of 2.5 s under the profiler), mostly Pydantic `__hash__` on frozen deltas; it runs twice per pipeline (`compare_schemas_with_snapshots` and again inside `assess_deltas`). Not optimized: no budget pressure. Candidate if a larger workload is needed later.
