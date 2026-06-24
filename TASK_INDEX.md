# TASK_INDEX.md
_Last updated: 2026-06-22_
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

## Phase 1 — Infrastructure (EXECUTION QUEUE)

### Batch A — DONE ✅

```
[x] P1-INFRA-01  infrastructure/postgres/pool.py
[x] P1-INFRA-02  catalog/tables.sql + columns.sql
[x] P1-INFRA-03  catalog/indexes.sql + constraints.sql
[x] P1-INFRA-04  catalog/extensions.sql + schemas
```

### Batch A2 — unblocked

```
[ ] P1-TEST-01   session-scoped pg18 container fixture   ← dispatch now
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

## Phase 2 — Diff Engine (EXECUTION QUEUE)

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
| P2-DOM-01b | Table-level deltas (Create/Drop/RenameTable, partition/owner attrs) | review | P2-DOM-01a | src/pgschemadiff/domain/delta/table.py, tests/unit/domain/delta/test_table.py | 0 | high |
| P2-DOM-01c | Column deltas (Add/Drop/AlterType/SetDefault/Nullability/RenameColumn) | ready | P2-DOM-01a | src/pgschemadiff/domain/delta/column.py, tests/unit/domain/delta/test_column.py | 0 | high |
| P2-DOM-01d | Index deltas (Create/Drop/Replace, method/predicate/include changes) | ready | P2-DOM-01a | src/pgschemadiff/domain/delta/index.py, tests/unit/domain/delta/test_index.py | 0 | high |
| P2-DOM-01e | Constraint deltas incl. FK (Add/Drop PK/Unique/Check/FK/Exclusion) | ready | P2-DOM-01a | src/pgschemadiff/domain/delta/constraint.py, tests/unit/domain/delta/test_constraint.py | 0 | high |
| P2-DOM-01f | Schema + extension deltas (Create/Drop schema, Create/Drop/Alter extension) **+ retype `DeltaSet.deltas` to the concrete `Delta` discriminated-union alias** (RF-A `TODO(P2-DOM-01f)` in delta/base.py — closes the lossy-round-trip gap) | ready | P2-DOM-01a | src/pgschemadiff/domain/delta/schema.py, src/pgschemadiff/domain/delta/base.py, tests/unit/domain/delta/test_schema.py | 0 | high |
| P2-DIFF-01 | `application/diff/engine.py` — visitor dispatcher over `ObjectRef.kind` → comparators | blocked | P2-DOM-01b, P2-DOM-01c, P2-DOM-01d, P2-DOM-01e, P2-DOM-01f | src/pgschemadiff/application/diff/engine.py, src/pgschemadiff/application/diff/__init__.py, tests/unit/application/diff/test_engine.py | 0 | high |
| P2-DIFF-02 | `comparators/table.py` — table-level diff (create/drop/rename/attrs), delegates cols/idx/constraints | blocked | P2-DIFF-01 | src/pgschemadiff/application/diff/comparators/table.py, tests/unit/application/diff/comparators/test_table.py | 0 | high |
| P2-DIFF-03 | `comparators/column.py` — per-column diff (add/drop/type/default/nullability) | blocked | P2-DIFF-02 | src/pgschemadiff/application/diff/comparators/column.py, tests/unit/application/diff/comparators/test_column.py | 0 | high |
| P2-DIFF-04 | `comparators/index.py` — index diff (create/drop/replace on method/predicate/include) | blocked | P2-DIFF-01 | src/pgschemadiff/application/diff/comparators/index.py, tests/unit/application/diff/comparators/test_index.py | 0 | high |
| P2-DIFF-05 | `comparators/constraint.py` — constraint diff incl. FK (add/drop) | blocked | P2-DIFF-01 | src/pgschemadiff/application/diff/comparators/constraint.py, tests/unit/application/diff/comparators/test_constraint.py | 0 | high |
| P2-DIFF-06 | Rename annotation loader (YAML/TOML) feeding the engine (ADR-0007) | blocked | P2-DIFF-03 | src/pgschemadiff/application/diff/renames.py, tests/unit/application/diff/test_renames.py | 0 | med |
| P2-DIFF-07 | Ignore-rules system (object/attr exclusion filter on DeltaSet) | blocked | P2-DIFF-01 | src/pgschemadiff/application/diff/ignore.py, tests/unit/application/diff/test_ignore.py | 0 | med |
| P2-DIFF-08 | `topo_sort.py` — Kahn ordering + cycle detection → `CyclicDependencyError` | ready | P2-DOM-01a | src/pgschemadiff/application/diff/topo_sort.py, tests/unit/application/diff/test_topo_sort.py | 0 | high |
| P2-TEST-01 | Per-comparator unit tests (edge cases beyond per-task tests) | blocked | P2-DIFF-02, P2-DIFF-03, P2-DIFF-04, P2-DIFF-05 | tests/unit/application/diff/comparators/test_comparators_edge.py | 0 | high |
| P2-TEST-02 | Hypothesis idempotent-diff + ordering property tests (max_examples=500) | blocked | P2-DIFF-01, P2-DIFF-02, P2-DIFF-03, P2-DIFF-04, P2-DIFF-05, P2-DIFF-08 | tests/unit/application/diff/test_diff_properties.py | 0 | high |
| P2-CLI-01 | `pgsd diff <src> <tgt>` — emit ordered DeltaSet JSON (M2 gate) | blocked | P2-DIFF-01, P2-DIFF-02, P2-DIFF-03, P2-DIFF-04, P2-DIFF-05, P2-DIFF-06, P2-DIFF-07, P2-DIFF-08 | src/pgschemadiff/application/diff/compare_schemas.py, src/pgschemadiff/presentation/cli/commands/diff.py, tests/unit/presentation/cli/test_diff.py | 0 | med |
```
[ ] All Phase 2 rows above — none dispatched yet.
```

## Phase 3 — Migration Generator (blocked on Phase 2)

```
[ ] P3-SQL-01..05   emitters (table, column, index, constraint)
[ ] P3-RISK-01      risk classifier (5 levels)
[ ] P3-TX-01        transaction splitter
[ ] P3-OUT-01       multi-file migration writer
[ ] P3-APPLY-01     postgres applier
[ ] P3-CLI-01       pgsd generate + pgsd apply
[ ] P3-TEST-01      round-trip integration test (M3 gate)
[ ] P3-TEST-02      emitter snapshot tests
```

## Phase 4 — TUI (blocked on P2-DIFF-01 + P1-INFRA-05)
P4-UX-01 and P4-TUI-01 are DONE (TUI shell exists in presentation/tui/).
P4-TUI-02..08: blocked on domain + infrastructure work.

---

## Milestones

| Gate | Condition | Status |
|---|---|---|
| M0 | CI green; layered arch enforced | ✅ (CI green on `main`) |
| M1 | `pgsd inspect` dumps schema JSON | ✅ feature MERGED to main via PR #2 (2026-06-22). ⚠️ full ROADMAP M1 exit gate (integration test suite green vs pg18 + 1000-obj <2s benchmark) NOT met — P1-TEST-02 PR #3 closed by human (needs-human). |
| M2 | `pgsd diff` emits typed DeltaSet | 🟡 Phase 2 in progress — P2-DOM-01a foundation MERGED (PR #4); P2-DOM-01b..f + P2-DIFF-08 now `ready`; next: P2-DOM-01b |
| M3 | round-trip integration test green | ❌ |
