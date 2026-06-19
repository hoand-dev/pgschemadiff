# AI_STATE.md
_Last updated: 2026-06-19_

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/brave-gauss-f3he8w` — rebased onto `main`; 4 commits ahead.

---

## Current Project Phase
**Phase 1 — Infrastructure (MVP-A) — Batch C**

Phase 0 ✅. Phase 1 domain ✅ (P1-DOM-01..09). Phase 1 infra Batch A+B ✅ (P1-INFRA-01..05, P1-TEST-01).
Now executing Batch C: P1-INFRA-06 (type normalizer), P1-TEST-02 (integration tests), P1-CLI-01 (inspect CLI).

---

## CI / PR Status
- **Local**: ruff ✅ mypy strict ✅ 392 unit tests ✅ 85.0% coverage (2026-06-19)
- **Remote CI `claude/brave-gauss-f3he8w`**: ✅ GREEN (run 27811581234, head ebaedb58)
- **Open PRs**: 0

---

## What Is Done

### Phase 0 — Stabilization ✅
All P0-ENV, P0-INFRA, P0-CI, P0-ARCH, P0-LOG, P0-DOC, P0-QUAL tasks complete.
Gap: P0-CI-03 (coverage gate 85%/80%) — not yet wired into CI.

### Phase 1 — Domain layer ✅
P1-DOM-01..09 complete: identity, column, constraint, table, index, schema, extension, database, ports.
268 domain unit tests.

### Phase 1 — Infrastructure Batch A+B ✅
| Task | Title |
|---|---|
| P1-INFRA-01 | `infrastructure/postgres/pool.py` — Pool async context-manager |
| P1-INFRA-02 | `catalog/tables.sql` + `columns.sql` |
| P1-INFRA-03 | `catalog/indexes.sql` + `constraints.sql` |
| P1-INFRA-04 | `catalog/extensions.sql` + `schemas.sql` |
| P1-INFRA-05 | `inspector.py` — PgCatalogInspector (510 lines, single REPEATABLE READ tx) |
| P1-TEST-01  | `tests/integration/conftest.py` — session-scoped postgres:18 fixture |

Total: 392 unit tests passing.

---

## Phase 1 Infrastructure — Batch C (EXECUTION QUEUE)

| Task | Title | Status |
|---|---|---|
| P1-INFRA-06 | Type normalizer (`infrastructure/postgres/type_normalizer.py`) | **DISPATCHED** |
| P1-TEST-02  | Inspector integration tests (`tests/integration/test_inspector.py`) | TODO |
| P1-CLI-01   | `pgsd inspect <conn-url>` CLI command | TODO |

---

## Critical Path
```
P1-DOM-01..09 ✅ → P1-INFRA-01..05 ✅ → P1-INFRA-06 → P1-CLI-01 (M1 gate)
                                          ↑
                                    P1-TEST-02 (CI-only)
```

---

## Architectural Notes
- Clean Architecture: domain < application < infrastructure < presentation (import-linter enforced)
- Domain is pure-sync Pydantic v2 frozen models — no IO, no async, no drivers
- `StrEnum` comparisons in tests: use `.value ==` not `== "literal"` (mypy strict comparison-overlap)
- Pool import in inspector.py lives under `TYPE_CHECKING` (TC001 — annotations only, lazy via PEP 563)
- `format_type(atttypid, atttypmod)` returns internal pg strings → type normalizer maps to canonical names
- Catalog SQL loaded via `importlib.resources` at module import — zero disk IO per call
- ADR-0012: single REPEATABLE READ tx per inspect() call (multi-snapshot deferred to P1-INFRA-07)

---

## Next Run Instructions
1. Verify P1-INFRA-06 commit on branch — ruff/mypy/tests all green
2. Dispatch P1-TEST-02 (inspector integration tests — QA agent)
3. Dispatch P1-CLI-01 (pgsd inspect CLI — backend-engineer)
4. After P1-CLI-01: verify M1 milestone gate (`pgsd inspect` dumps schema JSON)
5. Update TASK_INDEX.md + DAILY_LOG.md after each run
