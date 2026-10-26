# pgschemadiff

> Compare PostgreSQL schemas, generate safe migrations, with an interactive TUI and a scriptable CLI.

**Status:** Phase 0 done except P0-CI-03; Phase 1 feature shipped (P1-TEST-02 needs-human, benchmark unmeasured); Phase 2 complete (M2 unit-level); Phase 3a in progress, P3-SQL-02 next; TUI shell/views use mock data. See [`docs/ROADMAP.md`](docs/ROADMAP.md) and [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md).

## What it does

- Connect to two PostgreSQL 18 databases (or one DB and a target schema file)
- Introspect schemas via `pg_catalog` (async, consistent snapshot)
- Diff every object kind: tables, columns, indexes, constraints, foreign keys, views, materialized views, functions, procedures, sequences, enums, triggers, RLS policies, composite/domain types, extensions
- Classify each change by risk: `SAFE` / `WARNING` / `DANGEROUS` / `DESTRUCTIVE` / `BLOCKED`
- Generate ordered migration SQL (topologically sorted; non-transactional units split out)
- Apply migrations with per-unit transaction semantics and lock-timeout safety
- Drive everything from a Textual TUI or a `pgsd` CLI

## Installation

```bash
uv tool install pgschemadiff
# or
pipx install pgschemadiff
```

## Quickstart

> `pgsd inspect`, `pgsd diff`, `pgsd generate` and `pgsd apply` cover schemas, extensions, tables, columns, indexes, constraints, sequences, enum/composite/domain types, functions, procedures, views, materialized views, triggers and RLS policies. The TUI runs the same pipeline against your profiles.

```bash
# launch the TUI
pgsd                  # or: pgsd tui

# inspect a schema
pgsd inspect postgresql://user:pass@host:5432/db > snapshot.json

# diff current (source) against desired (target)
pgsd diff postgresql://user:pass@host/current postgresql://user:pass@host/desired
pgsd diff postgresql://user:pass@host/current postgresql://user:pass@host/desired --format summary --max-risk dangerous

# generate a migration bundle that moves current to desired
# (prints the bundle directory; --max-risk defaults to dangerous)
pgsd generate postgresql://.../current postgresql://.../desired --out ./migrations/

# preview, then apply it to the current database
pgsd apply ./migrations/20260523_120000_diff/ postgresql://.../current --dry-run
pgsd apply ./migrations/20260523_120000_diff/ postgresql://.../current
# destructive units need --yes (or interactive confirmation)
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (including `diff` with changes and no gate) |
| 1 | Runtime failure: connection, inspection, comparison, writing |
| 2 | Usage or policy: bad option/file, risk gate exceeded, invalid bundle, destructive not approved, BLOCKED bundle |
| 3 | Apply failed or was cancelled after it started |

## Development

```bash
# requires Python 3.13 and uv 0.8+
uv sync --extra dev

# run the test suite
uv run pytest

# lint + format
uv run ruff check .
uv run ruff format .

# type-check
uv run mypy src/

# architecture enforcement
uv run lint-imports

# launch the TUI
uv run pgsd tui
```

## Architecture

Clean Architecture, 4 layers, enforced by `import-linter`:

```
presentation/   ← Textual TUI, typer CLI
infrastructure/ ← psycopg async, pg_catalog queries, file IO
application/    ← use cases: CompareSchemas, GenerateMigration, ApplyMigration
domain/         ← pure Pydantic models, no IO
```

See [`docs/architecture.md`](docs/architecture.md) and [`docs/adr/`](docs/adr/) for the decision log.

## License

MIT — see [LICENSE](LICENSE).
