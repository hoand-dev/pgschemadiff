# pgschemadiff

> Compare PostgreSQL schemas, generate safe migrations, with an interactive TUI and a scriptable CLI.

**Status:** Pre-alpha. Phase 0 baseline + first slice of Phase 1 (domain identity) + Phase 4 TUI shell. See [`docs/ROADMAP.md`](docs/ROADMAP.md) and [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md).

## What it does

- Connect to two PostgreSQL 18 databases (or one DB and a target schema file)
- Introspect schemas via `pg_catalog` (async, consistent snapshot)
- Diff every object kind: tables, columns, indexes, constraints, foreign keys, views, materialized views, functions, procedures, sequences, enums, triggers, RLS policies, composite/domain types, extensions
- Classify each change by risk: `SAFE` / `WARNING` / `DANGEROUS` / `DESTRUCTIVE` / `BLOCKED`
- Generate ordered migration SQL (topologically sorted; non-transactional units split out)
- Apply migrations with per-unit transaction semantics and lock-timeout safety
- Drive everything from a Textual TUI or a `pgsd` CLI

## Quickstart

> The project is still being bootstrapped. The commands below describe the intended UX once Phase 1+ ships.

```bash
# install (Phase 5)
uv tool install pgschemadiff

# launch the TUI
pgsd                  # or: pgsd tui

# inspect a schema (Phase 1)
pgsd inspect postgresql://user:pass@host:5432/db > snapshot.json

# diff two databases (Phase 2)
pgsd diff postgresql://user:pass@host/src postgresql://user:pass@host/tgt

# generate a migration (Phase 3)
pgsd generate \
  --source postgresql://.../src \
  --target postgresql://.../tgt \
  --output ./migrations/

# apply (Phase 3)
pgsd apply ./migrations/20260523_120000_diff/
```

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

## Home screen prototype (legacy)

A standalone Home-screen prototype lives at the **repository root** (`app.py`, `home.py`, `profile.py`, `profile_detail.py`, `profile_item.py`, `yaml_loader.py`, `__main__.py`, `styles.tcss`, `profiles.yaml`). It pre-dates the Clean Architecture refactor and is preserved as a reference for the Connection-screen behaviour the user designed.

Run it directly:

```bash
PYTHONPATH=. python -m pgschemadiff           # uses the root-level __main__.py
# or
python app.py
```

It is **not** wired into the `pgsd` CLI. The Phase 4 task `P4-TUI-02 (ConnectionView)` will integrate its `Profile` / `ConnectionInfo` data model and the `profiles.yaml` loader into `src/pgschemadiff/{domain,infrastructure,presentation}/`. Until then the two trees coexist; new development goes under `src/pgschemadiff/`.

## License

MIT — see [LICENSE](LICENSE).
