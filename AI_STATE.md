# AI_STATE.md
_Last updated: 2026-06-19_

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/brave-gauss-f3he8w` — 2 commits ahead of `main`.

---

## Current Project Phase
**Phase 1 — Domain & Infrastructure (MVP-A)**

Phase 0 is complete. Phase 1 domain layer (P1-DOM-01..09) is complete.
Next: Phase 1 infrastructure layer (P1-INFRA-01..07) + tests (P1-TEST-01..02) + CLI (P1-CLI-01).

---

## CI / PR Status
- **Local**: ruff ✅ mypy strict ✅ 268 tests ✅ (as of 2026-06-19)
- **Remote branch `claude/brave-gauss-f3he8w`**: pushed; awaiting GitHub Actions result
- **Previous CI failure on `claude/busy-maxwell-4Qa3h`**: RESOLVED — mypy errors in domain test suite fixed (comparison-overlap on StrEnum, attr-defined on Protocol.__protocol_attrs__, unused-ignore on TypeAdapter)
- **Open PRs**: 0

---

## What Is Done

### Phase 0 — Stabilization ✅
All P0-ENV, P0-INFRA, P0-CI, P0-ARCH, P0-LOG, P0-DOC, P0-QUAL tasks complete.
One gap: P0-CI-03 (coverage gate 85%/80%) — not yet wired into CI.

### Phase 1 — Domain layer ✅
All P1-DOM-01..09 tasks complete:
- `domain/identity.py` — QualifiedName, ObjectRef, ObjectKind
- `domain/column.py` — Column, IdentitySpec, GeneratedTiming
- `domain/constraint.py` — discriminated union (PK/Unique/Check/FK/Exclusion)
- `domain/table.py` — Table aggregate (columns, constraints, partitions)
- `domain/index.py` — Index (method, key columns, INCLUDE, predicate, opclass)
- `domain/schema.py` + `domain/extension.py`
- `domain/database.py` — top-level aggregate
- `domain/ports.py` — SchemaInspector + MigrationWriter Protocols
- 268 unit tests covering all domain models

---

## Phase 1 Infrastructure — Next Execution Targets

### Immediate (unblocked)
| Task | Title | Complexity |
|---|---|---|
| P1-INFRA-01 | `infrastructure/postgres/pool.py` — AsyncConnectionPool wrapper | M |
| P1-INFRA-02 | `catalog/tables.sql` + `columns.sql` | M |
| P1-INFRA-03 | `catalog/indexes.sql` + `constraints.sql` | M |
| P1-INFRA-04 | `catalog/extensions.sql` + schemas | S |
| P1-TEST-01  | Session-scoped pg18 container fixture | M |

### Dependent on P1-INFRA-01..04
| Task | Title |
|---|---|
| P1-INFRA-05 | `PgCatalogInspector` (main MVP-A inspector) |
| P1-INFRA-06 | Type normalizer |
| P1-TEST-02  | Inspector integration tests |
| P1-CLI-01   | `pgsd inspect <conn-url>` |

---

## Critical Path
```
P1-DOM-01..09 ✅ ─→ P1-INFRA-01 ─→ P1-INFRA-05 ─→ P1-CLI-01 (M1 gate)
                      ↑
              P1-INFRA-02/03/04 (parallel)
```

---

## Architectural Notes
- Clean Architecture: domain < application < infrastructure < presentation (enforced by import-linter)
- Domain is pure-sync Pydantic v2 frozen models — no IO, no async, no drivers
- All `StrEnum` comparisons in tests should use `.value` (mypy strict `comparison-overlap`)
- Textual bug workaround: do not extend Vertical/Container with complex compose — inline into Screen
- psycopg async pool will be wrapped in `infrastructure/postgres/pool.py` (P1-INFRA-01)
- Catalog queries are plain SQL files in `src/pgschemadiff/infrastructure/postgres/catalog/`

---

## Next Run Instructions
1. Check if GitHub Actions CI is green on `claude/brave-gauss-f3he8w`
2. If green: dispatch `developer` for P1-INFRA-01 (pool wrapper) and P1-INFRA-02/03/04 (catalog SQL) in parallel
3. If red: dispatch `ci-recovery` first
4. Always: update TASK_INDEX.md + DAILY_LOG.md + PROGRESS.md after each run
