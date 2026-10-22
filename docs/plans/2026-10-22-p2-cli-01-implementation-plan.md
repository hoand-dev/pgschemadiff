# P2-CLI-01 Diff Command Implementation Plan

> **For agentic workers:** Use `subagent-driven-development` or `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Implement `pgsd diff <source-url> <target-url>` and emit dependency-ordered, typed `DeltaSet` JSON.

**Architecture:** Keep inspection wiring and JSON output in the CLI, comparison in an application use case, and object-specific comparison in comparators. Extend catalog mapping for fields the comparators need; derive structured dependency edges and pass them to the existing topological sorter.

**Tech Stack:** Python 3.13, Pydantic, Typer, psycopg 3, pytest, existing YAML/TOML rename loader. No new dependencies.

**Spec:** `docs/specs/2026-10-22-p2-cli-01-diff-command-design.md`

## Global Constraints

- Accept two live PostgreSQL connection URLs; saved inspect JSON is out of scope.
- `--schema` is repeatable and filters schema-scoped objects in both inspections; extensions remain database-wide.
- `--renames PATH` uses the existing YAML/TOML loader. Ignore rules remain application-only.
- Schema owner/comment and extension comment differences raise `DiffError`; never silently drop them.
- Dependency edges define order; `DeltaBase.sort_key` breaks ties among simultaneously ready deltas.
- CLI errors exit 1 on stderr; connection URLs and credentials must not appear in output or logs.
- Preserve Clean Architecture boundaries and add no dependencies.

---

### Task 1: Populate schema and extension metadata during inspection

**Files:**
- Modify: `src/pgschemadiff/infrastructure/postgres/catalog/schemas.sql`
- Modify: `src/pgschemadiff/infrastructure/postgres/catalog/extensions.sql`
- Modify: `src/pgschemadiff/infrastructure/postgres/inspector.py`
- Test: `tests/unit/infrastructure/postgres/test_inspector.py`
- Modify: `tests/unit/infrastructure/postgres/test_catalog_sql.py`
- Update: `tests/unit/infrastructure/postgres/__snapshots__/test_catalog_sql.ambr`

**Interfaces:**
- Preserve the existing `PgCatalogInspector(pool, *, schemas=None).inspect() -> Database` API.
- Populate `Schema.owner`, `Schema.comment`, `Extension.installed_schema`, and `Extension.comment` from catalog rows.
- Keep `Database.extensions` database-wide when `schemas` is set.

- [x] **Step 1: Write failing inspector tests** for schema owner/comment mapping, extension installed-schema/comment mapping, and database-wide extension results under a schema filter. Extend the existing namedtuple row fixtures with these fields. Update catalog SQL assertions and snapshots to describe the new owner/comment and installed-schema/comment queries.

```python
def test_assemble_maps_schema_and_extension_metadata() -> None:
    inspector = PgCatalogInspector(MagicMock(), schemas=["public"])
    database = inspector._assemble(
        schemas_rows=[_SchemaRow("public", "owner_role", "schema note")],
        tables_rows=[],
        columns_rows=[],
        indexes_rows=[],
        constraints_rows=[],
        extensions_rows=[_ExtensionRow("pgcrypto", "1.3", "extensions", "extension note")],
    )

    assert database.schemas[0].owner == "owner_role"
    assert database.schemas[0].comment == "schema note"
    assert len(database.extensions) == 1
    assert database.extensions[0].installed_schema == "extensions"
    assert database.extensions[0].comment == "extension note"
```

- [x] **Step 2: Verify RED** with `uv run pytest tests/unit/infrastructure/postgres/test_inspector.py tests/unit/infrastructure/postgres/test_catalog_sql.py -q`; failures must show missing metadata and outdated SQL expectations.
- [x] **Step 3: Implement SQL and row mapping.** Add schema owner/comment columns to `schemas.sql`; query installed extensions with their installed namespace and comment in `extensions.sql`; map those values into existing domain fields. Do not filter extensions by `schemas`.
- [x] **Step 4: Verify GREEN** with `uv run pytest tests/unit/infrastructure/postgres/test_inspector.py tests/unit/infrastructure/postgres/test_catalog_sql.py -q` after updating all fixture row shapes and SQL snapshots.

### Task 2: Add schema and extension comparators

**Files:**
- Create: `src/pgschemadiff/application/diff/comparators/schema.py`
- Create: `src/pgschemadiff/application/diff/comparators/extension.py`
- Modify: `src/pgschemadiff/application/diff/comparators/__init__.py`
- Create: `tests/unit/application/diff/comparators/test_schema.py`
- Create: `tests/unit/application/diff/comparators/test_extension.py`

**Interfaces:**
- Both classes implement `Comparator.compare(source: object | None, target: object | None) -> tuple[DeltaBase, ...]`, narrowing values internally to their domain model types.
- Export both comparators from `application.diff.comparators`.

- [x] **Step 1: Write failing tests** for schema and extension create/drop/no-change cases; schema owner/comment mismatch; extension version/schema changes; extension comment mismatch. Assert concrete delta types and payload fields.

```python
import pytest

from pgschemadiff.application.diff.comparators.schema import SchemaComparator
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.shared.errors import DiffError


def _schema(*, owner: str | None = None, comment: str | None = None) -> Schema:
    ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    return Schema(ref=ref, owner=owner, comment=comment)


def test_schema_metadata_change_raises_diff_error() -> None:
    source = _schema(owner="old_owner")
    target = _schema(owner="new_owner")

    with pytest.raises(DiffError, match="owner"):
        SchemaComparator().compare(source, target)
```

- [x] **Step 2: Verify RED** with `uv run pytest tests/unit/application/diff/comparators/test_schema.py tests/unit/application/diff/comparators/test_extension.py -q`.
- [x] **Step 3: Implement the two comparators.** Emit existing schema/extension delta classes; for extensions combine version and installed-schema changes in one `AlterExtension`; raise `DiffError` for unsupported metadata changes. Compare schema metadata only, not child table/index contents.
- [x] **Step 4: Verify GREEN** with the same targeted pytest command and `uv run ruff check src/pgschemadiff/application/diff/comparators tests/unit/application/diff/comparators`.

### Task 3: Derive dependency edges and order deltas

**Files:**
- Create: `src/pgschemadiff/application/diff/dependencies.py`
- Create: `tests/unit/application/diff/test_dependencies.py`

**Interfaces:**
- `order_deltas(delta_set: DeltaSet) -> DeltaSet`
- Use `topological_sort(nodes, dependencies, key=lambda delta: delta.sort_key)`; mapping values are prerequisites of each dependent delta.

- [x] **Step 1: Write failing tests** for schema/table/index/constraint/column prerequisites; schema creation before `CreateExtension` and `AlterExtension(new_schema=...)`; FK dependencies on both owning and referenced tables/columns, including FKs embedded in `CreateTable`/`DropTable` payloads; no self-edge for a self-referencing table delta; drops before dependent drops; index replacement prerequisites from `new_index` and `old_index`; rename-before-new-identity deltas; deterministic unrelated deltas; and cycle propagation.

```python
from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta import AddColumn, CreateIndex, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn


table_ref = ObjectRef(
    kind=ObjectKind.TABLE,
    qname=QualifiedName(namespace="public", name="items"),
)
column = Column(name="sku", position=2, data_type="text")
add_column = AddColumn(
    target=ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="sku"),
        parent=table_ref,
    ),
    column=column,
)
index = Index(
    ref=ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace="public", name="items_sku_idx"),
    ),
    table_ref=table_ref,
    key_columns=(IndexKeyColumn(column_name="sku"),),
)
create_index = CreateIndex(target=index.ref, index=index)


def test_add_column_precedes_index_that_uses_it() -> None:
    ordered = order_deltas(DeltaSet.from_iterable((create_index, add_column)))

    assert ordered.deltas == (add_column, create_index)
```

- [x] **Step 2: Verify RED** with `uv run pytest tests/unit/application/diff/test_dependencies.py -q`.
- [x] **Step 3: Implement structured edge extraction.** Read table/column ownership from `ObjectRef.parent`, index table and column refs from index payloads, FK local/remote refs from `AddConstraint`/`DropConstraint` and table payloads, and extension target schema from `CreateExtension.extension.installed_schema` or `AlterExtension.new_schema`. Add edges only when both deltas are present; skip self-edges; do not parse SQL.
- [x] **Step 4: Verify GREEN** with the targeted test and existing sorter tests: `uv run pytest tests/unit/application/diff/test_dependencies.py tests/unit/application/diff/test_topo_sort.py -q`.

### Task 4: Compose the comparison use case

**Files:**
- Create: `src/pgschemadiff/application/diff/compare_schemas.py`
- Create: `tests/unit/application/diff/test_compare_schemas.py`

**Interfaces:**
- `async def compare_schemas(source_inspector: SchemaInspector, target_inspector: SchemaInspector, *, renames: RenameAnnotations | None = None, ignore: IgnoreRules | None = None) -> DeltaSet`
- Register `SchemaComparator`, `ExtensionComparator`, `TableComparator(column_comparator=ColumnComparator(), constraint_comparator=ConstraintComparator())`, and `IndexComparator` in a fresh `DiffEngine`.

- [x] **Step 1: Write failing async tests** for both inspectors being inspected once, all default comparators participating, programmatic ignore application, rename forwarding, and ordered typed output.

```python
from pgschemadiff.application.diff.compare_schemas import compare_schemas
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import CreateSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema


def _schema() -> Schema:
    return Schema(
        ref=ObjectRef(
            kind=ObjectKind.SCHEMA,
            qname=QualifiedName(namespace="public", name="public"),
        )
    )


class StubInspector:
    def __init__(self, snapshot: Database) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def inspect(self) -> Database:
        self.calls += 1
        return self.snapshot


async def test_compare_schemas_returns_typed_schema_delta() -> None:
    source = StubInspector(Database(name="source"))
    target = StubInspector(Database(name="target", schemas=(_schema(),)))

    result = await compare_schemas(source, target)

    assert source.calls == target.calls == 1
    assert isinstance(result.deltas[0], CreateSchema)
```

- [x] **Step 2: Verify RED** with `uv run pytest tests/unit/application/diff/test_compare_schemas.py -q`.
- [x] **Step 3: Implement `compare_schemas`.** Await both `inspect()` calls, pass snapshots/options to `DiffEngine.diff`, call `order_deltas`, and return the resulting `DeltaSet`; keep serialization and infrastructure construction out of this module.
- [x] **Step 4: Verify GREEN** with the targeted test plus existing diff tests: `uv run pytest tests/unit/application/diff -q`.

### Task 5: Add `pgsd diff` CLI command

**Files:**
- Create: `src/pgschemadiff/presentation/cli/commands/diff.py`
- Modify: `src/pgschemadiff/presentation/cli/main.py`
- Modify: `src/pgschemadiff/infrastructure/postgres/pool.py`
- Create: `tests/unit/presentation/__init__.py`
- Create: `tests/unit/presentation/cli/__init__.py`
- Create: `tests/unit/presentation/cli/test_diff.py`
- Modify: `tests/unit/infrastructure/postgres/test_pool.py`

**Interfaces:**
- CLI command accepts source URL, target URL, repeatable `--schema`, and optional `--renames PATH`.
- The command constructs two pools/inspectors, calls `load_renames(Path)` only when requested, invokes `compare_schemas`, and prints `DeltaSet.model_dump_json(indent=2)`.

- [x] **Step 1: Write failing tests** for command registration, positional URLs, repeated schemas passed unchanged to both inspectors, rename loading, parseable typed JSON, database-wide extension comparison under a schema filter, sanitized `DiffError` handling, error exit code/stderr, and credential redaction from stdout/stderr/captured logs. Add a pool regression test proving an underlying pool is closed when `open()` raises; `__aexit__` does not run when `__aenter__` fails.

```python
import psycopg
from typer.testing import CliRunner

import pgschemadiff.presentation.cli.commands.diff as diff_command
from pgschemadiff.presentation.cli.main import app


class FailingPool:
    async def __aenter__(self) -> FailingPool:
        raise psycopg.OperationalError("password=driver-secret")

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None


def test_connection_error_redacts_dsn_and_driver_message(monkeypatch, caplog) -> None:
    monkeypatch.setattr(diff_command, "Pool", lambda *_args, **_kwargs: FailingPool())

    result = CliRunner().invoke(
        app,
        [
            "diff",
            "postgresql://alice:url-secret@source/db",
            "postgresql://bob:other-secret@target/db",
        ],
    )

    assert result.exit_code == 1
    assert "postgresql://alice:url-secret@source/db" not in result.output
    assert "postgresql://bob:other-secret@target/db" not in result.output
    assert "url-secret" not in result.output
    assert "other-secret" not in result.output
    assert "driver-secret" not in result.output
    assert "driver-secret" not in caplog.text
```

- [x] **Step 2: Verify RED** with `uv run pytest tests/unit/presentation/cli/test_diff.py tests/unit/infrastructure/postgres/test_pool.py -q`.
- [x] **Step 3: Implement command and registration.** Use async `Pool` contexts and the existing `PgCatalogInspector`; report sanitized error categories without rendering raw driver exceptions or logging credentials. Make the shared `Pool.__aenter__` close its created pool if opening fails, covering all callers; keep the existing `inspect` command behavior unchanged otherwise.
- [x] **Step 4: Verify GREEN** with both targeted test files and run `uv run pgsd diff --help` to verify rendered flags without opening a database.

### Task 6: Run project gates and update task state

**Files:**
- Modify: `TASK_INDEX.md`
- Format only: `src/pgschemadiff/application/diff/comparators/__init__.py`
- Format only: `src/pgschemadiff/infrastructure/postgres/inspector.py`
- Format only: `tests/unit/infrastructure/postgres/test_catalog_sql.py`
- Format only: `tests/unit/infrastructure/postgres/test_inspector.py`

- [x] **Step 1: Run all non-integration tests:** `uv run pytest tests/unit -q`.
- [x] **Step 2: Run static gates:** `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src tests`, and `uv run lint-imports`.
- [x] **Step 3: Update P2-CLI-01 in `TASK_INDEX.md`** to done, include the actual implementation/test files, and update the M2 milestone only after gates pass.
- [x] **Step 4: Report integration-test status separately.** Docker-based tests are not required for local acceptance when Docker daemon is unavailable; do not claim they passed unless run successfully.

## Self-review

- Spec coverage: inspector metadata is Task 1; schema/extension comparison is Task 2; dependency ordering (including FK dependencies embedded in whole-table deltas and schema prerequisites for extension relocation) is Task 3; use-case composition and programmatic ignore are Task 4; URL/flags/JSON/errors/redaction are Task 5; acceptance gates and queue state are Task 6.
- No new dependency, CLI ignore syntax, snapshot input, SQL generation, or migration application is introduced.
- Application code uses the `SchemaInspector` protocol and does not import infrastructure or presentation modules.
