# P5-BENCH-01 — Implementation plan

**Spec:** `docs/specs/2026-10-26-p5-bench-01-benchmark-design.md` (read it first; it wins on any conflict).
**Date:** 2026-10-26

Files created: `tests/benchmark/__init__.py`, `tests/benchmark/conftest.py`,
`tests/benchmark/workload.py`, `tests/benchmark/test_workload.py`,
`tests/benchmark/test_bench_pipeline.py`, `tests/benchmark/test_bench_e2e.py`.
File edited: `.github/workflows/ci.yml` (new job only). `pyproject.toml` only
if a pytest setting is strictly required. No production code.

## Step 1 — Workload and object counter

1. Write `tests/benchmark/test_workload.py` first (TDD):
   - `count_objects` on a hand-built tiny `Database` returns the exact expected
     number (cover at least tables, columns, constraints, indexes, views,
     functions, sequences).
   - `BenchWorkload` with small numbers (e.g. 10 tables): `seed_sql("source")`
     and `seed_sql("target")` produce the expected table counts.
2. Implement `tests/benchmark/workload.py`: `BenchWorkload` (frozen dataclass,
   defaults from the spec table), `count_objects`, then `seed_sql`.
3. Read the domain models (`domain/database.py`, `schema.py`, `table.py`,
   `column.py`, `constraint.py`, `index.py`, `view.py`, `function.py`,
   `sequence.py`) and existing test builders under `tests/unit/application/diff/`
   before writing `build_snapshots`. Reuse existing test helpers if there are
   any; do not invent fields.

## Step 2 — B1 in-memory benchmark

1. `build_snapshots(workload)` returns `(source, target)` with the change set
   from the spec.
2. `tests/benchmark/test_bench_pipeline.py`: fake inspector →
   `compare_schemas_with_snapshots` → `generate_migration(max_risk=DESTRUCTIVE,
   clock/id_factory fixed)` → `render_bundle`, under `benchmark.pedantic`
   (3 rounds). Assertions: object count >= 10,000, delta window, round < 10 s.
3. Run it alone and note the time:
   `uv run --no-sync pytest tests/benchmark -m "benchmark and not integration" -v`

## Step 3 — Profile B1

Run B1's pipeline once under `cProfile` (a throwaway script in the scratch
area or `python -m cProfile`; do not commit it). Put the top 15 cumulative
entries in the final report. If B1 takes more than 10 s, stop here and report
the hotspot — do not optimize.

## Step 4 — B2 end-to-end benchmark

1. `tests/benchmark/conftest.py`: import the four integration fixtures from
   `tests.integration.conftest` (re-export; mark with `# noqa: F401` or list them
   in `__all__`).
2. `seed_sql(workload, side)` generates one script per side using server-side
   loops; executed once per database with `psycopg` autocommit.
3. `tests/benchmark/test_bench_e2e.py`: open pools via
   `composition.open_inspectors(src, tgt, schemas=["bench"])`, wrap each
   inspector in a timing proxy, call `compare_schemas_with_snapshots`, then
   `generate_migration` and `render_bundle`; print the breakdown line from the
   spec; assert total < 10 s plus the count checks.
4. Locally Docker is unavailable: verify with
   `uv run --no-sync pytest tests/benchmark --collect-only -q` only. Say so in
   the report; never claim it ran.

## Step 5 — CI job

Add the `benchmark` job from the spec to `.github/workflows/ci.yml`. Confirm
the existing `unit-test` and `integration-test` commands still target only
`tests/unit` / `tests/integration`.

## Step 6 — Verification and report

Run the full gate from the common rules and paste tails, plus:
- `uv run --no-sync pytest tests/benchmark -m "benchmark and not integration" -v`
- `uv run --no-sync pytest tests/benchmark --collect-only -q`

Report: files, B1 timing, cProfile top 15, any choice the spec did not fix,
anything left open. The reviewer fills the spec's "Results" section after CI.
