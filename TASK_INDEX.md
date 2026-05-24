# TASK_INDEX.md — pgschemadiff execution queue

_Last updated: 2026-05-24_

Legend: `[ ]` todo · `[~]` in-progress · `[x]` done · `[!]` blocked

---

## Priority 1 — Critical (app cannot run)

### T-01 · Restructure into proper package layout
**Status:** `[ ]`
**Effort:** Medium
**Blocks:** everything else

The source files must be reorganised to match the package layout declared in `pyproject.toml`
and used by the import statements. Target structure:

```
src/pgschemadiff/
├── __init__.py
├── __main__.py
├── domain/
│   ├── __init__.py
│   └── models/
│       ├── __init__.py          # re-exports Profile, ConnectionInfo
│       └── profile.py
├── infrastructure/
│   ├── __init__.py
│   └── config/
│       ├── __init__.py
│       └── yaml_loader.py
└── presentation/
    ├── __init__.py
    ├── app.py
    ├── styles.tcss
    ├── screens/
    │   ├── __init__.py
    │   └── home.py
    └── widgets/
        ├── __init__.py
        ├── profile_item.py
        ├── profile_detail.py
        └── confirm_dialog.py    ← must be created (see T-02)

config/
└── profiles.yaml                ← move from root profiles.yaml
```

Actions:
- Create directory tree with `__init__.py` stubs
- Move each root `.py` file to correct subpath (update relative CSS_PATH in `app.py`)
- Move `profiles.yaml` to `config/profiles.yaml`
- Verify `uv sync && uv run python -m pgschemadiff` launches without error

---

### T-02 · Create missing `confirm_dialog.py`
**Status:** `[ ]`
**Effort:** Small
**Depends on:** T-01 (need the directory first)
**Blocks:** HomeScreen delete action (currently crashes if triggered)

Implement `ConfirmDialog(ModalScreen[bool])` — a simple modal with title, body text,
"Cancel" and "Delete" (danger-styled) buttons. Yields `True` on confirm, `False`/`None`
on cancel. Already called correctly from `home.py`; just needs to exist.

---

## Priority 2 — Tests & quality gate

### T-03 · Bootstrap test suite
**Status:** `[ ]`
**Effort:** Small
**Depends on:** T-01, T-02

- Add `tests/` directory with `conftest.py`
- Write smoke test: app loads, HomeScreen mounts, 4 profiles render
- Write delete-flow test: pilot presses `d`, confirm dialog appears, confirm deletes item
- Tool: `pytest-asyncio` + `textual.testing.Pilot` (already in dev deps)
- Add `pytest.ini` or `[tool.pytest.ini_options]` in `pyproject.toml`

---

### T-04 · Add GitHub Actions CI
**Status:** `[ ]`
**Effort:** Small
**Depends on:** T-03

- `.github/workflows/ci.yml`: Python 3.13, `uv sync`, `uv run pytest`, `uv run ruff check`
- Runs on push + pull_request to main

---

## Priority 3 — Feature roadmap (in dependency order)

### T-05 · `infrastructure/postgres/inspector.py` — pg_catalog queries
**Status:** `[ ]`
**Effort:** Large
**Depends on:** T-01
**Required by:** T-07

Async class `SchemaInspector` using `psycopg` (already in deps):
- Connect via DSN from `ConnectionInfo.dsn()`
- Query `pg_catalog` for: tables, columns, constraints, indexes, sequences, views, functions
- Return typed dataclasses/Pydantic models representing the raw schema snapshot

---

### T-06 · `domain/diff/comparator.py` — diff logic
**Status:** `[ ]`
**Effort:** Large
**Depends on:** T-05 (needs schema snapshot types)
**Required by:** T-07, T-08

Pure domain — no Textual, no psycopg:
- `compare(source_schema, target_schema) -> DiffResult`
- `DiffResult`: categorised sets — added/removed/altered tables, columns, indexes, etc.
- Structured enough for Tree widget in T-08 and SQL generation in T-09

---

### T-07 · `screens/comparing.py` — loading screen
**Status:** `[ ]`
**Effort:** Medium
**Depends on:** T-05

`ComparingScreen(profile: Profile)`:
- Shown after user presses Enter on a profile
- Async `Worker` calls `SchemaInspector` for source + target in parallel
- `ProgressBar` widget updates as each stage completes
- On success: push `DiffExplorerScreen`; on error: show error notification, pop back

Wire up `_start_compare()` in `home.py` to push this screen.

---

### T-08 · `screens/diff_explorer.py` — 3-column diff tree
**Status:** `[ ]`
**Effort:** Large
**Depends on:** T-06, T-07

`DiffExplorerScreen(diff: DiffResult)`:
- Left pane: `Tree` widget with schema objects grouped by type
- Middle pane: detail of selected diff item (before/after)
- Right pane: will show generated SQL (calls T-09)
- Key `p` to push `SqlPreviewScreen`

---

### T-09 · `domain/migration/generator.py` — generate migration SQL
**Status:** `[ ]`
**Effort:** Large
**Depends on:** T-06

`generate_migration(diff: DiffResult) -> str`:
- Produces idempotent `ALTER TABLE`, `CREATE TABLE`, `DROP`, etc.
- Handles ordering: dependencies resolved so FK targets created before FK columns

---

### T-10 · `screens/sql_preview.py` — SQL preview
**Status:** `[ ]`
**Effort:** Medium
**Depends on:** T-09

`SqlPreviewScreen(sql: str)`:
- `RichLog` with syntax highlight (Rich SQL lexer via Textual integration)
- Key `c` to copy to clipboard, `s` to save to file
- Key `Esc` to return to diff explorer

---

## Execution queue (next targets)

1. **T-01** — fix package structure (unblocks everything)
2. **T-02** — create `confirm_dialog.py` (completes HomeScreen)
3. **T-03** — bootstrap tests (establishes quality gate)
4. **T-04** — add CI (makes branch mergeable safely)
5. **T-05 + T-06** — backend foundation (parallelisable after T-01)
6. **T-07** — comparing screen (wires backend to UI)
7. **T-08 + T-09** — diff explorer + SQL generator (parallelisable)
8. **T-10** — SQL preview screen

---

## Dependency graph

```
T-01 ──► T-02 ──► T-03 ──► T-04
  │
  ├──► T-05 ──► T-06 ──► T-08
  │      │        │
  │      └──► T-07  └──► T-09 ──► T-10
  │
  └── (app runnable)
```
