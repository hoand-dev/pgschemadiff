# Documentation index

## Repository root

- `README.md` — project overview, quickstart, and development commands.
- `AI_STATE.md` — current execution state and open human decisions.
- `TASK_INDEX.md` — execution queue, dependencies, and milestone status.
- `DAILY_LOG.md` — append-only run history.
- `ORCHESTRATOR.md` — coordination rules and state-file schemas.
- `PROGRESS.md` — obsolete prototype tracker; archive move pending.
- `REVIEW.md` — review of the 2026-05 `init` prototype; archive move pending.

## `docs/` top-level

- `README.md` — this index.
- `TASKS.md` — canonical task breakdown and checkboxes.
- `ROADMAP.md` — phases, milestone gates, and risks.
- `PROJECT_CONTEXT.md` — current project snapshot and implementation history.
- `architecture.md` — package layers, data flow, and testing tiers.
- `api.md` — API reference.
- `ui-design.md` — Textual TUI implementation contract.
- `migration.md` — legacy package migration guide; archive move pending.

## Architecture decisions (`docs/adr/`)

- `0000-template.md` — ADR template.
- `0001-use-uv-package-manager.md` — Use uv as the package manager.
- `0002-psycopg3-async.md` — Use psycopg 3 async.
- `0003-pydantic-v2-domain.md` — Pydantic v2 frozen models for the domain layer.
- `0004-pg-catalog-only-introspection.md` — `pg_catalog`-only introspection (no `pg_dump`).
- `0005-clean-architecture-4-layers.md` — Clean Architecture, 4 layers, enforced by import-linter.
- `0006-per-type-comparator-visitor.md` — Per-type Comparator + Visitor dispatcher for the diff engine.
- `0007-explicit-rename-annotation.md` — Explicit-annotation rename detection.
- `0008-multi-file-migration-output.md` — Multi-file migration output with manifest.
- `0009-five-level-risk-model.md` — Five-level risk model.
- `0010-session-scoped-postgres-container.md` — Session-scoped Postgres container, per-test database.
- `0011-typer-for-cli.md` — Use typer for the CLI.
- `0012-snapshot-consistency.md` — REPEATABLE READ + `pg_export_snapshot` for consistent introspection.

## Specs and design proposals (`docs/specs/`)

- `2026-10-22-p2-cli-01-diff-command-design.md` — P2-CLI-01 diff command design.
- `2026-10-22-p3-risk-01-risk-classifier-design.md` — P3-RISK-01 risk classifier design.
- `2026-10-23-p3-sql-01-emitter-dispatcher-design.md` — P3-SQL-01 SQL emitter dispatcher design.
- `2026-10-23-p3-sql-02-06-ddl-emitters-design.md` — P3-SQL-02..06 concrete DDL emitters design (approved with review decisions).

## Implementation plans (`docs/plans/`)

- `2026-10-22-p2-cli-01-implementation-plan.md` — P2-CLI-01 implementation plan.
- `2026-10-22-p2-diff-06-rename-annotations.md` — P2-DIFF-06 implementation plan; filename rename pending (no inbound links found).
- `2026-10-22-p3-risk-01-implementation-plan.md` — P3-RISK-01 implementation plan.
- `2026-10-23-p3-sql-01-emitter-dispatcher-implementation-plan.md` — P3-SQL-01 implementation plan.
- `2026-10-22-pgschemadiff-status-roadmap.md` — Vietnamese status analysis and roadmap plan (partly superseded by current state files).

## UI design reference (`docs/ui-design/`)

- `reference/` — original UI source bundle; unchanged.
- `reference/design-chat.md` — design conversation and decisions.
- `pgschemadiff.zip` — original reference archive; unchanged.

## Archive (`docs/archive/`)

- Archive directory is ready but currently empty. `PROGRESS.md`, `REVIEW.md`, and `docs/migration.md` remain at their original paths because Windows ACLs block the required `git mv` operations.

## Naming convention

- Specs are approved designs: `YYYY-MM-DD-<task>-design.md`.
- Plans are implementation plans: `YYYY-MM-DD-<task>-implementation-plan.md`.
