# TASK_INDEX.md — pgschemadiff

> Last updated: 2026-05-24  
> Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

---

## Priority Queue (ordered by dependency + value)

| # | ID | Title | Est. | Status | Depends on |
|---|---|---|---|---|---|
| 1 | TASK-001 | Scaffold proper package structure | 45 min | [ ] | — |
| 2 | TASK-002 | Implement ConfirmDialog widget | 30 min | [ ] | TASK-001 |
| 3 | TASK-006 | PostgreSQL schema inspector | 90 min | [ ] | TASK-001 |
| 4 | TASK-005 | Wire "Test Connection" button | 45 min | [ ] | TASK-001, TASK-006 |
| 5 | TASK-003 | Wire "New Profile" form screen | 60 min | [ ] | TASK-001, TASK-002 |
| 6 | TASK-004 | Wire "Edit Profile" form screen | 45 min | [ ] | TASK-003 |
| 7 | TASK-007 | Schema diff comparator | 60 min | [ ] | TASK-006 |
| 8 | TASK-008 | SQL migration generator | 60 min | [ ] | TASK-007 |
| 9 | TASK-009 | Comparing screen (Worker + ProgressBar) | 75 min | [ ] | TASK-006, TASK-007 |
| 10 | TASK-010 | Diff Explorer screen (Tree, 3-column) | 90 min | [ ] | TASK-009, TASK-008 |
| 11 | TASK-011 | SQL Preview screen (RichLog + export) | 60 min | [ ] | TASK-010, TASK-008 |
| 12 | TASK-012 | Test suite & linting CI | 90 min | [ ] | TASK-007, TASK-008 |

---

## Tasks

### TASK-001 — Scaffold proper package structure
**Estimate:** 45 min  
**Status:** `[ ]`  
**Depends on:** —

**Context:**  
Root-level prototype files (`app.py`, `home.py`, `profile.py`, etc.) contain import paths referencing a `src/pgschemadiff/` package that doesn't exist on disk yet. `pyproject.toml` already declares `packages = ["src/pgschemadiff"]` and the entry point `pgschemadiff.__main__:main`. Nothing runs until the directory tree exists.

**Work:**
1. Create directory tree with empty `__init__.py` files:
   ```
   src/pgschemadiff/
   ├── __init__.py
   ├── __main__.py          ← content from root __main__.py
   ├── domain/
   │   ├── __init__.py
   │   └── models/
   │       ├── __init__.py  ← re-exports Profile, ConnectionInfo
   │       └── profile.py   ← content from root profile.py
   ├── infrastructure/
   │   ├── __init__.py
   │   └── config/
   │       ├── __init__.py
   │       └── yaml_loader.py  ← content from root yaml_loader.py
   └── presentation/
       ├── __init__.py
       ├── app.py           ← content from root app.py (fix CSS_PATH to Path(__file__).parent / "styles.tcss")
       ├── styles.tcss      ← content from root styles.tcss
       ├── screens/
       │   ├── __init__.py
       │   └── home.py      ← content from root home.py
       └── widgets/
           ├── __init__.py
           └── profile_item.py  ← content from root profile_item.py
   ```
2. Fix `CSS_PATH` in `app.py` to use `Path(__file__).parent / "styles.tcss"`.
3. Move `config/profiles.yaml` to `src/pgschemadiff/config/profiles.yaml`; update `__main__.py` fallback path to point there for dev.
4. Delete the now-superseded root-level prototype files.
5. Run `uv sync` then `uv run python -m pgschemadiff` — app must launch.

**Done conditions:**
- `uv run python -m pgschemadiff` starts the TUI without ImportError
- `uv run ruff check src/` exits 0
- No root-level `.py` prototype files remain (except `TASK_INDEX.md`)

**Affected files:**
- All root `.py` files (deleted after migration)
- `src/pgschemadiff/**` (created)
- `pyproject.toml` (verify, minor edits)

---

### TASK-002 — Implement ConfirmDialog widget
**Estimate:** 30 min  
**Status:** `[ ]`  
**Depends on:** TASK-001

**Context:**  
`home.py` imports `from pgschemadiff.presentation.widgets.confirm_dialog import ConfirmDialog` but this file does not exist. The delete action is currently broken.

**Work:**
1. Create `src/pgschemadiff/presentation/widgets/confirm_dialog.py`.
2. `ConfirmDialog(title: str, body: str)` is a `ModalScreen[bool | None]`:
   - Renders a centered panel with title, body text, a `Delete` / danger button, and a `Cancel` button.
   - `Delete` → `dismiss(True)`, `Cancel` / `Escape` → `dismiss(False)`.
3. Add CSS for the modal overlay to `styles.tcss` (dark backdrop, centered card).
4. Verify manually: press `d` on a profile, modal appears, `Cancel` closes it, `Delete` removes the profile from the list.

**Done conditions:**
- `home.py` delete flow completes without exception
- Modal renders centered with correct styling
- Escape and Cancel both dismiss without deleting

**Affected files:**
- `src/pgschemadiff/presentation/widgets/confirm_dialog.py` (new)
- `src/pgschemadiff/presentation/styles.tcss` (modal CSS added)

---

### TASK-003 — Wire "New Profile" form screen
**Estimate:** 60 min  
**Status:** `[ ]`  
**Depends on:** TASK-001, TASK-002

**Context:**  
Pressing `n` on the Home screen shows a warning "not wired yet". A form screen needs to collect all `Profile` fields and persist them.

**Work:**
1. Create `src/pgschemadiff/presentation/screens/profile_form.py`.
2. `ProfileFormScreen(profile: Profile | None = None)` — `None` means "new", a value means "edit".
3. Fields (use Textual `Input`): name, source host/port/database/user/password, target host/port/database/user/password, schemas (comma-separated string), ignore_patterns (comma-separated), mode (select: schema-only | data | full).
4. Validate on submit: name non-empty, ports are integers in 1–65535, schemas list non-empty.
5. On save → `dismiss(Profile(...))`, on cancel → `dismiss(None)`.
6. Wire `action_new_profile` in `HomeScreen`:
   - Push `ProfileFormScreen()`, await result.
   - If result is not None: append to `self._profiles`, append `ProfileListItem` to `ListView`, save via `ProfileLoader`, update subtitle.
7. Add TCSS for the form layout.

**Done conditions:**
- Pressing `n` opens the form
- Filling valid fields and submitting adds the profile to the list and persists to YAML (verified by restarting app)
- Submitting with an empty name shows an inline validation error
- Pressing Escape or Cancel returns to Home without changes

**Affected files:**
- `src/pgschemadiff/presentation/screens/profile_form.py` (new)
- `src/pgschemadiff/presentation/screens/home.py` (wire action)
- `src/pgschemadiff/presentation/styles.tcss` (form CSS)

---

### TASK-004 — Wire "Edit Profile" form screen
**Estimate:** 45 min  
**Status:** `[ ]`  
**Depends on:** TASK-003

**Context:**  
Pressing `e` or clicking the `Edit` button shows a notification "not wired yet". Reuse `ProfileFormScreen` from TASK-003 with pre-populated fields.

**Work:**
1. Push `ProfileFormScreen(profile=item.profile)` from `action_edit_profile` and the `btn-edit` button handler.
2. On result: replace the matching profile in `self._profiles` (by name), update the `ProfileListItem` label, save via `ProfileLoader`, refresh detail panel.
3. Ensure renaming a profile (changing the name field) works correctly — old entry is replaced, not duplicated.

**Done conditions:**
- Pressing `e` opens the form pre-filled with selected profile's data
- Saving changes updates the detail panel immediately and persists to YAML
- Cancel leaves the profile unchanged

**Affected files:**
- `src/pgschemadiff/presentation/screens/home.py` (wire action + button handler)
- `src/pgschemadiff/presentation/screens/profile_form.py` (pre-populate logic)

---

### TASK-005 — Wire "Test Connection" button
**Estimate:** 45 min  
**Status:** `[ ]`  
**Depends on:** TASK-001, TASK-006 (for connection DSN util)

**Context:**  
The `Test connection` button exists in the detail pane but does nothing. `psycopg[binary]` is already in `pyproject.toml`. This provides immediate feedback on whether credentials are valid.

**Work:**
1. Add `on_button_pressed` handler in `HomeScreen` for `#btn-test`.
2. Run a Textual `Worker` (thread, not async) that:
   - Calls `psycopg.connect(profile.source.dsn(), connect_timeout=5)`
   - Executes `SELECT version()`
   - Closes connection
   - Returns version string or exception message
3. While running: update the button label to `Testing…` and disable it.
4. On success: `notify(f"Source OK — {version}", severity="information")`.
5. On failure: `notify(f"Connection failed: {err}", severity="error")`.
6. Test both source and target (two workers, sequential or parallel — sequential is simpler).

**Done conditions:**
- Clicking `Test connection` shows a spinner-style label change
- A successful connection shows the PostgreSQL version string
- A bad host/port shows an error notification within ~6 seconds (timeout + overhead)

**Affected files:**
- `src/pgschemadiff/presentation/screens/home.py`

---

### TASK-006 — PostgreSQL schema inspector
**Estimate:** 90 min  
**Status:** `[ ]`  
**Depends on:** TASK-001

**Context:**  
The domain layer has no representation of database schema objects. This task creates domain models for all inspectable objects and a class that reads them from a live PostgreSQL connection via `pg_catalog`.

**Work:**
1. Create `src/pgschemadiff/domain/models/schema.py` with frozen Pydantic models:
   - `ColumnInfo(name, type_name, nullable, default, ordinal)`
   - `IndexInfo(name, columns, is_unique, is_primary, definition)`
   - `ConstraintInfo(name, kind, columns, check_expr, fk_table, fk_columns)`
   - `TableInfo(schema, name, columns, indexes, constraints)`
   - `ViewInfo(schema, name, definition)`
   - `SequenceInfo(schema, name, data_type, start, increment, min, max, cycle)`
   - `SchemaSnapshot(profile_name, captured_at, tables, views, sequences)`
2. Create `src/pgschemadiff/infrastructure/postgres/inspector.py`:
   - `SchemaInspector(conn: psycopg.Connection)`:
     - `capture(schemas: list[str]) → SchemaSnapshot` — orchestrates all sub-queries
     - Private methods querying: `information_schema.columns`, `pg_indexes`, `pg_constraint`, `pg_views`, `pg_sequences`
3. Add `__init__.py` for `infrastructure/postgres/`.

**Done conditions:**
- `SchemaInspector` can be instantiated and `capture()` runs without error against a live PG instance (verified manually or via a test with `@pytest.mark.integration`)
- All domain model fields are correctly typed and frozen
- `uv run mypy src/pgschemadiff/infrastructure/` passes

**Affected files:**
- `src/pgschemadiff/domain/models/schema.py` (new)
- `src/pgschemadiff/domain/models/__init__.py` (re-export new models)
- `src/pgschemadiff/infrastructure/postgres/__init__.py` (new)
- `src/pgschemadiff/infrastructure/postgres/inspector.py` (new)

---

### TASK-007 — Schema diff comparator
**Estimate:** 60 min  
**Status:** `[ ]`  
**Depends on:** TASK-006

**Context:**  
Given two `SchemaSnapshot` objects (source and target), produce a structured diff describing what changed.

**Work:**
1. Create `src/pgschemadiff/domain/diff/` package.
2. Define result models in `src/pgschemadiff/domain/diff/models.py`:
   - `TableDiff(table, added_columns, removed_columns, modified_columns, added_indexes, removed_indexes, added_constraints, removed_constraints)`
   - `DiffResult(profile_name, source_snapshot, target_snapshot, added_tables, removed_tables, modified_tables, added_views, removed_views, modified_views, added_sequences, removed_sequences, modified_sequences)`
3. Create `src/pgschemadiff/domain/diff/comparator.py`:
   - `SchemaComparator.compare(source: SchemaSnapshot, target: SchemaSnapshot) → DiffResult`
   - Compare by object identity: tables matched by `(schema, name)`, columns by `name` within a table, indexes by `name`, etc.
   - "Modified" = exists in both but at least one field differs.
4. Unit tests in `tests/domain/test_comparator.py` with synthetic snapshots.

**Done conditions:**
- `compare()` returns correct `DiffResult` for: new table, dropped table, added column, dropped column, changed column type, new index, dropped index
- Unit tests cover all six scenarios and pass
- `uv run mypy src/pgschemadiff/domain/diff/` passes

**Affected files:**
- `src/pgschemadiff/domain/diff/__init__.py` (new)
- `src/pgschemadiff/domain/diff/models.py` (new)
- `src/pgschemadiff/domain/diff/comparator.py` (new)
- `tests/domain/test_comparator.py` (new)

---

### TASK-008 — SQL migration generator
**Estimate:** 60 min  
**Status:** `[ ]`  
**Depends on:** TASK-007

**Context:**  
Translate a `DiffResult` into a valid PostgreSQL migration script. This is the core output of the tool.

**Work:**
1. Create `src/pgschemadiff/domain/migration/generator.py`:
   - `MigrationGenerator.generate(diff: DiffResult) → str`
   - Emit statements in safe order: DROP constraints/indexes → ALTER/DROP columns → DROP tables → CREATE tables → ADD columns → CREATE indexes → ADD constraints
   - Statements: `CREATE TABLE`, `DROP TABLE`, `ALTER TABLE ADD COLUMN`, `ALTER TABLE DROP COLUMN`, `ALTER TABLE ALTER COLUMN TYPE`, `CREATE [UNIQUE] INDEX`, `DROP INDEX`, `ALTER TABLE ADD CONSTRAINT`, `ALTER TABLE DROP CONSTRAINT`
   - Wrap everything in a transaction (`BEGIN; … COMMIT;`)
2. Unit tests in `tests/domain/test_generator.py` — given known `DiffResult`, assert generated SQL contains expected statements and is syntactically parseable (use `psycopg.sql` or simple string assertions).

**Done conditions:**
- `generate()` produces a non-empty SQL string for any non-empty `DiffResult`
- Generated SQL for a known diff matches expected statements (tested)
- Empty `DiffResult` → `"-- No schema differences found.\n"`
- `uv run mypy src/pgschemadiff/domain/migration/` passes

**Affected files:**
- `src/pgschemadiff/domain/migration/__init__.py` (new)
- `src/pgschemadiff/domain/migration/generator.py` (new)
- `tests/domain/test_generator.py` (new)

---

### TASK-009 — Comparing screen (Worker + ProgressBar)
**Estimate:** 75 min  
**Status:** `[ ]`  
**Depends on:** TASK-006, TASK-007

**Context:**  
When the user selects a profile and presses Enter (or clicks Compare), the app needs to connect to both databases, capture schemas, run the comparator, and show progress. Currently `_start_compare` only shows a notification.

**Work:**
1. Create `src/pgschemadiff/presentation/screens/comparing.py`:
   - `ComparingScreen(profile: Profile)` — a non-dismissible loading screen
   - Layout: centered panel with profile name, step label, `ProgressBar` (5 steps: connecting source, inspecting source, connecting target, inspecting target, comparing)
   - Run a `Worker` (async) that executes the 5 steps, calling `post_message` or `call_from_thread` to advance the progress bar after each step
   - On success: `dismiss(DiffResult)`
   - On any error: `dismiss(None)`, notify with error string
2. Wire in `HomeScreen._start_compare`:
   - Push `ComparingScreen(profile)` and await result
   - If result is a `DiffResult`: push `DiffExplorerScreen(result)` (stub screen OK for now — just shows "diff done" notification until TASK-010)
   - If result is None: return to Home (already there)
3. Handle `Escape` while comparing: confirm cancel, stop worker, dismiss.

**Done conditions:**
- Selecting a profile and pressing Enter transitions to the comparing screen
- ProgressBar advances through all 5 steps (visually confirmed)
- Successful compare shows a "comparison complete" notification (DiffExplorerScreen stub)
- A bad connection shows an error and returns to Home

**Affected files:**
- `src/pgschemadiff/presentation/screens/comparing.py` (new)
- `src/pgschemadiff/presentation/screens/home.py` (wire `_start_compare`)
- `src/pgschemadiff/presentation/styles.tcss` (comparing screen CSS)

---

### TASK-010 — Diff Explorer screen (Tree + 3-column layout)
**Estimate:** 90 min  
**Status:** `[ ]`  
**Depends on:** TASK-009, TASK-008

**Context:**  
After comparison, the user needs to browse the diff interactively before generating SQL. The README specifies a 3-column Tree widget layout.

**Work:**
1. Create `src/pgschemadiff/presentation/screens/diff_explorer.py`:
   - `DiffExplorerScreen(diff: DiffResult, migration_sql: str)`
   - Layout: 3 columns (30 / 35 / 35 width split)
     - **Left:** `Tree` — categories `Tables`, `Views`, `Sequences`; leaf nodes are object names prefixed with `+` (green), `-` (red), `~` (yellow) for added/removed/modified
     - **Middle:** detail panel — shows before/after field values for the selected tree node
     - **Right:** SQL preview pane — `RichLog` with the full migration SQL, auto-scrolls to the statement relevant to the selected object (best-effort search)
2. Key bindings: `s` → push `SqlPreviewScreen`, `q`/`Escape` → pop to Home.
3. Footer shows: `↑↓ navigate · s sql · q back`.

**Done conditions:**
- All diff categories appear in the tree, correctly color-coded
- Navigating tree nodes updates the middle detail panel
- Right pane shows SQL and scrolls to the relevant statement on node change
- `s` transitions to SQL Preview screen

**Affected files:**
- `src/pgschemadiff/presentation/screens/diff_explorer.py` (new)
- `src/pgschemadiff/presentation/screens/comparing.py` (update dismiss to pass DiffResult + generated SQL)
- `src/pgschemadiff/presentation/styles.tcss` (diff explorer CSS, color coding)

---

### TASK-011 — SQL Preview screen (RichLog + export)
**Estimate:** 60 min  
**Status:** `[ ]`  
**Depends on:** TASK-010, TASK-008

**Context:**  
The SQL Preview screen gives the user a full-screen view of the generated migration with export actions.

**Work:**
1. Create `src/pgschemadiff/presentation/screens/sql_preview.py`:
   - `SqlPreviewScreen(sql: str, profile_name: str)` — full-screen `RichLog` with SQL syntax highlighting via `rich.syntax.Syntax`
   - Toolbar buttons: `Copy` (write to clipboard via `pyperclip` or `xclip` subprocess), `Save` (open an `Input` modal for file path, write file, notify)
   - Key bindings: `c` → copy, `s` → save, `Escape`/`q` → pop back to Diff Explorer
2. If clipboard copy fails (no clipboard tool), show a notification explaining how to save to file instead.

**Done conditions:**
- SQL Preview screen shows highlighted SQL
- `s` prompts for filename and writes a `.sql` file to that path
- Pressing Escape returns to Diff Explorer with state intact

**Affected files:**
- `src/pgschemadiff/presentation/screens/sql_preview.py` (new)
- `src/pgschemadiff/presentation/screens/diff_explorer.py` (wire `s` key)
- `src/pgschemadiff/presentation/styles.tcss` (SQL screen toolbar CSS)

---

### TASK-012 — Test suite & linting CI
**Estimate:** 90 min  
**Status:** `[ ]`  
**Depends on:** TASK-007, TASK-008

**Context:**  
The project has `pytest`, `pytest-asyncio`, `ruff`, and `mypy` in dev dependencies but no `tests/` directory and no CI config.

**Work:**
1. Create `tests/` directory structure:
   ```
   tests/
   ├── __init__.py
   ├── conftest.py          ← shared fixtures (synthetic SchemaSnapshot, DiffResult)
   ├── domain/
   │   ├── test_comparator.py  ← from TASK-007
   │   └── test_generator.py   ← from TASK-008
   └── presentation/
       └── test_home_screen.py ← Textual Pilot tests
   ```
2. `test_home_screen.py` Pilot tests:
   - App loads 4 profiles from `profiles.yaml`
   - Navigate down → detail panel updates
   - Press `d` → ConfirmDialog appears → press Cancel → profile count unchanged
   - Press `d` → ConfirmDialog appears → press Delete → profile count decrements
3. Configure `pyproject.toml`:
   ```toml
   [tool.pytest.ini_options]
   asyncio_mode = "auto"
   testpaths = ["tests"]
   
   [tool.ruff]
   line-length = 100
   
   [tool.mypy]
   strict = true
   ```
4. Create `.github/workflows/ci.yml`:
   - `uv sync --dev`
   - `uv run ruff check src/ tests/`
   - `uv run mypy src/`
   - `uv run pytest tests/ -x -q`
5. All checks pass on the `main` branch.

**Done conditions:**
- `uv run pytest` exits 0 (≥10 passing tests)
- `uv run ruff check src/ tests/` exits 0
- `uv run mypy src/` exits 0
- CI workflow file exists and would pass

**Affected files:**
- `tests/` (new directory tree)
- `pyproject.toml` (pytest/ruff/mypy config)
- `.github/workflows/ci.yml` (new)

---

## Notes

- **Textual 8.2.7 bug:** Avoid extending `Vertical`/`Container` with complex `compose()`. Inline compose into the Screen directly (already documented in README).
- **CSS_PATH fix:** After TASK-001, `app.py` must use `Path(__file__).parent / "styles.tcss"` instead of a bare string, otherwise Textual can't find the stylesheet when the package is installed.
- **psycopg threading:** Textual Workers that use `psycopg` should use the synchronous `psycopg.connect()` in a thread worker (not the async driver) to avoid event-loop conflicts with Textual's own asyncio loop.
- **profiles.yaml location:** Keep `config/profiles.yaml` at the project root for dev convenience; the `__main__.py` discovery logic already handles this.
