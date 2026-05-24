# TASK_INDEX.md — pgschemadiff

_Last updated: 2026-05-24_

## Priority Queue

### P0 — BLOCKERS (must complete before any other work)

#### T001 — Restructure into `src/pgschemadiff/` package layout
**Status**: TODO  
**Depends on**: nothing  
**Blocks**: everything

Move files from project root into the proper package hierarchy:

```
src/pgschemadiff/
├── __init__.py
├── __main__.py
├── domain/
│   ├── __init__.py
│   └── models/
│       ├── __init__.py          (exports Profile, ConnectionInfo)
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
        └── profile_detail.py    (currently unused, keep for later)
```

Also move `config/profiles.yaml` to `config/profiles.yaml` (create `config/` dir).
The flat files at root (`app.py`, `home.py`, etc.) become dead — delete after migration.

**Acceptance**: `uv run python -m pgschemadiff --help` exits 0.

---

#### T002 — Create `confirm_dialog.py`
**Status**: TODO  
**Depends on**: T001 (place at `src/pgschemadiff/presentation/widgets/confirm_dialog.py`)  
**Blocks**: T004, all UI tests

`home.py` imports `ConfirmDialog` but the file is absent. Implement a Textual
`ModalScreen` with title, body text, "Delete" (danger) and "Cancel" buttons.
Returns `True` on confirm, `False`/`None` on cancel.

**Acceptance**: `d` key in HomeScreen opens modal; confirming removes profile from list.

---

#### T003 — Wire `pyproject.toml` and verify install
**Status**: TODO  
**Depends on**: T001  
**Blocks**: T004

After restructure, verify:
- `[tool.hatch.build.targets.wheel] packages = ["src/pgschemadiff"]` is correct
- `uv sync && uv run python -m pgschemadiff --version` (or `--help`) works
- `profiles.yaml` default path resolves correctly from installed entry point

---

### P1 — HIGH (immediate value, unblock testing)

#### T004 — Add smoke tests with pytest-asyncio
**Status**: TODO  
**Depends on**: T001, T002, T003

Create `tests/` with:
- `tests/conftest.py` — shared fixtures
- `tests/test_profile.py` — Profile/ConnectionInfo unit tests (Pydantic validation)
- `tests/test_yaml_loader.py` — load/save round-trip with tmp_path
- `tests/test_home_screen.py` — Textual Pilot: mount app, navigate list, delete profile

**Acceptance**: `uv run pytest` exits 0 with ≥10 passing tests.

---

#### T005 — Add `ruff` and `mypy` CI baseline
**Status**: TODO  
**Depends on**: T001

Configure:
- `pyproject.toml` `[tool.ruff]` section with sensible rules
- `pyproject.toml` `[tool.mypy]` section (strict for domain, lenient for presentation)
- Verify `uv run ruff check src/` and `uv run mypy src/` pass on existing code

---

### P2 — CORE FEATURES (roadmap phase 2)

#### T006 — `screens/comparing.py` — async compare screen
**Status**: TODO  
**Depends on**: T001, T002, T003  
**Blocks**: T007, T009

Textual `Screen` that:
1. Receives a `Profile`
2. Shows a progress bar + status line
3. Runs `inspector.introspect(source)` and `inspector.introspect(target)` via Textual `Worker`
4. On completion pushes `DiffExplorerScreen`; on error shows error modal

---

#### T007 — `infrastructure/postgres/inspector.py`
**Status**: TODO  
**Depends on**: T001  
**Blocks**: T006

Class `SchemaInspector(conn: ConnectionInfo)` with method:
```python
async def introspect(schemas: list[str]) -> SchemaSnapshot
```
Queries: `pg_catalog.pg_tables`, `pg_catalog.pg_class`, `pg_catalog.pg_attribute`,
`pg_catalog.pg_indexes`, `pg_catalog.pg_constraint`.

`SchemaSnapshot` is a Pydantic model (frozen) representing all objects in the
given schemas. Keep it agnostic of diff logic.

**Note**: `psycopg[binary,pool]` is already in `pyproject.toml`.

---

#### T008 — `domain/diff/comparator.py`
**Status**: TODO  
**Depends on**: T007  
**Blocks**: T009, T010

`compare(source: SchemaSnapshot, target: SchemaSnapshot) -> DiffResult`

`DiffResult` contains lists of:
- Tables added / removed / modified (column adds/drops/type changes)
- Indexes added / removed
- Constraints added / removed

---

#### T009 — `screens/diff_explorer.py`
**Status**: TODO  
**Depends on**: T006, T008

Textual `Screen` with Tree widget showing `DiffResult`. Three visual categories:
added (green), removed (red), modified (yellow). Selecting a node previews
the SQL for that object.

---

#### T010 — `domain/migration/generator.py`
**Status**: TODO  
**Depends on**: T008

`generate(diff: DiffResult, direction: Literal["up","down"]) -> str`

Returns a single SQL migration script. Pure function, no DB connection needed.

---

### P3 — POLISH

#### T011 — `screens/sql_preview.py`
**Status**: TODO  
**Depends on**: T010

`RichLog` widget with SQL syntax highlight (via `rich` `Syntax`). Includes
copy-to-clipboard action and export-to-file action.

#### T012 — New/Edit profile modal
**Status**: TODO  
**Depends on**: T001, T002

Wire up the `n` (new) and `e` (edit) key bindings in HomeScreen with a form modal
backed by `ProfileLoader.save()`.

#### T013 — Test connection action
**Status**: TODO  
**Depends on**: T007

`btn-test` in HomeScreen: attempt `SELECT 1` on both source and target, show
latency + success/error notification.

---

## Dependency Graph

```
T001 ──► T002 ──► T004
    └──► T003 ──► T004
    └──► T005
    └──► T006 ──► T009
    └──► T007 ──► T006
              └──► T008 ──► T009
                        └──► T010 ──► T011
    └──► T012
    └──► T013 (needs T007)
```

## Completed

_(none yet)_
