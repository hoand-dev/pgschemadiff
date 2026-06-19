"""Unit tests for catalog SQL files (tasks P1-INFRA-02, P1-INFRA-03, P1-INFRA-04).

These tests do NOT require a live PostgreSQL instance.  They verify that:
- All expected SQL files exist and are loadable via ``importlib.resources``
- Each file is non-empty and ends with a trailing newline
- Each file contains expected table references / keyword patterns
- Snapshot tests (syrupy) catch unintended changes to query text

Integration tests that run the queries against a real PG18 instance are
deferred to task P1-TEST-01/P1-TEST-02.
"""

from __future__ import annotations

import importlib.resources
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CATALOG_PKG = "pgschemadiff.infrastructure.postgres.catalog"


def _load_sql(filename: str) -> str:
    """Load a catalog SQL file via importlib.resources."""
    ref = importlib.resources.files(_CATALOG_PKG).joinpath(filename)
    return ref.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Existence and basic structural checks (parametrized)
# ---------------------------------------------------------------------------

_CATALOG_FILES = [
    "tables.sql",
    "columns.sql",
    "indexes.sql",
    "constraints.sql",
    "extensions.sql",
    "schemas.sql",
]


@pytest.mark.unit
@pytest.mark.parametrize("filename", _CATALOG_FILES)
def test_catalog_sql_file_is_loadable(filename: str) -> None:
    """Each SQL file must be loadable via importlib.resources without error."""
    sql = _load_sql(filename)
    assert isinstance(sql, str)
    assert len(sql) > 0


@pytest.mark.unit
@pytest.mark.parametrize("filename", _CATALOG_FILES)
def test_catalog_sql_file_ends_with_newline(filename: str) -> None:
    """Each SQL file must end with exactly one trailing newline."""
    sql = _load_sql(filename)
    assert sql.endswith("\n"), f"{filename} must end with a trailing newline"


# ---------------------------------------------------------------------------
# tables.sql specific checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tables_sql_selects_from_pg_class() -> None:
    sql = _load_sql("tables.sql")
    assert "pg_class" in sql


@pytest.mark.unit
def test_tables_sql_excludes_system_schemas() -> None:
    sql = _load_sql("tables.sql")
    # Must filter out pg_* schemas and information_schema
    assert "pg_%" in sql
    assert "information_schema" in sql


@pytest.mark.unit
def test_tables_sql_filters_relkind() -> None:
    sql = _load_sql("tables.sql")
    # Only ordinary ('r') and partitioned ('p') tables
    assert "'r'" in sql
    assert "'p'" in sql


@pytest.mark.unit
def test_tables_sql_includes_partition_columns() -> None:
    sql = _load_sql("tables.sql")
    assert "partstrat" in sql or "partition_strategy" in sql
    assert "pg_get_partkeydef" in sql or "partition_expr" in sql
    assert "relpartbound" in sql or "partition_bound" in sql


# ---------------------------------------------------------------------------
# columns.sql specific checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_columns_sql_selects_from_pg_attribute() -> None:
    sql = _load_sql("columns.sql")
    assert "pg_attribute" in sql


@pytest.mark.unit
def test_columns_sql_uses_format_type() -> None:
    sql = _load_sql("columns.sql")
    assert "format_type" in sql


@pytest.mark.unit
def test_columns_sql_excludes_dropped_columns() -> None:
    sql = _load_sql("columns.sql")
    assert "attisdropped" in sql


@pytest.mark.unit
def test_columns_sql_excludes_system_columns() -> None:
    sql = _load_sql("columns.sql")
    # Must filter attnum > 0
    assert "attnum > 0" in sql


@pytest.mark.unit
def test_columns_sql_includes_identity_columns() -> None:
    sql = _load_sql("columns.sql")
    assert "attidentity" in sql
    assert "identity_generated" in sql


@pytest.mark.unit
def test_columns_sql_includes_generated_columns() -> None:
    sql = _load_sql("columns.sql")
    assert "attgenerated" in sql
    assert "generated_expr" in sql


# ---------------------------------------------------------------------------
# indexes.sql specific checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_indexes_sql_selects_from_pg_index() -> None:
    sql = _load_sql("indexes.sql")
    assert "pg_index" in sql


@pytest.mark.unit
def test_indexes_sql_uses_pg_get_indexdef() -> None:
    sql = _load_sql("indexes.sql")
    assert "pg_get_indexdef" in sql


@pytest.mark.unit
def test_indexes_sql_joins_pg_am() -> None:
    sql = _load_sql("indexes.sql")
    assert "pg_am" in sql


@pytest.mark.unit
def test_indexes_sql_includes_primary_flag() -> None:
    sql = _load_sql("indexes.sql")
    assert "indisprimary" in sql


@pytest.mark.unit
def test_indexes_sql_includes_exclusion_flag() -> None:
    sql = _load_sql("indexes.sql")
    assert "indisexclusion" in sql


@pytest.mark.unit
def test_indexes_sql_includes_predicate() -> None:
    sql = _load_sql("indexes.sql")
    assert "indpred" in sql
    assert "predicate" in sql


# ---------------------------------------------------------------------------
# constraints.sql specific checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_constraints_sql_selects_from_pg_constraint() -> None:
    sql = _load_sql("constraints.sql")
    assert "pg_constraint" in sql


@pytest.mark.unit
def test_constraints_sql_uses_pg_get_constraintdef() -> None:
    sql = _load_sql("constraints.sql")
    assert "pg_get_constraintdef" in sql


@pytest.mark.unit
def test_constraints_sql_filters_constraint_types() -> None:
    sql = _load_sql("constraints.sql")
    # Must include p (PK), u (unique), c (check), f (FK), x (exclusion)
    for ctype in ("'p'", "'u'", "'c'", "'f'", "'x'"):
        assert ctype in sql, f"constraints.sql must include contype {ctype}"


@pytest.mark.unit
def test_constraints_sql_includes_deferrable_columns() -> None:
    sql = _load_sql("constraints.sql")
    assert "condeferrable" in sql
    assert "condeferred" in sql


@pytest.mark.unit
def test_constraints_sql_includes_fk_reference_columns() -> None:
    sql = _load_sql("constraints.sql")
    assert "ref_schema" in sql
    assert "ref_table" in sql


# ---------------------------------------------------------------------------
# extensions.sql specific checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extensions_sql_selects_from_pg_available_extensions() -> None:
    sql = _load_sql("extensions.sql")
    assert "pg_available_extensions" in sql


@pytest.mark.unit
def test_extensions_sql_filters_installed() -> None:
    sql = _load_sql("extensions.sql")
    assert "installed_version IS NOT NULL" in sql


@pytest.mark.unit
def test_extensions_sql_selects_expected_columns() -> None:
    sql = _load_sql("extensions.sql")
    assert "extension_name" in sql
    assert "default_version" in sql
    assert "installed_version" in sql


# ---------------------------------------------------------------------------
# schemas.sql specific checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schemas_sql_selects_from_pg_namespace() -> None:
    sql = _load_sql("schemas.sql")
    assert "pg_namespace" in sql


@pytest.mark.unit
def test_schemas_sql_excludes_pg_prefix() -> None:
    sql = _load_sql("schemas.sql")
    assert "pg_%" in sql


@pytest.mark.unit
def test_schemas_sql_excludes_information_schema() -> None:
    sql = _load_sql("schemas.sql")
    assert "information_schema" in sql


@pytest.mark.unit
def test_schemas_sql_selects_schema_name_column() -> None:
    sql = _load_sql("schemas.sql")
    assert "schema_name" in sql


# ---------------------------------------------------------------------------
# Snapshot tests — catch unintended query drift
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("filename", _CATALOG_FILES)
def test_catalog_sql_snapshot(filename: str, snapshot: SnapshotAssertion) -> None:
    """Snapshot each SQL file to detect accidental edits."""
    sql = _load_sql(filename)
    assert sql == snapshot
