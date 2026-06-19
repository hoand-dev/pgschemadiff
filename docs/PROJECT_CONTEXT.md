# PROJECT_CONTEXT — pgschemadiff

> Live state of the project. Update this file as a sibling of every PR that
> changes the phase status, finishes a milestone, or adds an ADR. Read me at
> the start of every chat session.

Last updated: **2026-06-19** — P1-TEST-01 complete: session-scoped pg18 container fixture + connection smoke test.

---

## Snapshot

| Field | Value |
|---|---|
| Current phase | **Phase 0** — Stabilization |
| Completed milestones | _none yet_ |
| Next milestone | **M0** — CI green on empty project |
| Working branch | `claude/stoic-pascal-LOygS` |
| Python version | 3.13 |
| PostgreSQL target | 18 ↔ 18 (MVP) |
| Package manager | uv 0.8+ |
| Source layout | `src/` |

## Active task

Backend track: `P1-INFRA-05` (`PgCatalogInspector` for MVP-A). P1-INFRA-01..04
are complete. The full domain model layer (`P1-DOM-02..09`) is now complete, so
`P1-DOM-08` ports are available for `P1-INFRA-05`.

TUI track unblocked at the shell level by `P4-TUI-01`. Remaining
`P4-TUI-02..08` are blocked on the Phase 1-3 data they each consume.

## Done in current session

- `P1-TEST-01` — `tests/integration/conftest.py`: session-scoped `postgres_container` fixture (postgres:18-alpine), `pg_admin_dsn` (session), `pg_test_dsn` (function-scoped — creates/drops `test_<uuid>` DB with FORCE). `tests/integration/test_connection.py`: smoke test asserting PostgreSQL 18 version string. Implements ADR-0010 strategy 3. Both ruff and mypy strict pass; 283 unit tests unaffected.

- `P1-INFRA-01` — `infrastructure/postgres/pool.py`: `Pool` async context-manager wrapper around `psycopg_pool.AsyncConnectionPool`; `ConnectionPool` type alias; `acquire()` async context manager; 14 unit tests (mocked, no live DB).
- `P1-INFRA-02` — `catalog/tables.sql` + `catalog/columns.sql`: pg_catalog queries for user tables/partitions and columns (identity/generated/collation support).
- `P1-INFRA-03` — `catalog/indexes.sql` + `catalog/constraints.sql`: pg_catalog queries for all indexes (btree/hash/gist/gin/brin/exclusion/PK) and constraints (PK/unique/check/FK/exclusion).
- `P1-INFRA-04` — `catalog/extensions.sql` + `catalog/schemas.sql`: pg_available_extensions and pg_namespace queries.
- All SQL files loaded via `importlib.resources`; 60 new tests (46 structural + 6 snapshot + 14 pool); all 328 tests pass.

- `P0-ENV-01` — `pyproject.toml` PEP 621 with all runtime + dev deps
- `P0-ENV-02` — `uv.lock` generated; `.python-version` set to 3.13
- `P0-ENV-03` — Textual pinned (`>=0.83`)
- `P0-INFRA-01` — ruff config (lint + format)
- `P0-INFRA-02` — mypy strict config
- `P0-INFRA-03` — import-linter contracts (4 contracts, all KEPT)
- `P0-INFRA-04` — pytest + asyncio + benchmark + syrupy + hypothesis configured
- `P0-INFRA-05` — pre-commit config
- `P0-ARCH-01` — Clean Architecture skeleton (`domain` / `application` / `infrastructure` / `presentation` / `shared`)
- `P0-LOG-01` — structlog baseline (`shared/logging.py`)
- `P0-CI-01` — GitHub Actions: lint + typecheck + unit-test
- `P0-CI-02` — GitHub Actions: integration job with `postgres:18`
- `P0-DOC-01` — this file
- `P0-DOC-02` — `docs/ROADMAP.md`
- `P0-DOC-03` — `docs/adr/0000-template.md`
- `P0-QUAL-01` — smoke tests passing (5/5)
- `P1-DOM-01` — `domain/identity.py` with QualifiedName / ObjectRef / ObjectKind; 29 unit tests, domain coverage 100%. Note: field renamed `schema` → `namespace` to avoid `BaseModel.schema` shadow (rationale in module docstring).
- `P1-DOM-02..09` — full domain model layer: `column.py` (Column / IdentitySpec / generated cols), `constraint.py` (Pydantic discriminated union over PK / Unique / Check / FK / Exclusion, `kind` discriminator), `table.py` (Table aggregate + partition info, column-name + constraint-reference validation), `index.py` (Index + key columns / opclass / INCLUDE / predicate), `schema.py` + `extension.py`, `database.py` (top-level aggregate with ObjectRef/QualifiedName lookup helpers), `ports.py` (`SchemaInspector` / `MigrationWriter` runtime-checkable Protocols; `Database` import under `TYPE_CHECKING` to keep domain pure). 181 new unit tests (268 total). Domain re-exported from `domain/__init__.py`. `pyproject.toml`: domain per-file-ignore extended with `TC001-TC003` (Pydantic needs field-type imports at runtime).
- `P4-UX-01` — imported the user's claude.ai/design bundle into `docs/ui-design/reference/`; authored `docs/ui-design.md` as the Textual implementation contract (layout, theme tokens, vim bindings, screen specs).
- `P4-TUI-01` — TUI app shell: `PgsdApp` (`presentation/tui/app.py`), Catppuccin Mocha ↔ Latte switching, vim chord dispatcher (`gc/go/gd/gm/ga/gh/gs`, `gT`, `ZZ`), vim `:` command palette with stub parser, `?` help modal, 7 placeholder views, `pgsd tui` CLI command (also `pgsd` with no sub-command). 8 Pilot-driven unit tests passing.

## Blockers

- None.

## Known limitations / debt (running list)

- TUI design not yet provided by user → Phase 4 task breakdown is a placeholder
- Original Claude share-link transcript could not be machine-read (SPA) →
  user will paste the relevant decisions; until then, this PROJECT_CONTEXT is
  the source of truth.

## UI Design Decisions

_Awaiting user-provided summary. Will populate this section with screen flow,
key components, and Textual widget choices once the transcript is shared._

Placeholder screen flow (subject to user input):

```
Connection → Compare → DiffTree → SQLPreview → ApplyConfirm
```

## Decision log (cross-reference)

See `docs/adr/` for the full set. Numbered list:

- ADR-0001 Use uv as the package manager
- ADR-0002 Use psycopg 3 async
- ADR-0003 Pydantic v2 frozen models for domain
- ADR-0004 pg_catalog-only introspection (no pg_dump)
- ADR-0005 Clean Architecture, 4 layers, enforced by import-linter
- ADR-0006 Per-type Comparator + Visitor dispatcher for the diff engine
- ADR-0007 Explicit-annotation rename detection (no heuristic)
- ADR-0008 Multi-file migration output (up.sql / down.sql / manifest.json / ...)
- ADR-0009 Five-level risk model: SAFE / WARNING / DANGEROUS / DESTRUCTIVE / BLOCKED
- ADR-0010 Session-scoped Postgres container, per-test database
- ADR-0011 Typer for the CLI
- ADR-0012 REPEATABLE READ + pg_export_snapshot for consistent multi-connection reads

## Session bootstrap checklist (for the next AI engineering team session)

1. `git pull origin claude/stoic-pascal-LOygS`
2. Read this file (`docs/PROJECT_CONTEXT.md`)
3. Read `docs/ROADMAP.md` for phase status
4. Read `docs/TASKS.md` for the task board (single source of truth in-repo)
5. Read `.claude/agents/README.md` for the sub-agent roster + routing rules
6. `git log --oneline -20` to confirm real progress vs. claimed
7. Respond with: **Current State → Team Analysis → Next Best Action → Immediate Tasks**
8. Dispatch the next `[ ]` task (whose deps are `[x]`) to the right sub-agent — usually `backend-engineer`
