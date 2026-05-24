# Progress

Tracks implementation status by phase. Updated as work lands.

---

## Phase 0 — Prototype (flat files at root)

> Goal: validate UX concepts before committing to the full package structure.

| Task | Status | Notes |
|------|--------|-------|
| Domain models (`Profile`, `ConnectionInfo`) | ✅ Done | Pydantic frozen, in `profile.py` |
| YAML loader (`ProfileLoader`) | ✅ Done | `load()` and `save()` in `yaml_loader.py` |
| Sample `profiles.yaml` (4 profiles) | ✅ Done | At repo root |
| Catppuccin Mocha theme (`styles.tcss`) | ✅ Done | |
| `PgSchemaDiffApp` (Textual App) | ✅ Done | `app.py` |
| `HomeScreen` — 2-pane layout | ✅ Done | `home.py` |
| Real-time detail panel on ↑↓ | ✅ Done | `on_list_view_highlighted` |
| Delete profile with modal confirm | ✅ Done | `action_delete_profile` + inline callback |
| Footer with auto key bindings | ✅ Done | Via `BINDINGS` |
| Status bar (profile count) | ✅ Done | `sub_title` update |
| CLI args + config path resolution | ✅ Done | `__main__.py` |
| `ProfileListItem` widget (2-line) | ✅ Done | `profile_item.py` |

**Gaps in the prototype (blocking runability):**

| Gap | Impact |
|-----|--------|
| `src/pgschemadiff/` package hierarchy missing | ❌ App cannot be imported/run |
| `confirm_dialog.py` missing | ❌ Import error at startup |
| `config/profiles.yaml` path mismatch | ⚠️ Must pass `--config profiles.yaml` manually |
| `profile_detail.py` unused (Textual workaround) | ℹ️ Dead code, not blocking |

---

## Phase 1 — Package reorganisation

> Goal: make the project installable and runnable as a proper Python package.
> See [`docs/migration.md`](docs/migration.md) for step-by-step instructions.

| Task | Status | Notes |
|------|--------|-------|
| Create `src/pgschemadiff/` hierarchy | ❌ Not started | |
| Add `__init__.py` files | ❌ Not started | |
| Move files with `git mv` | ❌ Not started | |
| Create `domain/models/__init__.py` re-export | ❌ Not started | |
| Create `confirm_dialog.py` | ❌ Not started | Extract from `home.py` |
| Move `profiles.yaml` → `config/profiles.yaml` | ❌ Not started | |
| `uv run mypy src/pgschemadiff` green | ❌ Not started | |
| App runs end-to-end | ❌ Not started | |
| Wire `n` (new profile) action | ❌ Not started | Form screen or modal |
| Wire `e` (edit profile) action | ❌ Not started | Form screen or modal |

---

## Phase 2 — PostgreSQL connectivity

> Goal: actually connect to real databases and extract schema information.

| Task | Status | Notes |
|------|--------|-------|
| `infrastructure/postgres/inspector.py` | ❌ Not started | psycopg `AsyncConnectionPool` |
| Query `pg_catalog` for tables | ❌ Not started | |
| Query `pg_catalog` for columns, types | ❌ Not started | |
| Query `pg_catalog` for indexes, constraints | ❌ Not started | |
| Query `pg_catalog` for views, functions | ❌ Not started | |
| Test connection button in HomeScreen | ❌ Not started | `#btn-test` already in layout |
| `screens/comparing.py` — loading screen | ❌ Not started | Worker async + ProgressBar |

---

## Phase 3 — Diff logic

> Goal: compare two schema snapshots and produce a structured diff.

| Task | Status | Notes |
|------|--------|-------|
| `domain/diff/comparator.py` | ❌ Not started | |
| Diff tables (added / removed / changed) | ❌ Not started | |
| Diff columns, types, nullability | ❌ Not started | |
| Diff indexes, constraints | ❌ Not started | |
| Diff views, functions | ❌ Not started | |
| Apply `ignore_patterns` filter | ❌ Not started | |
| Respect `schemas` list filter | ❌ Not started | |

---

## Phase 4 — TUI: Diff Explorer

> Goal: browse diff results interactively.

| Task | Status | Notes |
|------|--------|-------|
| `screens/diff_explorer.py` | ❌ Not started | Tree widget, 3-column layout |
| Navigate diff tree | ❌ Not started | |
| Select/deselect individual changes | ❌ Not started | |
| Show added / removed / changed with colour coding | ❌ Not started | |

---

## Phase 5 — SQL Migration Generator

> Goal: generate valid PostgreSQL SQL from selected diff items.

| Task | Status | Notes |
|------|--------|-------|
| `domain/migration/generator.py` | ❌ Not started | |
| `ALTER TABLE … ADD COLUMN` | ❌ Not started | |
| `ALTER TABLE … DROP COLUMN` | ❌ Not started | |
| `CREATE TABLE` / `DROP TABLE` | ❌ Not started | |
| `CREATE INDEX` / `DROP INDEX` | ❌ Not started | |
| `screens/sql_preview.py` | ❌ Not started | RichLog + SQL syntax highlight |
| Copy SQL to clipboard | ❌ Not started | |
| Export SQL to file | ❌ Not started | |

---

## Dependency readiness

| Dependency | In pyproject.toml | Used |
|------------|-------------------|------|
| `textual>=0.83.0` | ✅ | ✅ HomeScreen |
| `pydantic>=2.9.0` | ✅ | ✅ Profile / ConnectionInfo |
| `pyyaml>=6.0.2` | ✅ | ✅ ProfileLoader |
| `rich>=13.9.0` | ✅ | ❌ Not yet (planned: SqlPreviewScreen) |
| `psycopg[binary,pool]>=3.2.0` | ✅ | ❌ Not yet (planned: Phase 2) |
