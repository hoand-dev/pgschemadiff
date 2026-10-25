# TASK_INDEX.md
_Last updated: 2026-10-23_
_Canonical task list lives in `docs/TASKS.md` — this file mirrors the execution queue._

---

## Phase 0 — Stabilization

| Status | ID | Title |
|---|---|---|
| ✅ DONE | P0-ENV-01  | `pyproject.toml` (PEP 621) + deps |
| ✅ DONE | P0-ENV-02  | `uv` workflow + `uv.lock` + `.python-version` |
| ✅ DONE | P0-INFRA-01..05 | ruff, mypy, import-linter, pytest, pre-commit |
| ✅ DONE | P0-CI-01   | GitHub Actions: lint + typecheck + unit |
| ✅ DONE | P0-CI-02   | GitHub Actions: integration job (postgres:18) |
| TODO    | P0-CI-03   | Coverage gate (85%/80%) in CI |
| ✅ DONE | P0-ARCH-01 | Clean Architecture skeleton + `py.typed` |
| ✅ DONE | P0-LOG-01  | structlog baseline |
| ✅ DONE | P0-DOC-01..06 | All docs (ADRs, architecture.md, README) |
| ✅ DONE | P0-QUAL-01 | Smoke tests |

---

## Phase 1 — Domain Layer

| Status | ID | Title |
|---|---|---|
| ✅ DONE | P1-DOM-01 | `domain/identity.py` |
| ✅ DONE | P1-DOM-02 | `domain/column.py` |
| ✅ DONE | P1-DOM-03 | `domain/constraint.py` |
| ✅ DONE | P1-DOM-04 | `domain/table.py` |
| ✅ DONE | P1-DOM-05 | `domain/index.py` |
| ✅ DONE | P1-DOM-06 | `domain/schema.py` + `domain/extension.py` |
| ✅ DONE | P1-DOM-07 | `domain/database.py` |
| ✅ DONE | P1-DOM-08 | `domain/ports.py` (SchemaInspector + MigrationWriter Protocols) |
| ✅ DONE | P1-DOM-09 | Unit tests (268 tests total, all passing) |

---

## Phase 1 — Infrastructure (done; exceptions listed below)

### Batch A — DONE ✅

```
[x] P1-INFRA-01  infrastructure/postgres/pool.py
[x] P1-INFRA-02  catalog/tables.sql + columns.sql
[x] P1-INFRA-03  catalog/indexes.sql + constraints.sql
[x] P1-INFRA-04  catalog/extensions.sql + schemas
```

### Batch A2 — DONE ✅

```
[x] P1-TEST-01   session-scoped pg18 container fixture
```

### Batch B — DONE ✅

```
[x] P1-INFRA-05  PgCatalogInspector (inspector.py, 710 lines)
[x] P1-TEST-01   session-scoped pg18 container fixture
```

### Batch C — DONE ✅ (PR #2 MERGED 2026-06-22)

```
[x] P1-INFRA-06  Type normalizer            ← MERGED to main via PR #2  attempts:1
[x] P1-CLI-01    pgsd inspect <conn-url>     ← MERGED to main via PR #2 — M1 feature  attempts:1
[H] P1-TEST-02   Inspector integration tests ← NEEDS-HUMAN: PR #3 closed without merge by human (2026-06-22); do NOT recreate  attempts:1
```
Status key: [x] done (merged to main) · [H] needs-human.

### Optional (deferred)
```
[ ] P0-CI-03     Coverage gate (85%/80%)
[ ] P1-INFRA-07  Multi-connection pg_export_snapshot
```

---

## Phase 2 — Diff Engine (done)

Decomposed from docs/TASKS.md P2-* (M2 gate). Each unit ≤ ~3 files + one testable
done-condition. Clean Architecture per ADR-0005: deltas live in `domain/`, the
engine + comparators + topo-sort + rename/ignore loaders live in `application/diff/`,
the CLI command in `presentation/cli/`. Discriminated-union deltas per ADR-0003;
per-type comparators per ADR-0006; explicit-annotation renames per ADR-0007.

> **P2-DOM-01 split rationale:** docs/TASKS.md ships `domain/delta.py` as "40+ Delta
> subclasses" (Cx L) — too large for one ≤3-file unit. Splitting by object category
> yields clean 2-file units (module + its unit test) AND lets the independent
> comparators (table/index/constraint) start as soon as their matching delta module
> lands, instead of blocking on a single mega-module. The shared base + discriminated-
> union alias + `DeltaSet` container lands first (P2-DOM-01a); category modules
> (P2-DOM-01b..f) re-export through `domain/delta/__init__.py`. Net public import
> surface is unchanged (`from pgschemadiff.domain.delta import ...`).

| id | title | status | deps | files | attempts | priority |
|---|---|---|---|---|---|---|
| P2-DOM-01a | `domain/delta/` package: shared `DeltaBase`, `DeltaOp`/discriminator, `DeltaSet` container | done | P1-DOM-07, P1-INFRA-05 | src/pgschemadiff/domain/delta/__init__.py, src/pgschemadiff/domain/delta/base.py, tests/unit/domain/delta/test_base.py | 1 | high | **MERGED to main via PR #4** (rebase, 2026-06-23); reviewed + RF-A |
| P2-DOM-01b | Table-level deltas (Create/Drop/RenameTable, partition/owner attrs) | done | P2-DOM-01a | src/pgschemadiff/domain/delta/table.py, tests/unit/domain/delta/test_table.py | 0 | high |
| P2-DOM-01c | Column deltas (Add/Drop/AlterType/SetDefault/Nullability/RenameColumn) | done | P2-DOM-01a | src/pgschemadiff/domain/delta/column.py, tests/unit/domain/delta/test_column.py | 1 | high | on main; integrated 2026-06-29 |
| P2-DOM-01d | Index deltas (Create/Drop/Replace, method/predicate/include changes) | done | P2-DOM-01a, P2-DOM-01c | src/pgschemadiff/domain/delta/index.py, tests/unit/domain/delta/test_index.py | 0 | high | on main |
| P2-DOM-01e | Constraint deltas incl. FK (Add/Drop PK/Unique/Check/FK/Exclusion) | done | P2-DOM-01a, P2-DOM-01d | src/pgschemadiff/domain/delta/constraint.py, tests/unit/domain/delta/test_constraint.py | 0 | high | on main |
| P2-DOM-01f | Schema + extension deltas (Create/Drop schema, Create/Drop/Alter extension) **+ retype `DeltaSet.deltas` to the concrete `Delta` discriminated-union alias** (RF-A `TODO(P2-DOM-01f)` in delta/base.py — closes the lossy-round-trip gap) | done | P2-DOM-01a, P2-DOM-01e | src/pgschemadiff/domain/delta/schema.py, src/pgschemadiff/domain/delta/base.py, tests/unit/domain/delta/test_schema.py | 0 | high | on main |
| P2-DIFF-01 | `application/diff/engine.py` — visitor dispatcher over `ObjectRef.kind` → comparators | done | P2-DOM-01b, P2-DOM-01c, P2-DOM-01d, P2-DOM-01e, P2-DOM-01f | src/pgschemadiff/application/diff/engine.py, src/pgschemadiff/application/diff/__init__.py, tests/unit/application/diff/test_engine.py | 0 | high | on main |
| P2-DIFF-02 | `comparators/table.py` — table-level diff (create/drop/rename/attrs), delegates cols/idx/constraints | done | P2-DIFF-01 | src/pgschemadiff/application/diff/comparators/table.py, tests/unit/application/diff/comparators/test_table.py | 0 | high | on main |
| P2-DIFF-03 | `comparators/column.py` — per-column diff (add/drop/type/default/nullability) | done | P2-DIFF-02 | src/pgschemadiff/application/diff/comparators/column.py, tests/unit/application/diff/comparators/test_column.py | 1 | high | commit `709467e`; full unit suite: 1,135 passed |
| P2-DIFF-04 | `comparators/index.py` — index diff (create/drop/replace on method/predicate/include) | done | P2-DIFF-01 | src/pgschemadiff/application/diff/comparators/index.py, tests/unit/application/diff/comparators/test_index.py | 0 | high | on main |
| P2-DIFF-05 | `comparators/constraint.py` — constraint diff incl. FK (add/drop) | done | P2-DIFF-01 | src/pgschemadiff/application/diff/comparators/constraint.py, tests/unit/application/diff/comparators/test_constraint.py | 0 | high | on main |
| P2-DIFF-06 | Rename annotation loader (YAML/TOML) feeding the engine (ADR-0007) | done | P2-DIFF-03 | src/pgschemadiff/application/diff/renames.py, src/pgschemadiff/infrastructure/config/rename_loader.py, tests/unit/application/diff/test_renames.py | 1 | med | explicit table/column mappings integrated; dependent references normalized without SQL rewriting; 1,173 tests, Ruff, formatter, mypy, and build pass; CLI deferred to P2-CLI-01 |
| P2-DIFF-07 | Ignore-rules system (object/attr exclusion filter on DeltaSet) | done | P2-DIFF-01 | src/pgschemadiff/application/diff/ignore.py, src/pgschemadiff/application/diff/engine.py, src/pgschemadiff/application/diff/__init__.py, tests/unit/application/diff/test_ignore.py, tests/unit/application/diff/test_engine.py | 0 | med | Exact object/attribute filtering integrated into `DiffEngine.diff`; 1,227 non-integration tests, Ruff, format, and full mypy pass; Docker integration unavailable locally |
| P2-DIFF-08 | `topo_sort.py` — Kahn ordering + cycle detection → `CyclicDependencyError` | done | P2-DOM-01a | src/pgschemadiff/application/diff/topo_sort.py, tests/unit/application/diff/test_topo_sort.py | 1 | high | **MERGED to main (rebase, human, 2026-06-26) via PR #7 — main now `27f63d7`, CI green.** |
| TD-TOPO-01 | Tech-debt (reviewer N1–N5): refactor topo_sort `id()`-keyed O(n·m) → hashable-node dict O(n+m); test-hardening (assert non-cycle node absent from cycle msg; Hypothesis DAG property test); doc fix re removed `DeltaOp.NO_CHANGE` | done | P2-DIFF-08 | src/pgschemadiff/application/diff/topo_sort.py, tests/unit/application/diff/test_topo_sort.py, docs/PROJECT_CONTEXT.md, pyproject.toml | 1 | low | on main |
| P2-TEST-01 | Per-comparator unit tests (edge cases beyond per-task tests) | done | P2-DIFF-02, P2-DIFF-03, P2-DIFF-04, P2-DIFF-05 | tests/unit/application/diff/comparators/test_comparators_edge.py | 0 | high | Added column ordering/type+collation, index nested-key, and constraint-field edge cases; 1,230 unit tests pass; Ruff, format, mypy, and import-linter pass |
| P2-TEST-02 | Hypothesis idempotent-diff + ordering property tests (max_examples=500) | done | P2-DIFF-01, P2-DIFF-02, P2-DIFF-03, P2-DIFF-04, P2-DIFF-05, P2-DIFF-08 | tests/unit/application/diff/test_diff_properties.py | 0 | high | Added 500-example properties for deep-copy self-diff and order stability under reversed schema/table/column collections; 1,232 unit tests + 6 snapshots, Ruff, format, mypy, and import-linter pass |
| P2-CLI-01 | `pgsd diff <src> <tgt>` — emit ordered DeltaSet JSON (M2 gate) | done | P2-DIFF-01, P2-DIFF-02, P2-DIFF-03, P2-DIFF-04, P2-DIFF-05, P2-DIFF-06, P2-DIFF-07, P2-DIFF-08 | src/pgschemadiff/infrastructure/postgres/catalog/schemas.sql, src/pgschemadiff/infrastructure/postgres/catalog/extensions.sql, src/pgschemadiff/infrastructure/postgres/inspector.py, tests/unit/infrastructure/postgres/test_inspector.py, tests/unit/infrastructure/postgres/test_catalog_sql.py, src/pgschemadiff/application/diff/comparators/schema.py, src/pgschemadiff/application/diff/comparators/extension.py, src/pgschemadiff/application/diff/dependencies.py, src/pgschemadiff/application/diff/compare_schemas.py, src/pgschemadiff/presentation/cli/commands/diff.py, src/pgschemadiff/presentation/cli/main.py, src/pgschemadiff/infrastructure/postgres/pool.py | 1 | med | on main; 1,338 unit tests pass; Docker integration not run locally |
```
[x] P2-DIFF-01..08 implemented on main.
[x] P2-DIFF-06 done; explicit YAML/TOML annotations integrated; CLI flag deferred to P2-CLI-01.
[x] P2-DIFF-07 done; exact object/attribute ignore rules integrated into `DiffEngine.diff`.
```

## Phase 3 — Migration Generator (in progress)

| id | title | status | deps | files | attempts | priority |
|---|---|---|---|---|---:|---|
| P3-RISK-01 | Five-level risk classifier | done | P2-DOM-01 | src/pgschemadiff/application/sql_emit/risk.py | — | high |
| P3-SQL-01 | Exact-type SQL emitter dispatcher | done | P2-DOM-01 | src/pgschemadiff/application/sql_emit/emitter.py | — | high |
| P3-SQL-02 | Table emitter | done | P3-SQL-01 | src/pgschemadiff/application/sql_emit/table_emitter.py | 0 | high |
| P3-SQL-03 | Column emitter | done | P3-SQL-01 | src/pgschemadiff/application/sql_emit/column_emitter.py | 0 | high |
| P3-SQL-04 | Index emitter (CONCURRENTLY default) | done | P3-SQL-01 | src/pgschemadiff/application/sql_emit/index_emitter.py | 0 | high |
| P3-SQL-05 | Constraint emitter (NOT VALID + VALIDATE) | done | P3-SQL-01 | src/pgschemadiff/application/sql_emit/constraint_emitter.py | 0 | high |
| P3-SQL-06 | Schema/extension emitter + `default_handlers()` registry | done | P3-SQL-01 | src/pgschemadiff/application/sql_emit/schema_emitter.py, src/pgschemadiff/application/sql_emit/registry.py | 0 | high |
| P3-TX-01 | Transaction unit splitter | done | P3-SQL-04, P3-RISK-01 | src/pgschemadiff/application/sql_emit/transaction.py | 0 | high |
| P3-OUT-01 | Multi-file migration writer (plan, renderer, atomic writer; `MigrationWriter` moved to application) | done | P3-SQL-01..05, P3-TX-01 | src/pgschemadiff/application/migration/, src/pgschemadiff/infrastructure/fs/migration_writer.py | 0 | high |
| P3-APPLY-01 | Bundle applier (validator, use case, executor, history schema) | done | P3-OUT-01 | src/pgschemadiff/infrastructure/postgres/applier.py | 0 | high |
| P3-CLI-01 | `pgsd generate` + `pgsd apply` | done | P3-OUT-01, P3-APPLY-01 | src/pgschemadiff/presentation/cli/commands/ | 0 | high |
| P3-TEST-01 | Round-trip integration test (M3 gate); seed + 37-scenario corpus | done | P3-APPLY-01 | — | 0 | high |
| P3-TEST-02 | Emitter snapshot corpus | done | P3-SQL-02..05 | — | 0 | high |

## Phase 4 — TUI
P4-UX-01 and P4-TUI-01 DONE. The shell and all seven views are implemented on mock data (`presentation/tui/_mock.py`); P4-TUI-02..08 real-use-case wiring remains TODO.

---

## Milestones

| Gate | Condition | Status |
|---|---|---|
| M0 | CI green; layered arch enforced | Phase 0 done except open P0-CI-03 coverage gate; CI fixes committed locally as `5f34d3f`, remote CI not rechecked |
| M1 | `pgsd inspect` dumps schema JSON | Feature shipped; exit caveat: P1-TEST-02 needs-human and 1000-object benchmark unmeasured |
| M2 | `pgsd diff` emits typed DeltaSet | ✅ Phase 2 complete; 1,338 unit tests pass; Docker integration not run locally |
| M3 | round-trip integration test green | ✅ Reached 2026-10-26 (CI `aeef321`); TD xfails fixed, CI `0c9536b`: 48 passed |
