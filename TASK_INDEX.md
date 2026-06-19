# TASK_INDEX.md
_Last updated: 2026-06-19_
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

### Batch C — EXECUTION QUEUE (unblocked)

```
[ ] P1-INFRA-06  Type normalizer                        ← dispatch next
[ ] P1-TEST-02   Inspector integration tests
[ ] P1-CLI-01    pgsd inspect <conn-url>
```

### Optional (deferred)
```
[ ] P0-CI-03     Coverage gate (85%/80%)
[ ] P1-INFRA-07  Multi-connection pg_export_snapshot
```

---

## Phase 2 — Diff Engine (blocked on P1-INFRA-05)

```
[ ] P2-DOM-01    domain/delta.py — 40+ Delta subclasses
[ ] P2-DIFF-01   application/diff/engine.py — visitor
[ ] P2-DIFF-02..07  comparators (table, column, index, constraint, rename, ignore)
[ ] P2-DIFF-08   topo_sort.py
[ ] P2-TEST-01..02  unit + hypothesis tests
[ ] P2-CLI-01    pgsd diff
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
| M0 | CI green; layered arch enforced | ✅ (locally clean; CI push in progress) |
| M1 | `pgsd inspect` dumps schema JSON | ❌ P1-INFRA-05 not started |
| M2 | `pgsd diff` emits typed DeltaSet | ❌ |
| M3 | round-trip integration test green | ❌ |
