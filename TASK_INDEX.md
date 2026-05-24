# TASK_INDEX.md
_Last updated: 2026-05-24_

---

## Priority 1 — BLOCKER: Restructure into proper `src` layout

**Status:** `TODO`
**Blocks:** everything else — app cannot run or be packaged

**Work:**
1. Create the full directory tree:
   ```
   src/pgschemadiff/
     __init__.py
     __main__.py
     domain/
       __init__.py
       models/
         __init__.py       ← re-export Profile, ConnectionInfo
         profile.py
     infrastructure/
       __init__.py
       config/
         __init__.py
         yaml_loader.py
     presentation/
       __init__.py
       app.py
       styles.tcss
       screens/
         __init__.py
         home.py
       widgets/
         __init__.py
         profile_item.py
         profile_detail.py
         confirm_dialog.py   ← NEW (modal not yet in repo)
   config/
     profiles.yaml
   ```
2. Move each root-level file to its target path (content unchanged except CSS_PATH fix in `app.py`).
3. Create all missing `__init__.py` files.
4. **Write `confirm_dialog.py`** — a Textual `ModalScreen` used by `home.py`:
   - Takes `title: str`, `body: str`
   - Two buttons: "Delete" (returns `True`) and "Cancel" (returns `False`)
   - Styled to match Catppuccin Mocha theme
5. Fix `CSS_PATH` in `app.py` → relative path resolves correctly from package (use `Path(__file__).parent / "styles.tcss"`).
6. Delete the now-redundant root-level flat files.
7. Smoke-test: `uv sync && uv run python -m pgschemadiff --config config/profiles.yaml`

---

## Priority 2 — Add test infrastructure

**Status:** `TODO`
**Depends on:** Priority 1 (must have working package first)

**Work:**
1. Create `tests/` directory with `__init__.py`.
2. Write `tests/test_models.py` — unit tests for `Profile`, `ConnectionInfo` (no Textual needed).
3. Write `tests/test_yaml_loader.py` — test `ProfileLoader.load()` with a tmp YAML fixture.
4. Write `tests/test_home_screen.py` — Textual Pilot test:
   - App boots, list has 4 items
   - ↑↓ navigation updates detail pane
   - `d` opens confirm modal; confirm deletes item
   - `esc` closes modal without deleting
5. Add `pytest.ini` or `[tool.pytest.ini_options]` in `pyproject.toml`.

---

## Priority 3 — CI with GitHub Actions

**Status:** `TODO`
**Depends on:** Priority 2

**Work:**
1. Create `.github/workflows/ci.yml`:
   - Trigger on push/PR to `main`
   - Python 3.13 + `uv sync`
   - Run `ruff check src tests`
   - Run `mypy src`
   - Run `pytest`
2. Add `ruff` config to `pyproject.toml` (`[tool.ruff]` with sensible defaults).
3. Add `mypy` config (`[tool.mypy]`, strict mode).

---

## Priority 4 — `screens/comparing.py`

**Status:** `TODO`
**Depends on:** Priority 1

**Screen:** Shown when user triggers Compare from HomeScreen.

**Work:**
1. `src/pgschemadiff/presentation/screens/comparing.py`
2. Layout: title bar, animated ProgressBar, status log (RichLog), Cancel button.
3. Use Textual `Worker` (async) to simulate/stub DB inspection.
4. On success → push `DiffExplorerScreen` (stub OK for now).
5. On cancel → pop back to HomeScreen.
6. Wire `_start_compare()` in `home.py` to push this screen.

---

## Priority 5 — `screens/diff_explorer.py`

**Status:** `TODO`
**Depends on:** Priority 4 (needs diff data structure)

**Screen:** Three-column diff view.

**Work:**
1. Left panel: source schema tree (Textual `Tree`)
2. Middle panel: diff status (added/removed/changed badges)
3. Right panel: detail of selected diff item
4. Key: `s` → push `SqlPreviewScreen`
5. Define `DiffResult` dataclass in `domain/diff/comparator.py` (stub with dummy data for now).

---

## Priority 6 — `screens/sql_preview.py`

**Status:** `TODO`
**Depends on:** Priority 5

**Screen:** SQL migration preview.

**Work:**
1. `RichLog` widget showing generated SQL with syntax highlighting.
2. Key: `c` copy to clipboard, `w` write to file.
3. Wire `domain/migration/generator.py` stub returning placeholder SQL.

---

## Priority 7 — Real PostgreSQL integration

**Status:** `TODO`
**Depends on:** Priorities 4–6 (UI scaffolding complete)

**Work:**
1. `infrastructure/postgres/inspector.py` — query `pg_catalog` / `information_schema`:
   - List schemas, tables, columns, indexes, constraints, views, functions.
2. `domain/diff/comparator.py` — real diff logic producing `DiffResult`.
3. `domain/migration/generator.py` — generate `ALTER TABLE`, `CREATE INDEX`, etc.
4. Integration tests using Docker PostgreSQL (optional, separate workflow).

---

## Execution Queue (ordered)

```
[ ] P1 — src layout restructure + confirm_dialog.py
[ ] P2 — test suite
[ ] P3 — CI workflow
[ ] P4 — ComparingScreen
[ ] P5 — DiffExplorerScreen
[ ] P6 — SqlPreviewScreen
[ ] P7 — Real DB integration
```
