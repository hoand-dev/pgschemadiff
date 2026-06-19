# Task Breakdown — pgschemadiff

> Stable, in-repo source of truth for task IDs referenced by sub-agents and PRs.
> Sub-agents must update the status checkbox of any task they complete and reflect
> the change in `docs/PROJECT_CONTEXT.md` in the same commit.
>
> ID format: `P<phase>-<role>-<num>` (e.g. `P1-DOM-03`).
> Priority: **P0** blocker · **P1** critical · **P2** important · **P3** nice-to-have.
> Complexity: **S** <2h · **M** half-day · **L** 1-2 days · **XL** 3+ days.

---

## Phase 0 — Stabilization  ✅ baseline complete

| Status | ID | Title | Owner | Pri | Deps | Cx |
|---|---|---|---|---|---|---|
| [x] | P0-ENV-01  | Init `pyproject.toml` (PEP 621) + deps | devops-engineer | P0 | — | S |
| [x] | P0-ENV-02  | `uv` workflow + `uv.lock` + `.python-version` | devops-engineer | P0 | P0-ENV-01 | S |
| [x] | P0-ENV-03  | Pin Textual version (≥0.83) | tui-engineer | P0 | P0-ENV-01 | S |
| [x] | P0-INFRA-01 | ruff config | devops-engineer | P0 | P0-ENV-01 | S |
| [x] | P0-INFRA-02 | mypy strict config | devops-engineer | P0 | P0-ENV-01 | S |
| [x] | P0-INFRA-03 | import-linter contracts | architect | P0 | P0-ENV-01 | M |
| [x] | P0-INFRA-04 | pytest + asyncio + benchmark + syrupy + hypothesis | qa-engineer | P0 | P0-ENV-01 | S |
| [x] | P0-INFRA-05 | pre-commit config | devops-engineer | P1 | P0-INFRA-01..03 | S |
| [x] | P0-CI-01   | GitHub Actions: lint + typecheck + unit | devops-engineer | P0 | P0-INFRA-01..04 | M |
| [x] | P0-CI-02   | GitHub Actions: integration job (postgres:18) | devops-engineer | P0 | P0-CI-01 | M |
| [ ] | P0-CI-03   | Coverage gate (85% line / 80% branch) in CI | qa-engineer | P1 | P0-CI-01 | S |
| [x] | P0-ARCH-01 | Clean Architecture skeleton + `py.typed` | architect | P0 | P0-ENV-01 | S |
| [x] | P0-LOG-01  | structlog baseline | devops-engineer | P1 | P0-ARCH-01 | S |
| [x] | P0-DOC-01  | `docs/PROJECT_CONTEXT.md` | architect | P0 | — | S |
| [x] | P0-DOC-02  | `docs/ROADMAP.md` | architect | P0 | — | S |
| [x] | P0-DOC-03  | ADR template (`docs/adr/0000-template.md`) | architect | P0 | — | S |
| [x] | P0-DOC-04  | ADR-0001 … ADR-0012 | architect | P0 | P0-DOC-03 | L |
| [x] | P0-DOC-05  | `docs/architecture.md` | architect | P1 | P0-DOC-04 | M |
| [x] | P0-DOC-06  | `README.md` | architect | P1 | P0-DOC-01 | S |
| [x] | P0-QUAL-01 | Smoke tests | qa-engineer | P0 | P0-ARCH-01 | S |

## Phase 1 — Domain & Infrastructure (MVP-A)

| Status | ID | Title | Owner | Pri | Deps | Cx |
|---|---|---|---|---|---|---|
| [x] | P1-DOM-01 | `domain/identity.py` — QualifiedName, ObjectRef, ObjectKind | backend-engineer | P0 | P0-ARCH-01 | S |
| [x] | P1-DOM-02 | `domain/column.py` — Column + GeneratedColumn + IdentitySpec | backend-engineer | P0 | P1-DOM-01 | M |
| [x] | P1-DOM-03 | `domain/constraint.py` — discriminated union (PK/Unique/Check/FK/Exclusion) | backend-engineer | P0 | P1-DOM-01 | M |
| [x] | P1-DOM-04 | `domain/table.py` — Table aggregate (cols, constraints, partition) | backend-engineer | P0 | P1-DOM-02, P1-DOM-03 | M |
| [x] | P1-DOM-05 | `domain/index.py` — Index (method, columns, INCLUDE, predicate, opclass) | backend-engineer | P0 | P1-DOM-01 | M |
| [x] | P1-DOM-06 | `domain/schema.py` + `domain/extension.py` | backend-engineer | P0 | P1-DOM-01 | S |
| [x] | P1-DOM-07 | `domain/database.py` — top-level aggregate | backend-engineer | P0 | P1-DOM-04..06 | S |
| [x] | P1-DOM-08 | `domain/ports.py` — SchemaInspector, MigrationWriter Protocols | backend-engineer | P0 | P1-DOM-07 | S |
| [x] | P1-DOM-09 | Unit tests for all domain models | qa-engineer | P0 | P1-DOM-07 | M |
| [x] | P1-INFRA-01 | `infrastructure/postgres/pool.py` — AsyncConnectionPool wrapper | backend-engineer | P0 | P0-ENV-01 | M |
| [x] | P1-INFRA-02 | `catalog/tables.sql` + `columns.sql` | backend-engineer | P0 | — | M |
| [x] | P1-INFRA-03 | `catalog/indexes.sql` + `constraints.sql` | backend-engineer | P0 | — | M |
| [x] | P1-INFRA-04 | `catalog/extensions.sql` + schemas | backend-engineer | P0 | — | S |
| [x] | P1-INFRA-05 | `PgCatalogInspector` for MVP-A | backend-engineer | P0 | P1-INFRA-01..04, P1-DOM-08 | XL |
| [ ] | P1-INFRA-06 | Type normalizer | backend-engineer | P0 | P1-INFRA-05 | M |
| [ ] | P1-INFRA-07 | Multi-connection `pg_export_snapshot` (deferred) | backend-engineer | P2 | P1-INFRA-05 | M |
| [x] | P1-TEST-01 | Session-scoped pg18 container fixture | qa-engineer | P0 | P0-CI-02 | M |
| [ ] | P1-TEST-02 | Inspector integration tests | qa-engineer | P0 | P1-INFRA-05 | L |
| [ ] | P1-CLI-01 | `pgsd inspect <conn-url>` | backend-engineer | P1 | P1-INFRA-05 | M |

## Phase 2 — Diff Engine

| Status | ID | Title | Owner | Pri | Deps | Cx |
|---|---|---|---|---|---|---|
| [ ] | P2-DOM-01 | `domain/delta.py` — 40+ Delta subclasses with discriminator | backend-engineer | P0 | P1-DOM-07 | L |
| [ ] | P2-DIFF-01 | `application/diff/engine.py` — visitor dispatcher | backend-engineer | P0 | P2-DOM-01 | M |
| [ ] | P2-DIFF-02 | `comparators/table.py` | backend-engineer | P0 | P2-DIFF-01 | L |
| [ ] | P2-DIFF-03 | `comparators/column.py` | backend-engineer | P0 | P2-DIFF-02 | L |
| [ ] | P2-DIFF-04 | `comparators/index.py` | backend-engineer | P0 | P2-DIFF-01 | M |
| [ ] | P2-DIFF-05 | `comparators/constraint.py` (incl. FK) | backend-engineer | P0 | P2-DIFF-01 | M |
| [ ] | P2-DIFF-06 | Rename annotation loader (YAML/TOML) | backend-engineer | P1 | P2-DIFF-03 | M |
| [ ] | P2-DIFF-07 | Ignore-rules system | backend-engineer | P1 | P2-DIFF-01 | M |
| [ ] | P2-DIFF-08 | `topo_sort.py` — Kahn + cycle detect | backend-engineer | P0 | P2-DOM-01 | M |
| [ ] | P2-TEST-01 | Per-comparator unit tests | qa-engineer | P0 | P2-DIFF-02..05 | L |
| [ ] | P2-TEST-02 | Hypothesis property tests | qa-engineer | P0 | P2-DIFF-01..05 | L |
| [ ] | P2-CLI-01 | `pgsd diff` command | backend-engineer | P1 | P2-DIFF-01..08 | S |

## Phase 3a — Migration Generator (MVP-A)

| Status | ID | Title | Owner | Pri | Deps | Cx |
|---|---|---|---|---|---|---|
| [ ] | P3-SQL-01 | `sql_emit/emitter.py` — dispatcher | backend-engineer | P0 | P2-DOM-01 | M |
| [ ] | P3-SQL-02 | `table_emitter.py` | backend-engineer | P0 | P3-SQL-01 | L |
| [ ] | P3-SQL-03 | `column_emitter.py` | backend-engineer | P0 | P3-SQL-01 | L |
| [ ] | P3-SQL-04 | `index_emitter.py` (CONCURRENTLY default) | backend-engineer | P0 | P3-SQL-01 | M |
| [ ] | P3-SQL-05 | `constraint_emitter.py` (NOT VALID + VALIDATE) | backend-engineer | P0 | P3-SQL-01 | M |
| [ ] | P3-RISK-01 | Risk classifier (5 levels) | backend-engineer | P0 | P2-DOM-01 | M |
| [ ] | P3-TX-01 | Transaction unit splitter | backend-engineer | P0 | P3-SQL-04, P3-RISK-01 | M |
| [ ] | P3-OUT-01 | Multi-file migration writer | backend-engineer | P0 | P3-SQL-01..05, P3-TX-01 | M |
| [ ] | P3-APPLY-01 | `infrastructure/postgres/applier.py` | backend-engineer | P0 | P3-OUT-01 | M |
| [ ] | P3-CLI-01 | `pgsd generate` + `pgsd apply` | backend-engineer | P0 | P3-OUT-01, P3-APPLY-01 | M |
| [ ] | P3-TEST-01 | **Round-trip integration test (CORE)** | qa-engineer | P0 | P3-APPLY-01 | L |
| [ ] | P3-TEST-02 | Emitter snapshot tests | qa-engineer | P0 | P3-SQL-02..05 | M |

## Phase 3b — MVP-B object types

| Status | ID | Title | Owner | Pri | Deps | Cx |
|---|---|---|---|---|---|---|
| [ ] | P3-MVPB-01 | Views | backend-engineer | P1 | P3-CLI-01 | M |
| [ ] | P3-MVPB-02 | Materialized views | backend-engineer | P1 | P3-CLI-01 | M |
| [ ] | P3-MVPB-03 | Functions | backend-engineer | P1 | P3-CLI-01 | L |
| [ ] | P3-MVPB-04 | Procedures | backend-engineer | P1 | P3-CLI-01 | M |
| [ ] | P3-MVPB-05 | Sequences | backend-engineer | P1 | P3-CLI-01 | M |
| [ ] | P3-MVPB-06 | Enums (ADD VALUE positioning) | backend-engineer | P1 | P3-CLI-01 | M |
| [ ] | P3-MVPB-07 | Triggers | backend-engineer | P1 | P3-CLI-01 | L |
| [ ] | P3-MVPB-08 | RLS policies | backend-engineer | P1 | P3-CLI-01 | M |
| [ ] | P3-MVPB-09 | Composite types | backend-engineer | P1 | P3-CLI-01 | M |
| [ ] | P3-MVPB-10 | Domain types | backend-engineer | P1 | P3-CLI-01 | M |

## Phase 4 — TUI

| Status | ID | Title | Owner | Pri | Deps | Cx |
|---|---|---|---|---|---|---|
| [x] | P4-UX-01 | Import user UI design → `docs/ui-design.md` (+ bundle in `docs/ui-design/reference/`) | tui-engineer | P0 | user input | S |
| [x] | P4-TUI-01 | TUI app shell — Catppuccin theme, vim chord dispatcher, command palette, help modal, 7 placeholder views, `pgsd tui` entry | tui-engineer | P0 | P4-UX-01 | L |
| [ ] | P4-TUI-02 | ConnectionView wired to real source/target profiles | tui-engineer | P1 | P1-INFRA-05 | M |
| [ ] | P4-TUI-03 | OverviewView wired to `application/diff` | tui-engineer | P1 | P2-DIFF-01 | M |
| [ ] | P4-TUI-04 | DiffView (side / inline / tree modes) | tui-engineer | P1 | P2-DIFF-02 | L |
| [ ] | P4-TUI-05 | MigrationView wired to `application/sql_emit` | tui-engineer | P1 | P3-OUT-01 | M |
| [ ] | P4-TUI-06 | ApplyView with progress worker + log stream | tui-engineer | P1 | P3-APPLY-01 | L |
| [ ] | P4-TUI-07 | HistoryView reading the migration manifest store | tui-engineer | P1 | P3-OUT-01 | M |
| [ ] | P4-TUI-08 | SettingsView with live config.toml preview | tui-engineer | P2 | P4-TUI-01 | M |

## Phase 5 — Production readiness

| Status | ID | Title | Owner | Pri | Deps | Cx |
|---|---|---|---|---|---|---|
| [ ] | P5-CLI-01 | Full CLI UX (progress, color, `--max-risk`) | backend-engineer | P1 | P3-CLI-01 | M |
| [ ] | P5-REPORT-01 | HTML diff report | backend-engineer | P2 | P3-OUT-01 | L |
| [ ] | P5-I18N-01 | EN + VI message catalog | backend-engineer | P3 | — | M |
| [ ] | P5-PKG-01 | `uv build` + PyPI publish workflow | devops-engineer | P1 | M3 reached | M |
| [ ] | P5-BENCH-01 | Benchmark suite (10k objects) | devops-engineer | P1 | M3 reached | M |
| [ ] | P5-DOCS-01 | User guide + safe-migration cookbook | architect | P1 | M3 reached | L |

---

## Critical path

```
P0 baseline ─┐
              ├─→ P1-DOM-01 ─→ P1-DOM-07 ─→ P1-INFRA-05 ─→
                                                          P2-DOM-01 ─→ P2-DIFF-01 ─→ P2-DIFF-02 ─→
                                                          P3-SQL-01 ─→ P3-OUT-01 ─→ P3-APPLY-01 ─→ P3-TEST-01 (M3)
```

## Parallel batches (after dependencies met)

- **B1 (after P1-DOM-01):** P1-DOM-02 ∥ P1-DOM-03 ∥ P1-DOM-05 ∥ P1-DOM-06
- **B2 (after P0-baseline):** P1-INFRA-02 ∥ P1-INFRA-03 ∥ P1-INFRA-04 (catalog SQL drafts)
- **B3 (after P2-DIFF-01):** P2-DIFF-02 ∥ P2-DIFF-04 ∥ P2-DIFF-05 (independent comparators)
- **B4 (after P3-SQL-01):** P3-SQL-02 ∥ P3-SQL-03 ∥ P3-SQL-04 ∥ P3-SQL-05 + P3-RISK-01

## Hard "do not do yet"

- ❌ TUI screens before user provides UI design (Phase 4 blocked)
- ❌ MVP-B object types before MVP-A round-trip test green
- ❌ Heuristic rename detection (ADR-0007)
- ❌ Multi-connection snapshot (P1-INFRA-07) unless single-connection benchmark fails
- ❌ HTML report / i18n / PyPI / benchmark suite before M3
- ❌ Backward compat with PG ≤17 in MVP
- ❌ `pg_dump` dependency (ADR-0004)
- ❌ Idempotent migrations by default (only via opt-in flag)
- ❌ Force-push or amend after pushing to `claude/stoic-pascal-LOygS`
