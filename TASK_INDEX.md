# TASK_INDEX.md

Last updated: 2026-05-24  
Source: roadmap in README.md + structural analysis of current prototype

## Status legend

| Symbol | Meaning |
|--------|---------|
| `[ ]`  | Not started |
| `[~]`  | In progress |
| `[x]`  | Done |
| `[!]`  | Blocked |

---

## Dependency graph

```
TASK-001 (restructure)
    ├── TASK-002 (profile CRUD)
    ├── TASK-003 (domain types + comparator)
    │       ├── TASK-004 (pg inspector)
    │       │       └── TASK-005 (comparing screen)
    │       │               └── TASK-006 (diff explorer)
    │       │                       └── TASK-009 (full flow)
    │       └── TASK-007 (migration generator)
    │               └── TASK-008 (sql preview)
    │                       └── TASK-009 (full flow)
    └── TASK-010 (test suite skeleton)
```

---

## Tasks

### TASK-001 · Set up src-layout package structure
**Priority: CRITICAL — blocks all other tasks**  
**Estimate: 45–60 min**  
**Status: [ ]**

#### Context
All code files currently sit flat at the repo root (`app.py`, `home.py`,
`profile.py`, etc.) but their imports already reference the planned package
hierarchy (`pgschemadiff.domain.models`, `pgschemadiff.presentation.screens.home`,
etc.). The package cannot be imported as-is. `confirm_dialog.py` is also
missing from the repo (imported by `home.py` but not committed).

#### Work
1. Create `src/pgschemadiff/` directory skeleton with `__init__.py` files:
   - `src/pgschemadiff/`
   - `src/pgschemadiff/domain/`
   - `src/pgschemadiff/domain/models/`
   - `src/pgschemadiff/domain/diff/`
   - `src/pgschemadiff/domain/migration/`
   - `src/pgschemadiff/infrastructure/`
   - `src/pgschemadiff/infrastructure/config/`
   - `src/pgschemadiff/infrastructure/postgres/`
   - `src/pgschemadiff/presentation/`
   - `src/pgschemadiff/presentation/screens/`
   - `src/pgschemadiff/presentation/widgets/`
2. Move flat files to their target locations:
   - `__main__.py` → `src/pgschemadiff/__main__.py`
   - `app.py` → `src/pgschemadiff/presentation/app.py`
   - `home.py` → `src/pgschemadiff/presentation/screens/home.py`
   - `profile.py` → `src/pgschemadiff/domain/models/profile.py`
   - `profile_item.py` → `src/pgschemadiff/presentation/widgets/profile_item.py`
   - `profile_detail.py` → `src/pgschemadiff/presentation/widgets/profile_detail.py`
   - `yaml_loader.py` → `src/pgschemadiff/infrastructure/config/yaml_loader.py`
   - `styles.tcss` → `src/pgschemadiff/presentation/styles.tcss`
3. Create `src/pgschemadiff/domain/models/__init__.py` exporting `Profile`, `ConnectionInfo`
4. Create missing `src/pgschemadiff/presentation/widgets/confirm_dialog.py`
   (Modal with title, body, Cancel/Delete buttons; callback `bool | None`)
5. Move `profiles.yaml` → `config/profiles.yaml`
6. Update `CSS_PATH` in `app.py` to resolve from package root
7. Delete the flat root-level source files (keep `profiles.yaml` in `config/`)

#### Done conditions
- `uv sync && uv run python -m pgschemadiff` starts and renders HomeScreen
- `uv run python -m pgschemadiff --config config/profiles.yaml` loads 4 profiles
- Delete dialog (`d`) works: modal appears, Delete/Cancel function correctly
- `ruff check src/` passes with no errors

#### Affected files
- **Deleted**: `__main__.py`, `app.py`, `home.py`, `profile.py`, `profile_item.py`, `profile_detail.py`, `yaml_loader.py`, `styles.tcss`, `profiles.yaml` (root-level)
- **Created**: full `src/pgschemadiff/` tree + `config/profiles.yaml`

---

### TASK-002 · Profile CRUD — New & Edit dialogs
**Priority: HIGH (user-visible UX gap)**  
**Estimate: 60–90 min**  
**Status: [ ]**  
**Depends on: TASK-001**

#### Work
1. Create `src/pgschemadiff/presentation/screens/profile_form.py`
   - Input fields: name, source host/port/db/user/password, target host/port/db/user/password,
     schemas (comma-separated), ignore_patterns (comma-separated), mode (select: schema-only / data / full)
   - Submit / Cancel buttons; validate non-empty name, valid port integers
   - Return: `Profile | None` via screen result callback
2. Wire `HomeScreen.action_new_profile` → push `ProfileFormScreen(None)`,
   on result append to `_profiles`, save via `ProfileLoader.save()`
3. Wire `HomeScreen.action_edit_profile` → push `ProfileFormScreen(profile)`,
   on result replace in `_profiles`, save via `ProfileLoader.save()`
4. Wire `HomeScreen.on_button_pressed` for `btn-edit` → same as `e` key

#### Done conditions
- `n` opens blank form, filling and submitting adds profile to list and persists to YAML
- `e` opens form pre-filled with selected profile's values; saving updates list and YAML
- Pressing `esc` or Cancel from form returns to HomeScreen with no changes
- Form validation shows inline error for missing name or invalid port

#### Affected files
- **Created**: `src/pgschemadiff/presentation/screens/profile_form.py`
- **Modified**: `src/pgschemadiff/presentation/screens/home.py`

---

### TASK-003 · Domain types + `domain/diff/comparator.py`
**Priority: HIGH — foundational types used by TASK-004, 005, 006, 007**  
**Estimate: 60–90 min**  
**Status: [ ]**  
**Depends on: TASK-001**

#### Work
1. Create `src/pgschemadiff/domain/models/schema_snapshot.py` with frozen dataclasses:
   ```
   ColumnDef(name, data_type, nullable, default, ordinal)
   IndexDef(name, columns, unique, method)
   ConstraintDef(name, type, columns, foreign_table, foreign_columns, check_expr)
   SequenceDef(name, data_type, start, increment, min_val, max_val, cycle)
   ViewDef(name, definition)
   FunctionDef(name, signature, return_type, language, body)
   TableDef(name, columns, indexes, constraints)
   SchemaSnapshot(schema_name, tables, sequences, views, functions)
   ```
2. Create `src/pgschemadiff/domain/diff/comparator.py`:
   ```
   @dataclass(frozen=True)
   class ObjectDiff:
       kind: Literal["added", "removed", "modified"]
       object_type: str  # "table", "column", etc.
       path: str         # e.g. "public.users.email"
       source: Any | None
       target: Any | None

   @dataclass
   class DiffResult:
       diffs: list[ObjectDiff]
       def is_empty(self) -> bool: ...

   def compare(source: SchemaSnapshot, target: SchemaSnapshot) -> DiffResult: ...
   ```
   - Compare tables, columns (added/removed/type-changed/nullable-changed/default-changed),
     indexes, constraints, sequences, views (by definition), functions (by body+signature)
3. Update `src/pgschemadiff/domain/models/__init__.py` to also export snapshot types
4. Create `src/pgschemadiff/domain/diff/__init__.py`

#### Done conditions
- `compare(snapshot_a, snapshot_b)` returns correct `DiffResult` for:
  - added table
  - removed column
  - changed column type
  - added index
  - removed constraint
  - modified view definition
- `compare(x, x)` returns `DiffResult(diffs=[])` (identical → no diff)

#### Affected files
- **Created**: `src/pgschemadiff/domain/models/schema_snapshot.py`
- **Created**: `src/pgschemadiff/domain/diff/__init__.py`
- **Created**: `src/pgschemadiff/domain/diff/comparator.py`
- **Modified**: `src/pgschemadiff/domain/models/__init__.py`

---

### TASK-004 · `infrastructure/postgres/inspector.py` — pg_catalog introspection
**Priority: HIGH**  
**Estimate: 90–120 min**  
**Status: [ ]**  
**Depends on: TASK-001, TASK-003**

#### Work
1. Create `src/pgschemadiff/infrastructure/postgres/inspector.py`:
   ```python
   async def inspect_schema(
       dsn: str,
       schemas: list[str],
       on_progress: Callable[[str], None] | None = None,
   ) -> dict[str, SchemaSnapshot]:
       ...
   ```
2. Implement queries against `pg_catalog`:
   - `pg_tables` / `information_schema.columns` for tables + columns
   - `pg_indexes` for indexes (parse `indexdef` to extract columns + method)
   - `pg_constraint` for constraints (pk, fk, unique, check)
   - `pg_sequences` for sequences
   - `pg_views` for views
   - `pg_proc` + `pg_language` for functions
3. Use `psycopg` async connection with `await conn.execute()`
4. Call `on_progress("Fetching tables…")` etc. at each step for UI feedback
5. Create `src/pgschemadiff/infrastructure/postgres/__init__.py`

#### Done conditions
- `inspect_schema(dsn, ["public"])` returns `dict[str, SchemaSnapshot]` keyed by schema name
- Works against a real PostgreSQL 14+ instance (tested manually or via integration test)
- Handles missing schema gracefully (returns empty `SchemaSnapshot`)
- `on_progress` callback is called at each introspection step
- Connection errors raise `InspectorError` (custom exception, not raw psycopg error)

#### Affected files
- **Created**: `src/pgschemadiff/infrastructure/postgres/__init__.py`
- **Created**: `src/pgschemadiff/infrastructure/postgres/inspector.py`

---

### TASK-005 · `screens/comparing.py` — async loading screen
**Priority: MEDIUM**  
**Estimate: 60–90 min**  
**Status: [ ]**  
**Depends on: TASK-001, TASK-003, TASK-004**

#### Work
1. Create `src/pgschemadiff/presentation/screens/comparing.py`:
   - Receives `profile: Profile`
   - Displays spinner + `Label` showing current step text
   - Uses `self.run_worker(self._run_comparison(), exclusive=True)` (Textual Worker)
   - `_run_comparison()` async:
     1. Calls `inspector.inspect_schema(source_dsn, schemas, on_progress)` 
     2. Calls `inspector.inspect_schema(target_dsn, schemas, on_progress)`
     3. Calls `comparator.compare(source_snap, target_snap)` for each schema
     4. On success: `self.app.switch_screen(DiffExplorerScreen(profile, result))`
     5. On `InspectorError`: shows error panel with message + Retry / Back buttons
2. Wire `HomeScreen._start_compare()` to push `ComparingScreen(profile)` instead of `notify()`

#### Done conditions
- Pressing `enter` on a profile pushes ComparingScreen
- Step labels update in real-time as inspection proceeds
- Connection failure shows error message (not an unhandled exception crash)
- `esc` or Back button during loading cancels the worker and returns to HomeScreen

#### Affected files
- **Created**: `src/pgschemadiff/presentation/screens/comparing.py`
- **Modified**: `src/pgschemadiff/presentation/screens/home.py` (`_start_compare`)

---

### TASK-006 · `screens/diff_explorer.py` — Tree diff viewer
**Priority: MEDIUM**  
**Estimate: 90–120 min**  
**Status: [ ]**  
**Depends on: TASK-001, TASK-003, TASK-005**

#### Work
1. Create `src/pgschemadiff/presentation/screens/diff_explorer.py`:
   - Left pane (1/3 width): Textual `Tree` widget
     - Root nodes: "Tables", "Indexes", "Constraints", "Sequences", "Views", "Functions"
     - Children: one `TreeNode` per `ObjectDiff`, labelled by `diff.path`
     - Color: green markup for `added`, red for `removed`, yellow for `modified`
   - Right pane (2/3 width): `Static` or `RichLog` showing detail of selected diff
     - Shows `diff.source` and `diff.target` formatted as readable text
   - Footer bindings: `s` → SQLPreviewScreen, `q`/`esc` → back to HomeScreen
2. Add sub-title: `"{profile.name} — {len(result.diffs)} differences"`
3. Handle empty diff (`result.is_empty()`) — show "Schemas are identical" message

#### Done conditions
- Tree renders all diffs grouped by category
- Navigating tree nodes updates detail pane in real-time
- `s` pushes SQLPreviewScreen (or shows placeholder until TASK-008 is done)
- `esc` pops back to HomeScreen
- Empty diff shows a clear "no differences" message

#### Affected files
- **Created**: `src/pgschemadiff/presentation/screens/diff_explorer.py`
- **Modified**: `src/pgschemadiff/presentation/styles.tcss` (tree styles)

---

### TASK-007 · `domain/migration/generator.py` — SQL migration generator
**Priority: MEDIUM**  
**Estimate: 90–120 min**  
**Status: [ ]**  
**Depends on: TASK-001, TASK-003**

#### Work
1. Create `src/pgschemadiff/domain/migration/generator.py`:
   ```python
   @dataclass
   class MigrationScript:
       statements: list[str]
       def as_sql(self) -> str: ...  # joined with ";\n"

   def generate(result: DiffResult) -> MigrationScript: ...
   ```
2. Implement statement generation for each `ObjectDiff.object_type`:
   - `added` table → `CREATE TABLE`
   - `removed` table → `DROP TABLE`
   - `added` column → `ALTER TABLE … ADD COLUMN`
   - `removed` column → `ALTER TABLE … DROP COLUMN`
   - `modified` column type → `ALTER TABLE … ALTER COLUMN … TYPE`
   - `modified` column nullable → `ALTER TABLE … ALTER COLUMN … SET/DROP NOT NULL`
   - `modified` column default → `ALTER TABLE … ALTER COLUMN … SET/DROP DEFAULT`
   - `added` / `removed` index → `CREATE INDEX` / `DROP INDEX`
   - `added` / `removed` constraint → `ALTER TABLE … ADD CONSTRAINT` / `DROP CONSTRAINT`
   - `added` / `removed` sequence → `CREATE SEQUENCE` / `DROP SEQUENCE`
   - `added` / `removed` view → `CREATE VIEW` / `DROP VIEW`
   - `modified` view → `CREATE OR REPLACE VIEW`
   - `added` / `removed` function → `CREATE FUNCTION` / `DROP FUNCTION`
   - `modified` function → `CREATE OR REPLACE FUNCTION`
3. Order statements to respect dependencies (drops before creates for renamed objects;
   column additions before index additions on same table)
4. Create `src/pgschemadiff/domain/migration/__init__.py`

#### Done conditions
- `generate(diff_result)` returns valid, executable PostgreSQL SQL for all 12 diff types
- Statements are ordered (table drops before index drops; column adds before index adds)
- `generate(DiffResult(diffs=[]))` returns `MigrationScript(statements=[])`
- Unit tests pass for each statement type

#### Affected files
- **Created**: `src/pgschemadiff/domain/migration/__init__.py`
- **Created**: `src/pgschemadiff/domain/migration/generator.py`

---

### TASK-008 · `screens/sql_preview.py` — SQL preview with syntax highlight
**Priority: MEDIUM**  
**Estimate: 60–90 min**  
**Status: [ ]**  
**Depends on: TASK-001, TASK-007**

#### Work
1. Create `src/pgschemadiff/presentation/screens/sql_preview.py`:
   - Receives `script: MigrationScript`
   - Full-screen `RichLog` (or `TextArea` in read-only mode) with syntax-highlighted SQL
   - Uses Rich's `Syntax("sql", ...)` for highlighting
   - Sub-title: `"{len(script.statements)} statements"`
2. Bindings:
   - `c` → copy full SQL to clipboard via `pyperclip` or `xclip` subprocess (graceful fallback if unavailable)
   - `s` → save to file prompt (Input widget overlay asking for filename)
   - `esc` → back to DiffExplorerScreen
3. Show line numbers; scroll to top on mount

#### Done conditions
- SQL is syntax-highlighted in the Catppuccin Mocha color scheme
- `s` opens filename prompt; saving writes the file and shows a success notification
- `esc` returns to DiffExplorerScreen without data loss
- Empty migration renders "Nothing to migrate" message instead of blank screen

#### Affected files
- **Created**: `src/pgschemadiff/presentation/screens/sql_preview.py`

---

### TASK-009 · Wire full compare flow end-to-end
**Priority: MEDIUM**  
**Estimate: 45–60 min**  
**Status: [ ]**  
**Depends on: TASK-005, TASK-006, TASK-008**

#### Work
1. Confirm screen transitions form a clean stack:
   `HomeScreen → ComparingScreen → DiffExplorerScreen → SQLPreviewScreen`
2. Ensure `profile` and `diff_result` / `script` are passed correctly via screen
   constructors (no global state)
3. Verify `esc` at each screen pops cleanly: SQL Preview → Diff Explorer, Diff Explorer → Home
4. Wire `DiffExplorerScreen` `s` key → `generator.generate(result)` → push `SQLPreviewScreen`
5. Add `btn-compare` in HomeScreen `on_button_pressed` → same as `enter` / `action_compare`
6. Smoke-test the full flow with mock data (fake `SchemaSnapshot` objects, no real DB)

#### Done conditions
- Full `HomeScreen → compare → (async load) → DiffExplorer → SQL Preview` flow works
- `esc` at each stage returns to the previous screen, no crashes
- Profile name visible in sub-title across all screens
- No unhandled exceptions with mock data

#### Affected files
- **Modified**: `src/pgschemadiff/presentation/screens/diff_explorer.py`
- **Modified**: `src/pgschemadiff/presentation/screens/comparing.py`
- **Modified**: `src/pgschemadiff/presentation/screens/home.py`

---

### TASK-010 · Test suite skeleton
**Priority: LOW (but enables CI)**  
**Estimate: 60–90 min**  
**Status: [ ]**  
**Depends on: TASK-001, TASK-003, TASK-007**

#### Work
1. Create `tests/` directory with `conftest.py`
2. `tests/domain/test_profile.py` — `Profile.model_validate`, `ConnectionInfo.display()`, `ConnectionInfo.dsn()`
3. `tests/infrastructure/test_yaml_loader.py` — round-trip load/save to tmp file
4. `tests/domain/test_comparator.py` — parametrized tests for all diff types (no real DB)
5. `tests/domain/test_generator.py` — one test per SQL statement type
6. Add `[tool.pytest.ini_options]` to `pyproject.toml`: `testpaths = ["tests"]`, `asyncio_mode = "auto"`
7. Verify `uv run pytest` passes with 0 failures

#### Done conditions
- `uv run pytest` exits 0
- At least 20 distinct test cases covering profile validation, YAML round-trip, comparator, generator
- No tests require a real PostgreSQL connection (mock or fixture data only)

#### Affected files
- **Created**: `tests/` directory tree
- **Modified**: `pyproject.toml`

---

## Execution order

```
Sprint 1 (unblock everything)
  TASK-001  ← start here, merge first

Sprint 2 (foundational logic, can parallelize)
  TASK-003  ← domain types + comparator
  TASK-002  ← profile CRUD (quick UX win, independent)

Sprint 3 (infrastructure + generation, parallelize)
  TASK-004  ← pg inspector
  TASK-007  ← migration generator

Sprint 4 (UI screens, parallelize after TASK-004 done)
  TASK-005  ← comparing screen
  TASK-008  ← SQL preview

Sprint 5 (complete UI)
  TASK-006  ← diff explorer (needs TASK-005)

Sprint 6 (wire + test)
  TASK-009  ← full flow wiring
  TASK-010  ← test suite
```

## Time summary

| Task | Est. time | Priority | Status |
|------|-----------|----------|--------|
| TASK-001 · Restructure src-layout | 45–60 min | CRITICAL | [ ] |
| TASK-002 · Profile CRUD dialogs | 60–90 min | HIGH | [ ] |
| TASK-003 · Domain types + comparator | 60–90 min | HIGH | [ ] |
| TASK-004 · pg inspector | 90–120 min | HIGH | [ ] |
| TASK-005 · Comparing screen | 60–90 min | MEDIUM | [ ] |
| TASK-006 · Diff explorer screen | 90–120 min | MEDIUM | [ ] |
| TASK-007 · Migration generator | 90–120 min | MEDIUM | [ ] |
| TASK-008 · SQL preview screen | 60–90 min | MEDIUM | [ ] |
| TASK-009 · Full flow wiring | 45–60 min | MEDIUM | [ ] |
| TASK-010 · Test suite | 60–90 min | LOW | [ ] |
| **Total** | **~11–17 hrs** | | |
