# TASK_INDEX.md
_Last updated: 2026-05-24_

ID format: `T-NN` (sequential). Status: `TODO` · `IN_PROGRESS` · `DONE` · `BLOCKED`.
Priority: **P0** blocker · **P1** critical · **P2** important · **P3** nice-to-have.

---

## Execution Queue (ordered)

```
[ ] T-01  P0  Src layout restructure + confirm_dialog  ← START HERE
[ ] T-02  P0  .gitignore + CI workflow
[ ] T-03  P1  Test suite (unit + Pilot)
[ ] T-04  P1  ComparingScreen (async Worker + ProgressBar)
[ ] T-05  P2  DiffExplorerScreen (Tree widget, 3-column)
[ ] T-06  P2  SqlPreviewScreen (RichLog + SQL highlight)
[ ] T-07  P2  Domain diff model (DiffResult dataclass)
[ ] T-08  P3  PgCatalogInspector (real pg_catalog queries)
[ ] T-09  P3  DiffComparator (real diff logic)
[ ] T-10  P3  MigrationGenerator (ALTER TABLE / CREATE INDEX SQL)
```

---

## T-01 — Src layout restructure + confirm_dialog

**Status:** `TODO`  
**Priority:** P0 — BLOCKER (app cannot run, no other task can proceed)  
**Branch with prior work:** `claude/determined-goodall-KGag4` (complete implementation)  
**Estimated effort:** S (< 2h from scratch; cherry-pick if available)

### Shortcut: cherry-pick from `determined-goodall-KGag4`
```bash
git fetch origin claude/determined-goodall-KGag4
git cherry-pick origin/claude/determined-goodall-KGag4
```
This brings in: full src layout, all `__init__.py`, `confirm_dialog.py`, updated
`pyproject.toml` (ruff/mypy config, pytest config, types-PyYAML), `uv.lock`, `.gitignore`.

### Manual implementation steps (if cherry-pick not used)
1. Create directory tree:
   ```
   src/pgschemadiff/
     __init__.py
     __main__.py
     domain/__init__.py
     domain/models/__init__.py       ← re-export Profile, ConnectionInfo
     domain/models/profile.py
     infrastructure/__init__.py
     infrastructure/config/__init__.py
     infrastructure/config/yaml_loader.py
     presentation/__init__.py
     presentation/app.py             ← fix CSS_PATH to use Path(__file__).parent
     presentation/styles.tcss
     presentation/screens/__init__.py
     presentation/screens/home.py
     presentation/widgets/__init__.py
     presentation/widgets/profile_item.py
     presentation/widgets/profile_detail.py
     presentation/widgets/confirm_dialog.py  ← NEW (see spec below)
   config/
     profiles.yaml
   ```
2. Move each root-level file to its target (content unchanged, except CSS_PATH fix).
3. Create all `__init__.py` files (empty or with `__all__` re-exports).
4. Write `confirm_dialog.py` — `ModalScreen` with:
   - Constructor: `title: str`, `body: str`
   - Two buttons: "Delete" → returns `True`, "Cancel" → returns `False`
   - Catppuccin Mocha styling matching `styles.tcss`
5. Fix `CSS_PATH` in `app.py`:
   ```python
   CSS_PATH = Path(__file__).parent / "styles.tcss"
   ```
6. Delete root-level flat files (they become dead code).
7. Update `pyproject.toml`: add ruff/mypy/pytest config, `types-PyYAML` to dev deps.
8. Run `uv sync` to generate `uv.lock`.
9. Smoke-test: `uv run python -m pgschemadiff --config config/profiles.yaml`

### Acceptance criteria
- `uv run python -m pgschemadiff --config config/profiles.yaml` launches with no import errors
- 4 profiles appear in the list
- `d` opens delete modal, confirming deletes item
- No root-level source files remain

---

## T-02 — .gitignore + CI workflow

**Status:** `TODO`  
**Priority:** P0  
**Depends on:** T-01 (needs src layout to exist for paths to be correct)  
**Branch with prior work:** `claude/determined-goodall-KGag4` (complete `.gitignore` + `.github/workflows/ci.yml`)

### .gitignore (standard Python)
```
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
.mypy_cache/
.ruff_cache/
.pytest_cache/
*.egg
```

### CI workflow (`.github/workflows/ci.yml`)
- Triggers: push to `main` and `claude/**`, PR to `main`
- Jobs: `lint` (ruff check, ruff format, mypy) + `test` (pytest)
- Python 3.11 (or 3.13 — match `pyproject.toml` `requires-python`)
- Use `uv sync --all-groups` + `astral-sh/setup-uv@v4`

### Acceptance criteria
- `ruff check src/ tests/` passes
- `mypy src/` passes
- `pytest` passes
- CI green on push

---

## T-03 — Test suite

**Status:** `TODO`  
**Priority:** P1  
**Depends on:** T-01  
**Branch with prior work:** `claude/determined-goodall-KGag4` has partial tests

### Tests to write
1. `tests/test_models.py` — unit tests for `Profile`, `ConnectionInfo` (pure domain, no Textual)
2. `tests/test_yaml_loader.py` — `ProfileLoader.load()` with tmp YAML fixture (pytest tmp_path)
3. `tests/test_home_screen.py` — Textual Pilot tests:
   - App boots with 4 profiles
   - ↑↓ navigation updates detail pane
   - `d` opens confirm modal; confirm deletes item; count drops to 3
   - `esc` closes modal without deleting; count stays at 4

### Acceptance criteria
- `pytest -v` passes all tests
- Tests run in CI (T-02)

---

## T-04 — ComparingScreen

**Status:** `TODO`  
**Priority:** P1  
**Depends on:** T-01  
**File:** `src/pgschemadiff/presentation/screens/comparing.py`

### Spec
- Shown when user presses Enter/Compare on a profile in HomeScreen
- Layout: header title, `ProgressBar`, `RichLog` (status messages), Cancel button
- Use Textual `Worker` (async) to simulate/stub DB inspection steps
- On completion → push `DiffExplorerScreen` (stub: just a `notify` is fine)
- On Cancel → pop back to `HomeScreen`
- Wire `_start_compare()` in `home.py` to push this screen instead of `notify()`

### Acceptance criteria
- Pressing Enter on a profile pushes ComparingScreen
- Progress bar animates across 3-5 stub steps (e.g. "Connecting…", "Inspecting source…", "Inspecting target…", "Computing diff…")
- Cancel button pops back to HomeScreen
- Completion pushes next screen (stub OK)

---

## T-05 — DiffExplorerScreen

**Status:** `TODO`  
**Priority:** P2  
**Depends on:** T-04 (needs screen navigation wired), T-07 (needs DiffResult model)  
**File:** `src/pgschemadiff/presentation/screens/diff_explorer.py`

### Spec
- Three-column layout:
  - Left: source schema `Tree` widget
  - Middle: diff status badges (added/removed/changed)
  - Right: detail of selected diff item
- Key binding `s` → push `SqlPreviewScreen`
- Initially populated with stub `DiffResult` data

### Acceptance criteria
- Screen renders without errors
- Navigating tree updates right panel
- `s` pushes SqlPreviewScreen

---

## T-06 — SqlPreviewScreen

**Status:** `TODO`  
**Priority:** P2  
**Depends on:** T-05  
**File:** `src/pgschemadiff/presentation/screens/sql_preview.py`

### Spec
- `RichLog` widget showing generated migration SQL with syntax highlighting
- Key bindings: `c` copy to clipboard, `w` write to file (prompt for path)
- Wire `domain/migration/generator.py` stub returning placeholder SQL

### Acceptance criteria
- SQL displays with highlighting
- `w` prompts for path and writes file

---

## T-07 — Domain diff model

**Status:** `TODO`  
**Priority:** P2  
**Depends on:** T-01  
**File:** `src/pgschemadiff/domain/diff/comparator.py`

### Spec
- `DiffResult` dataclass:
  - `profile_name: str`
  - `added: list[str]`
  - `removed: list[str]`
  - `changed: list[tuple[str, str]]`
- Stub `compare(source: ..., target: ...) -> DiffResult` returning dummy data
- Real implementation deferred to T-09

### Acceptance criteria
- Importable from `pgschemadiff.domain.diff.comparator`
- Stub returns deterministic dummy data for testing

---

## T-08 — PgCatalogInspector (real DB queries)

**Status:** `TODO`  
**Priority:** P3  
**Depends on:** T-07  
**File:** `src/pgschemadiff/infrastructure/postgres/inspector.py`

### Spec
- Query `pg_catalog` / `information_schema` to extract:
  - Tables, columns (types, defaults, nullable)
  - Indexes (method, columns, predicate)
  - Constraints (PK, unique, FK, check)
  - Views, functions (deferred MVP-B)
- Use `psycopg[binary,pool]` (already in deps)
- Integration tests use Docker PostgreSQL

---

## T-09 — DiffComparator (real logic)

**Status:** `TODO`  
**Priority:** P3  
**Depends on:** T-07, T-08

Replace stub in `comparator.py` with real column/table/index/constraint comparison.

---

## T-10 — MigrationGenerator

**Status:** `TODO`  
**Priority:** P3  
**Depends on:** T-09

Generate safe `ALTER TABLE`, `CREATE INDEX CONCURRENTLY`, `ADD CONSTRAINT ... NOT VALID`
SQL from `DiffResult`. Write to file.

---

## Cross-cutting notes

- **Textual bug**: Do not extend `Vertical`/`Container` with complex `compose` — inline into `Screen` directly. Already worked around in `home.py`.
- **psycopg**: Listed in deps but unused until T-08.
- **stoic-pascal-LOygS branch**: Contains a much deeper Clean Architecture re-design (CLI-first, 12 ADRs, 40+ tasks). Treat as aspirational reference for T-08+, not as an immediate merge target — it diverges significantly from the TUI-first roadmap.
