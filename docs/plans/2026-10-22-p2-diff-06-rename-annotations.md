# P2-DIFF-06 Rename Annotations Implementation Plan

> **For agentic workers:** Execute inline in this session, test-first, and update `TASK_INDEX.md` at each completed milestone.

**Goal:** Load explicit YAML/TOML table and column rename annotations and consume them in the diff API without inferring renames.

**Architecture:** Application layer owns immutable typed annotations and snapshot validation. Infrastructure loader parses YAML with the existing YAML dependency and TOML with stdlib `tomllib`. `DiffEngine.diff(..., renames=...)` pairs annotated objects and passes annotation context only to rename-aware comparators; normal calls preserve current behavior.

**Tech Stack:** Python 3.13, Pydantic v2, PyYAML, stdlib `tomllib`, pytest.

**Spec:** ADR-0007 and approved P2-DIFF-06 design in conversation (2026-10-22).

## Global Constraints

- Never infer renames; only explicit annotations may produce `RenameTable` or `RenameColumn`.
- Malformed, ambiguous, conflicting, missing-endpoint, or unsupported annotations raise `DiffError`; never fall back silently.
- Keep CLI `--renames` deferred to P2-CLI-01.
- Preserve original source/target objects in emitted deltas; normalize structured references only for semantic comparison.
- Do not rewrite SQL expression or predicate strings; existing comparators must expose any resulting structural delta.

---

## Files and Responsibilities

- `src/pgschemadiff/application/diff/renames.py`: immutable `TableRename`, `ColumnRename`, and `RenameAnnotations`; PostgreSQL identifier-path parsing and validation against source/target snapshots.
- `src/pgschemadiff/infrastructure/config/rename_loader.py`: `load_renames(Path)`, YAML/TOML dispatch and parser-error conversion to `DiffError`.
- `src/pgschemadiff/application/diff/engine.py`: keyword-only `renames` API, explicit table pairing, collision-free default pairing, context-aware comparator dispatch.
- `src/pgschemadiff/application/diff/comparators/column.py` and `table.py`: emit rename deltas and compare old/new column pairs with correct old/new `ObjectRef`s.
- `src/pgschemadiff/application/diff/comparators/index.py` and `constraint.py`: normalize structured column/table references for equality; keep raw SQL expressions untouched and payloads unchanged.
- `tests/unit/application/diff/test_renames.py`: path parsing, annotation validation, and engine integration.
- `tests/infrastructure/test_rename_loader.py`: YAML/TOML parity and parser/extension failures.
- Existing comparator tests: rename pair semantics and structured-reference normalization.
- `TASK_INDEX.md`: status and milestone notes.

## Tasks

### Task 1: Typed annotation contract and loader

**Files:**
- Create `src/pgschemadiff/application/diff/renames.py`
- Create `src/pgschemadiff/infrastructure/config/rename_loader.py`
- Create `tests/unit/application/diff/test_renames.py`
- Create `tests/infrastructure/test_rename_loader.py`

- [x] Test the ADR YAML and equivalent TOML documents produce equal typed annotations.
- [x] Test table paths have two identifiers, column paths have three, quoted identifiers preserve dots/case, and unquoted PostgreSQL identifiers fold to lowercase.
- [x] Test unknown kinds/keys, malformed paths, duplicate endpoints, no-op mappings, unsupported extensions, parse errors, and missing files raise `DiffError`.
- [x] Run the new tests and confirm they fail before implementation (initially failed collection: missing module).
- [x] Implement typed models, parsing, and loader using `yaml.safe_load` and `tomllib`; add no dependency.
- [x] Run both new test files: 19 passed. `TASK_INDEX.md` records loader milestone complete.

### Task 2: Engine pairing and table/column deltas

**Files:**
- Modify `src/pgschemadiff/application/diff/engine.py`
- Modify `src/pgschemadiff/application/diff/comparators/table.py`
- Modify `src/pgschemadiff/application/diff/comparators/column.py`
- Modify `tests/unit/application/diff/test_engine.py`
- Modify `tests/unit/application/diff/comparators/test_table.py`
- Modify `tests/unit/application/diff/comparators/test_column.py`

- [x] Test `diff(..., renames=...)` pairs annotated tables across different `QualifiedName`s and emits one `RenameTable`, not table create/drop.
- [x] Test column annotation emits `RenameColumn`, not column add/drop, and simultaneous supported attribute changes target the new column reference.
- [x] Test unannotated differing names retain current drop/add behavior; same-name tables accept explicit column mappings through the same API contract.
- [x] Test missing endpoints, collisions with unannotated objects, many-to-one mappings, and rename cycles raise `DiffError`.
- [x] Run targeted tests and confirm failures before implementation (`TypeError`: `diff()` did not yet accept `renames`).
- [x] Implement `DiffEngine.diff(..., *, renames=None)`, validation, deterministic pairing, and rename-aware table/column comparison.
- [x] Run engine/table/column tests: 25 focused feature tests pass; `TASK_INDEX.md` records pairing milestone complete.

### Task 3: Structured dependent-reference comparison

**Files:**
- Modify `src/pgschemadiff/application/diff/comparators/index.py`
- Modify `src/pgschemadiff/application/diff/comparators/constraint.py`
- Modify `src/pgschemadiff/application/diff/comparators/table.py`
- Modify `tests/unit/application/diff/comparators/test_index.py`
- Modify `tests/unit/application/diff/comparators/test_constraint.py`

- [x] Test a column rename alone does not cause index or structured constraint replacement solely from updated column names.
- [x] Test FK referenced table/column renames and table partition-parent renames compare semantically through explicit mappings.
- [x] Test actual structural changes still emit replacement deltas and retain original source/target payloads.
- [x] Test raw expression/predicate differences remain visible as existing replace/drop-add deltas.
- [x] Run targeted tests and confirm failures before wiring was complete; integration checks then pass.
- [x] Implement comparison-only normalization for structured references; leave stored models and emitted payloads untouched. Exclusion `column_or_expr` remains untouched because model cannot distinguish identifier from SQL expression.
- [x] Run comparator/engine suites: 219 tests pass; `TASK_INDEX.md` records dependent-reference milestone complete.

### Task 4: Verification and status

- [x] Run full unit suite (1,173 tests including loader tests), Ruff on changed files, formatter check, full mypy (`src tests`), and package build.
- [x] Fix failures within this task; YAML duplicate mapping keys now raise `DiffError` instead of silently taking the last value.
- [x] Update `TASK_INDEX.md` to `done` after all gates passed. Unrelated untracked ZIP remains untouched.
