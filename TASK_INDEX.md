# TASK_INDEX.md — pgschemadiff

> Last updated: 2026-05-23  
> Status legend: `[ ]` open · `[~]` in progress · `[x]` done

---

## Priority queue (execute in this order)

| # | ID | Title | Est. | Status | Blocks |
|---|-----|-------|------|--------|--------|
| 1 | T01 | Reorganize to src/ package structure | 45 min | [ ] | all |
| 2 | T02 | Implement `ConfirmDialog` widget | 30 min | [ ] | T03 |
| 3 | T03 | Verify HomeScreen runs end-to-end | 30 min | [ ] | T05+ |
| 4 | T04 | Implement `postgres/inspector.py` | 90 min | [ ] | T06, T07 |
| 5 | T05 | Implement `domain/diff/comparator.py` | 60 min | [ ] | T07, T08, T09 |
| 6 | T06 | Implement `screens/comparing.py` | 60 min | [ ] | T08 |
| 7 | T07 | Implement `domain/migration/generator.py` | 75 min | [ ] | T09 |
| 8 | T08 | Implement `screens/diff_explorer.py` | 75 min | [ ] | T09 |
| 9 | T09 | Implement `screens/sql_preview.py` | 45 min | [ ] | — |
| 10 | T10 | Wire New/Edit profile dialogs | 60 min | [ ] | — |
| 11 | T11 | Wire Test connection button | 45 min | [ ] | — |
| 12 | T12 | Unit + Pilot tests | 90 min | [ ] | — |

---

## T01 — Reorganize to `src/` package structure

**Estimate:** 45 min  
**Status:** `[ ]`  
**Depends on:** nothing  
**Blocks:** everything

### What to do

Create the proper package layout described in README. The flat files in root were written with correct imports anticipating this structure — they just need to be placed correctly.

```
src/pgschemadiff/
├── __init__.py
├── __main__.py                   ← move from root __main__.py
├── domain/
│   ├── __init__.py
│   └── models/
│       ├── __init__.py           ← export Profile, ConnectionInfo
│       └── profile.py            ← move from root profile.py
├── infrastructure/
│   ├── __init__.py
│   └── config/
│       ├── __init__.py
│       └── yaml_loader.py        ← move from root yaml_loader.py
└── presentation/
    ├── __init__.py
    ├── app.py                    ← move from root app.py
    ├── styles.tcss               ← move from root styles.tcss
    ├── screens/
    │   ├── __init__.py
    │   └── home.py               ← move from root home.py
    └── widgets/
        ├── __init__.py
        ├── profile_item.py       ← move from root profile_item.py
        └── profile_detail.py     ← move from root profile_detail.py
```

Also move `profiles.yaml` → `config/profiles.yaml`.

**Fix CSS_PATH in app.py:** after moving, the relative `"styles.tcss"` path in `PgSchemaDiffApp.CSS_PATH` must point to `"presentation/styles.tcss"` (relative to package root) or use `Path(__file__).parent / "styles.tcss"`.

**Done conditions:**
- `uv sync && uv run python -m pgschemadiff --help` exits cleanly
- All imports resolve (no `ModuleNotFoundError`)
- Root-level prototype files are removed

**Affected files:**
- All flat files at root (move, do not edit)
- `pyproject.toml` (verify `packages = ["src/pgschemadiff"]` — already correct)
- `src/pgschemadiff/presentation/app.py` (fix `CSS_PATH`)

---

## T02 — Implement `ConfirmDialog` widget

**Estimate:** 30 min  
**Status:** `[ ]`  
**Depends on:** T01  
**Blocks:** T03 (HomeScreen delete action requires it)

### What to do

Create `src/pgschemadiff/presentation/widgets/confirm_dialog.py`.

The widget is already imported and called in `home.py`:
```python
ConfirmDialog(title="Delete profile?", body="...")
```
And the callback signature is `Callable[[bool | None], None]` where `None` = dismissed without answer.

Implementation sketch:
- Extend `ModalScreen[bool]` (returns `bool` via `self.dismiss(True/False)`)
- Constructor accepts `title: str`, `body: str`
- Compose: `Label(title)`, `Label(body)`, Button("Delete", id="btn-confirm", classes="-danger")`, `Button("Cancel", id="btn-cancel")`
- `on_button_pressed`: dismiss True for confirm, False for cancel
- `on_key` with `escape`: dismiss None (or False)
- Style: centered modal, `#313244` background, `f38ba8` danger button (already in styles.tcss)

**Done conditions:**
- `ConfirmDialog` importable from `pgschemadiff.presentation.widgets.confirm_dialog`
- Pressing Delete in the modal dismisses with `True`
- Pressing Cancel or Escape dismisses with `False`/`None`

**Affected files:**
- `src/pgschemadiff/presentation/widgets/confirm_dialog.py` (new)
- `src/pgschemadiff/presentation/widgets/__init__.py` (optional re-export)

---

## T03 — Verify HomeScreen runs end-to-end

**Estimate:** 30 min  
**Status:** `[ ]`  
**Depends on:** T01, T02  
**Blocks:** all screen tasks (sanity checkpoint)

### What to do

Run the app with the sample `config/profiles.yaml` and exercise every wired interaction:

1. Launch: `uv run python -m pgschemadiff --config config/profiles.yaml`
2. Verify 4 profiles load, list renders, detail pane updates on ↑↓
3. Press `d` → ConfirmDialog appears → Delete → profile removed from list
4. Press `d` → Cancel → list unchanged
5. Press `?` → help notification appears
6. Press `q` → app exits cleanly

Write a basic Textual Pilot smoke test covering steps 2–4.

**Done conditions:**
- App starts without errors
- Delete flow works (list + subtitle update)
- Pilot test `tests/test_home_smoke.py` passes via `uv run pytest tests/`

**Affected files:**
- `tests/__init__.py` (new, empty)
- `tests/test_home_smoke.py` (new)
- `pyproject.toml` — add `[tool.pytest.ini_options] asyncio_mode = "auto"` if not present

---

## T04 — Implement `infrastructure/postgres/inspector.py`

**Estimate:** 90 min  
**Status:** `[ ]`  
**Depends on:** T01  
**Blocks:** T05, T06

### What to do

Query `pg_catalog` (not `information_schema`) to snapshot a database schema. Produce a pure-domain `SchemaSnapshot` object — no I/O after the query phase.

**New domain model** (`src/pgschemadiff/domain/models/schema_snapshot.py`):
```python
@dataclass(frozen=True)
class ColumnDef:
    name: str; type: str; nullable: bool; default: str | None; position: int

@dataclass(frozen=True)
class IndexDef:
    name: str; columns: tuple[str, ...]; unique: bool; definition: str

@dataclass(frozen=True)
class ConstraintDef:
    name: str; type: str; definition: str   # type: p|f|u|c

@dataclass(frozen=True)
class TableDef:
    schema: str; name: str
    columns: tuple[ColumnDef, ...]
    indexes: tuple[IndexDef, ...]
    constraints: tuple[ConstraintDef, ...]

@dataclass(frozen=True)
class ViewDef:
    schema: str; name: str; definition: str

@dataclass(frozen=True)
class SequenceDef:
    schema: str; name: str; start: int; increment: int; min: int; max: int

@dataclass(frozen=True)
class SchemaSnapshot:
    schemas: tuple[str, ...]
    tables: dict[str, TableDef]   # key: "schema.table"
    views: dict[str, ViewDef]
    sequences: dict[str, SequenceDef]
```

**Inspector class** (`src/pgschemadiff/infrastructure/postgres/inspector.py`):
```python
class SchemaInspector:
    async def inspect(
        self, dsn: str, schemas: list[str]
    ) -> SchemaSnapshot: ...
```

Queries to implement:
- Tables: `pg_class` + `pg_namespace` where `relkind = 'r'`
- Columns: `pg_attribute` + `pg_type` (filter `attnum > 0` and not dropped)
- Indexes: `pg_index` + `pg_class` (skip primary key constraint indexes — those come from constraints)
- Constraints: `pg_constraint` where `contype IN ('p','f','u','c')`; use `pg_get_constraintdef()` for definition
- Views: `pg_class` where `relkind = 'v'`; use `pg_get_viewdef()` for definition
- Sequences: `pg_sequences` system view

Use `psycopg` (v3 async API): `await psycopg.AsyncConnection.connect(dsn)`.

**Done conditions:**
- `SchemaInspector.inspect()` returns `SchemaSnapshot` for a running PostgreSQL
- All pg_catalog queries are parameterized (no f-string SQL)
- Works with schemas containing 0 objects (empty schema)
- Unit-testable via dependency injection (accept a connection, not a DSN, for testing)

**Affected files:**
- `src/pgschemadiff/domain/models/schema_snapshot.py` (new)
- `src/pgschemadiff/domain/models/__init__.py` (add exports)
- `src/pgschemadiff/infrastructure/postgres/__init__.py` (new)
- `src/pgschemadiff/infrastructure/postgres/inspector.py` (new)

---

## T05 — Implement `domain/diff/comparator.py`

**Estimate:** 60 min  
**Status:** `[ ]`  
**Depends on:** T01, T04 (needs `SchemaSnapshot` model)  
**Blocks:** T06, T07, T08

### What to do

Pure function: take two `SchemaSnapshot` objects, return a `DiffResult` describing what changed.

**New types** (`src/pgschemadiff/domain/diff/types.py`):
```python
from enum import Enum, auto

class ChangeKind(Enum):
    ADDED = auto()
    REMOVED = auto()
    MODIFIED = auto()

@dataclass(frozen=True)
class ObjectChange:
    kind: ChangeKind
    object_type: str      # "table" | "column" | "index" | "constraint" | "view" | "sequence"
    schema: str
    name: str             # qualified: "tablename.columnname" for columns
    source_def: object | None   # original object or None if ADDED
    target_def: object | None   # new object or None if REMOVED
    children: tuple["ObjectChange", ...] = ()

@dataclass(frozen=True)
class DiffResult:
    source_schemas: tuple[str, ...]
    target_schemas: tuple[str, ...]
    changes: tuple[ObjectChange, ...]

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0
```

**Comparator** (`src/pgschemadiff/domain/diff/comparator.py`):
```python
def compare(source: SchemaSnapshot, target: SchemaSnapshot) -> DiffResult: ...
```

Logic:
- Compare tables by qualified name (`schema.table`)
- For each shared table: compare columns (by name), indexes (by name), constraints (by name)
- Report column type/nullability/default changes as `MODIFIED`
- Compare views by name + definition string
- Compare sequences by name + properties

**Done conditions:**
- `compare(a, b)` returns empty `DiffResult` when `a == b`
- Detects: new table, dropped table, added column, dropped column, changed column type, changed index, changed view definition
- Pure function — no I/O, no Textual dependency
- Tests in `tests/test_comparator.py` covering all change kinds

**Affected files:**
- `src/pgschemadiff/domain/diff/__init__.py` (new)
- `src/pgschemadiff/domain/diff/types.py` (new)
- `src/pgschemadiff/domain/diff/comparator.py` (new)
- `tests/test_comparator.py` (new)

---

## T06 — Implement `screens/comparing.py`

**Estimate:** 60 min  
**Status:** `[ ]`  
**Depends on:** T01, T04, T05  
**Blocks:** T08 (diff explorer needs compare to have run)

### What to do

A loading screen that:
1. Accepts a `Profile` on construction
2. On mount: launches a Textual `Worker` (`self.run_worker`) that calls `SchemaInspector.inspect()` for source AND target concurrently (via `asyncio.gather`)
3. Runs `compare(source_snap, target_snap)` → `DiffResult`
4. On success: replaces itself with `DiffExplorerScreen(diff_result, profile)`
5. On error: shows error message with retry / back buttons

UI layout:
- `Label` showing "Connecting to source…" / "Connecting to target…" / "Comparing…"
- `ProgressBar` (indeterminate) during async work
- `Label` with spinner or status text
- Binding `escape` → back to Home

Wire up in `HomeScreen._start_compare()`: replace the `notify()` stub with `self.app.push_screen(ComparingScreen(profile))`.

**Done conditions:**
- Screen mounts, worker fires, progress bar is visible
- On worker success: transitions to DiffExplorerScreen (can be a stub that just shows the change count)
- On worker error (e.g. connection refused): shows error with "Back" button that returns to Home
- Escape always returns to Home

**Affected files:**
- `src/pgschemadiff/presentation/screens/comparing.py` (new)
- `src/pgschemadiff/presentation/screens/home.py` (update `_start_compare`)
- `src/pgschemadiff/presentation/screens/__init__.py` (update exports)

---

## T07 — Implement `domain/migration/generator.py`

**Estimate:** 75 min  
**Status:** `[ ]`  
**Depends on:** T01, T05  
**Blocks:** T09

### What to do

Generate DDL SQL migration from a `DiffResult`. The migration moves target schema toward source schema (source is the reference/desired state).

**Generator** (`src/pgschemadiff/domain/migration/generator.py`):
```python
def generate(diff: DiffResult) -> str: ...
```

DDL to generate per change kind:

| Change | SQL |
|--------|-----|
| Table ADDED | `CREATE TABLE schema.name (...)` |
| Table REMOVED | `DROP TABLE schema.name;` |
| Column ADDED | `ALTER TABLE t ADD COLUMN name type [NOT NULL] [DEFAULT x];` |
| Column REMOVED | `ALTER TABLE t DROP COLUMN name;` |
| Column MODIFIED (type) | `ALTER TABLE t ALTER COLUMN name TYPE newtype;` |
| Column MODIFIED (nullable) | `ALTER TABLE t ALTER COLUMN name [SET/DROP] NOT NULL;` |
| Column MODIFIED (default) | `ALTER TABLE t ALTER COLUMN name [SET/DROP] DEFAULT x;` |
| Index ADDED | use `IndexDef.definition` directly (pg_get_indexdef output) |
| Index REMOVED | `DROP INDEX CONCURRENTLY schema.name;` |
| Constraint ADDED | `ALTER TABLE t ADD CONSTRAINT name ...` using `ConstraintDef.definition` |
| Constraint REMOVED | `ALTER TABLE t DROP CONSTRAINT name;` |
| View ADDED | `CREATE OR REPLACE VIEW ...` |
| View REMOVED | `DROP VIEW schema.name;` |
| View MODIFIED | `CREATE OR REPLACE VIEW ...` |
| Sequence ADDED | `CREATE SEQUENCE ...` |
| Sequence REMOVED | `DROP SEQUENCE schema.name;` |

Output: a single SQL string with `-- section` comments grouping changes by type, safe to pipe to `psql`.

**Done conditions:**
- `generate(empty_diff)` returns empty string
- All change kinds produce valid SQL (manually verified)
- Output is ordered: DROP INDEX → DROP CONSTRAINT → ALTER TABLE → DROP TABLE → CREATE TABLE → ADD COLUMN → ADD CONSTRAINT → CREATE INDEX → views → sequences
- Tests in `tests/test_generator.py` covering core patterns

**Affected files:**
- `src/pgschemadiff/domain/migration/__init__.py` (new)
- `src/pgschemadiff/domain/migration/generator.py` (new)
- `tests/test_generator.py` (new)

---

## T08 — Implement `screens/diff_explorer.py`

**Estimate:** 75 min  
**Status:** `[ ]`  
**Depends on:** T01, T05, T06  
**Blocks:** T09

### What to do

Show the `DiffResult` in a navigable Tree. This is the main output screen.

Layout (3 columns via `Horizontal`):
- **Left pane (28 cols):** `Tree` widget — top-level nodes are object types ("Tables", "Views", "Sequences"), children are the changed objects, icon prefix: `[+]` added, `[-]` removed, `[~]` modified
- **Center pane (1fr):** `Static` — detail of selected object (old vs new definition rendered with Rich markup)
- **Right pane (24 cols):** `Static` — raw SQL snippet for this change (from generator, filtered to this object)

Bindings:
- `s` → push `SqlPreviewScreen(full_sql)` 
- `c` → copy full SQL to clipboard (via `pyperclip` or `xclip` shell call)
- `escape` → back to Home (pop screen)
- `enter` / tree selection → updates center+right panes

Header subtitle: `"X changes · profile_name"` (where X = `len(diff.changes)`)

If `diff.has_changes` is False: show a centered "No schema differences found" message instead of the tree.

**Done conditions:**
- Tree renders all change kinds with correct prefix icons
- Selecting a tree node updates center/right panes
- `s` opens SqlPreviewScreen
- Escape returns to Home
- No-diff state shows empty state message

**Affected files:**
- `src/pgschemadiff/presentation/screens/diff_explorer.py` (new)
- `src/pgschemadiff/presentation/styles.tcss` (add diff explorer styles)
- `src/pgschemadiff/presentation/screens/__init__.py` (update exports)

---

## T09 — Implement `screens/sql_preview.py`

**Estimate:** 45 min  
**Status:** `[ ]`  
**Depends on:** T01, T07, T08  
**Blocks:** nothing (terminal feature)

### What to do

Full-screen SQL viewer with syntax highlighting.

Layout:
- `Header` with title "SQL Migration Preview"
- `RichLog` (or `TextArea` in read-only mode) displaying the full migration SQL with syntax highlighting
- `Footer` with bindings

Bindings:
- `c` → copy to clipboard
- `w` → write to file (prompt for path via `Input` overlay, default `migration_YYYYMMDD_HHMMSS.sql`)
- `escape` → pop back to DiffExplorerScreen

For syntax highlighting: use `rich.syntax.Syntax("sql", theme="monokai")` rendered into a `Static`, or use Textual's built-in `TextArea` with `language="sql"` (available in Textual ≥ 0.47).

**Done conditions:**
- SQL is displayed with syntax highlighting
- `w` key prompts for filename and writes the file
- File is written to CWD with confirmation notification
- Escape returns to DiffExplorer

**Affected files:**
- `src/pgschemadiff/presentation/screens/sql_preview.py` (new)
- `src/pgschemadiff/presentation/styles.tcss` (add preview styles if needed)

---

## T10 — Wire New/Edit profile dialogs

**Estimate:** 60 min  
**Status:** `[ ]`  
**Depends on:** T01, T03  
**Blocks:** nothing (HomeScreen UX improvement)

### What to do

Implement a `ProfileFormScreen` modal that handles both create and edit flows.

Fields to expose (matching `Profile` model):
- `name` (Input, required, unique)
- `source.*` (host, port, database, user, password)
- `target.*` (same fields)
- `schemas` (Input, comma-separated)
- `ignore_patterns` (Input, comma-separated)
- `mode` (Select: "schema-only")

Wire in `HomeScreen`:
- `action_new_profile` → `push_screen(ProfileFormScreen(), on_new_profile)`
- `action_edit_profile` → `push_screen(ProfileFormScreen(profile=item.profile), on_edit_profile)`

Persist changes via `ProfileLoader.save()`. Update `self._profiles` in memory and rebuild the ListView (or call `lv.append()` for new).

**Done conditions:**
- `n` key opens form with empty fields
- `e` key opens form pre-filled with selected profile's values
- Saving a valid new profile: adds to list and persists to YAML
- Editing: updates list item and persists to YAML
- Validation: name uniqueness for new, non-empty required fields
- Cancel returns without changes

**Affected files:**
- `src/pgschemadiff/presentation/screens/profile_form.py` (new)
- `src/pgschemadiff/presentation/screens/home.py` (update action handlers)
- `src/pgschemadiff/presentation/styles.tcss` (form styles)

---

## T11 — Wire "Test connection" button

**Estimate:** 45 min  
**Status:** `[ ]`  
**Depends on:** T01, T03  
**Blocks:** nothing

### What to do

Wire `btn-test` (and add a `t` keybinding) to test both source and target connections for the selected profile.

Implementation:
- Run `await psycopg.AsyncConnection.connect(dsn, connect_timeout=5)` for source and target
- Use a Worker so the UI stays responsive
- Show a `ProgressBar` (indeterminate) in the detail pane while testing
- On success: notify "`source` ✓  `target` ✓ — both connections OK"
- On partial failure: notify "source ✗: [error]" or "target ✗: [error]" with `severity="error"`

**Done conditions:**
- Button click triggers async test (UI doesn't freeze)
- Success and failure notifications are shown correctly
- Timeout is respected (no hang beyond 5 s)
- Works for both Source and Target independently reported

**Affected files:**
- `src/pgschemadiff/presentation/screens/home.py` (add `on_button_pressed` handler, add `t` binding)

---

## T12 — Unit + Pilot tests

**Estimate:** 90 min  
**Status:** `[ ]`  
**Depends on:** T01, T02, T03, T05, T07  
**Blocks:** nothing (quality gate)

### What to do

Comprehensive test suite using `pytest` + `pytest-asyncio` + Textual Pilot.

| Test file | What it covers |
|-----------|---------------|
| `tests/test_comparator.py` | Pure unit: all change kinds in comparator |
| `tests/test_generator.py` | Pure unit: DDL output for each change type |
| `tests/test_home_smoke.py` | Pilot: launch, navigate, delete profile |
| `tests/test_confirm_dialog.py` | Pilot: confirm/cancel/escape all paths |

Add to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Done conditions:**
- `uv run pytest` passes with 0 failures
- Coverage ≥ 80% for `domain/` modules
- No test requires a live PostgreSQL (mock psycopg for inspector tests)

**Affected files:**
- `pyproject.toml` (add pytest config)
- `tests/test_comparator.py` (new or extend)
- `tests/test_generator.py` (new or extend)
- `tests/test_home_smoke.py` (new or extend)
- `tests/test_confirm_dialog.py` (new)

---

## Dependency graph

```
T01 (restructure)
 ├─ T02 (confirm_dialog)
 │   └─ T03 (smoke verify) ──────── T10 (new/edit forms)
 │                                   T11 (test connection)
 ├─ T04 (inspector)
 │   └─ T05 (comparator)
 │       ├─ T06 (comparing screen)
 │       │   └─ T08 (diff explorer)
 │       │       └─ T09 (sql preview)
 │       └─ T07 (migration generator)
 │           └─ T09
 └─ T12 (tests) ← depends on T02, T05, T07
```

## Notes

- **Textual bug workaround:** Textual 0.83+ has a bug when extending `Vertical`/`Container` with complex `compose()`. Keep screen composition inline (as done in `home.py`) rather than creating intermediate Container subclasses.
- `profile_detail.py` at root uses the buggy Container-subclass pattern — do NOT use it; use the inline pattern from `home.py` instead.
- `psycopg[binary,pool]` is already in dependencies; use `psycopg.AsyncConnection` for all DB access.
- All DB queries must use parameterized queries — no f-string SQL.
