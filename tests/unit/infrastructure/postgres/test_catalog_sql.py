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
    "enums.sql",
    "composite_types.sql",
    "domain_types.sql",
    "type_prerequisites.sql",
    "sequences.sql",
    "sequence_prerequisites.sql",
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


@pytest.mark.unit
@pytest.mark.parametrize("filename", _CATALOG_FILES)
def test_catalog_sql_file_has_no_like_prefix_filters(filename: str) -> None:
    """``LIKE 'pg_%'`` treats ``_`` as a wildcard and also skips schemas like ``pga``."""
    assert "LIKE 'pg_" not in _load_sql(filename), f"{filename} must use left(..., 3) != 'pg_'"


@pytest.mark.unit
@pytest.mark.parametrize("filename", _CATALOG_FILES)
def test_catalog_sql_file_has_no_bind_placeholders(filename: str) -> None:
    """Catalog queries run without parameters; schema filtering happens in Python.

    A ``%s`` placeholder makes psycopg also parse literal ``%`` characters
    patterns, which breaks the query at run time.
    """
    assert "%s" not in _load_sql(filename), f"{filename} must not use bind placeholders"


# ---------------------------------------------------------------------------
# tables.sql specific checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tables_sql_selects_from_pg_class() -> None:
    sql = _load_sql("tables.sql")
    assert "pg_class" in sql


@pytest.mark.unit
def test_tables_sql_projects_unlogged_persistence() -> None:
    sql = _load_sql("tables.sql")
    assert "c.relpersistence = 'u'" in sql
    assert "AS unlogged" in sql


@pytest.mark.unit
def test_tables_sql_excludes_system_schemas() -> None:
    sql = _load_sql("tables.sql")
    # Must filter out pg_* schemas and information_schema
    assert "3) != 'pg_'" in sql
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


@pytest.mark.unit
def test_columns_sql_qualifies_non_catalog_collations() -> None:
    sql = _load_sql("columns.sql")
    assert "collation_namespace.nspname" in sql
    assert "format('%I.%I', collation_namespace.nspname, col.collname)" in sql
    assert "format('%I', col.collname)" in sql


@pytest.mark.unit
def test_columns_sql_exposes_virtual_generated_columns_for_fail_closed_mapping() -> None:
    sql = _load_sql("columns.sql")
    assert "a.attgenerated = 'v'" in sql
    assert "AS is_virtual_generated" in sql


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


@pytest.mark.unit
def test_indexes_sql_selects_include_columns_and_constraint_owner() -> None:
    sql = _load_sql("indexes.sql")
    assert "i.indnkeyatts" in sql
    assert "i.indnatts" in sql
    assert "pg_catalog.pg_attribute" in sql
    assert "AS include_columns" in sql
    assert "con.conindid = i.indexrelid" in sql
    assert "con.contype IN ('p', 'u', 'x')" in sql
    assert "AS constraint_name" in sql


@pytest.mark.unit
def test_indexes_sql_selects_partitioned_and_parent_attachment_flags() -> None:
    sql = " ".join(_load_sql("indexes.sql").split())

    assert "ic.relkind = 'I' AS partitioned" in sql
    assert (
        "EXISTS (SELECT 1 FROM pg_catalog.pg_inherits WHERE inhrelid = i.indexrelid) "
        "AS attached_to_parent"
    ) in sql


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


@pytest.mark.unit
def test_constraints_sql_selects_inherited_status() -> None:
    sql = _load_sql("constraints.sql")
    assert "(con.conparentid <> 0 OR NOT con.conislocal)         AS inherited" in sql


# ---------------------------------------------------------------------------
# extensions.sql specific checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extensions_sql_selects_installed_extensions() -> None:
    sql = _load_sql("extensions.sql")
    assert "FROM pg_catalog.pg_extension AS e" in sql


@pytest.mark.unit
def test_extensions_sql_joins_installed_schema_and_reads_comment() -> None:
    sql = _load_sql("extensions.sql")
    assert "LEFT JOIN pg_catalog.pg_namespace AS n ON n.oid = e.extnamespace" in sql
    assert "n.nspname AS installed_schema" in sql
    assert "pg_catalog.obj_description(e.oid, 'pg_extension') AS comment" in sql


@pytest.mark.unit
def test_extensions_sql_selects_expected_columns() -> None:
    sql = _load_sql("extensions.sql")
    assert "extension_name" in sql
    assert "installed_version" in sql
    assert "installed_schema" in sql
    assert "comment" in sql


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
    assert "3) != 'pg_'" in sql


@pytest.mark.unit
def test_schemas_sql_excludes_information_schema() -> None:
    sql = _load_sql("schemas.sql")
    assert "information_schema" in sql


@pytest.mark.unit
def test_schemas_sql_selects_schema_name_column() -> None:
    sql = _load_sql("schemas.sql")
    assert "schema_name" in sql


@pytest.mark.unit
def test_schemas_sql_selects_owner_and_comment() -> None:
    sql = _load_sql("schemas.sql")
    assert "pg_catalog.pg_get_userbyid(n.nspowner) AS owner" in sql
    assert "pg_catalog.obj_description(n.oid, 'pg_namespace') AS comment" in sql


@pytest.mark.unit
@pytest.mark.parametrize(
    "filename",
    [
        pytest.param("schemas.sql"),
        pytest.param("tables.sql"),
        pytest.param("columns.sql"),
        pytest.param("constraints.sql"),
        pytest.param("indexes.sql"),
        pytest.param("enums.sql"),
        pytest.param("composite_types.sql"),
        pytest.param("domain_types.sql"),
        pytest.param("type_prerequisites.sql"),
        pytest.param("sequences.sql"),
        pytest.param("sequence_prerequisites.sql"),
    ],
)
def test_catalog_sql_excludes_reserved_history_schema(filename: str) -> None:
    sql = _load_sql(filename)
    assert "!= 'information_schema'" in sql
    assert "!= 'pgschemadiff'" in sql


@pytest.mark.unit
def test_enums_sql_preserves_postgres_label_order_and_owner() -> None:
    sql = _load_sql("enums.sql")
    assert "pg_enum" in sql
    assert "enumlabel" in sql
    assert "enumsortorder" in sql
    assert "pg_get_userbyid(t.typowner) AS owner" in sql
    assert "ORDER BY e.enumsortorder" in sql


@pytest.mark.unit
def test_enums_sql_excludes_extension_owned_types() -> None:
    sql = _load_sql("enums.sql")
    assert "pg_depend" in sql
    assert "deptype = 'e'" in sql
    assert "pg_type" in sql
    assert "n.nspname != 'pgschemadiff'" in sql


@pytest.mark.unit
def test_composite_types_sql_selects_only_standalone_composite_relations() -> None:
    sql = _load_sql("composite_types.sql")

    assert "t.typtype = 'c'" in sql
    assert "composite_relation.relkind = 'c'" in sql
    assert "a.attnum AS attribute_position" in sql
    assert "format_type(a.atttypid, a.atttypmod)" in sql
    assert "a.attnum > 0" in sql
    assert "NOT a.attisdropped" in sql
    assert "pg_get_userbyid(t.typowner) AS owner" in sql
    assert "attcollation" in sql


@pytest.mark.unit
def test_composite_types_sql_excludes_system_reserved_and_extension_types() -> None:
    sql = _load_sql("composite_types.sql")

    assert "left(n.nspname, 3) != 'pg_'" in sql
    assert "n.nspname != 'information_schema'" in sql
    assert "n.nspname != 'pgschemadiff'" in sql
    assert "pg_depend" in sql
    assert "deptype = 'e'" in sql


@pytest.mark.unit
def test_domain_types_sql_selects_metadata_checks_validation_and_container_use() -> None:
    sql = _load_sql("domain_types.sql")

    for expected in (
        "pg_type",
        "typbasetype",
        "typcollation",
        "typdefaultbin",
        "typnotnull",
        "pg_constraint",
        "convalidated",
        "pg_get_expr",
        "pg_get_userbyid(t.typowner)",
        "used_in_container",
        "pg_range",
        "pg_attribute",
        "typelem",
        "typbasetype",
    ):
        assert expected in sql


@pytest.mark.unit
def test_domain_types_sql_excludes_system_reserved_and_extension_domains() -> None:
    sql = _load_sql("domain_types.sql")

    assert "typtype = 'd'" in sql
    assert "3) != 'pg_'" in sql
    assert "!= 'information_schema'" in sql
    assert "!= 'pgschemadiff'" in sql
    assert "pg_depend" in sql
    assert "deptype = 'e'" in sql


@pytest.mark.unit
def test_type_prerequisites_sql_follows_enum_array_element_types() -> None:
    sql = _load_sql("type_prerequisites.sql")
    assert "pg_attribute" in sql
    assert "atttypid" in sql
    assert "typelem" in sql
    assert "typtype = 'e'" in sql
    assert "typtype = 'c'" in sql
    assert "typtype = 'd'" in sql
    assert "'domain_type'::text AS dependent_kind" in sql
    assert "domain_type" in sql
    assert "DISTINCT" in sql


@pytest.mark.unit
def test_type_prerequisites_sql_excludes_system_and_extension_types() -> None:
    sql = _load_sql("type_prerequisites.sql")
    assert "3) != 'pg_'" in sql
    assert "!= 'information_schema'" in sql
    assert "!= 'pgschemadiff'" in sql
    assert "pg_depend" in sql
    assert "deptype = 'e'" in sql


@pytest.mark.unit
def test_sequences_sql_selects_options_owner_and_owned_column() -> None:
    sql = _load_sql("sequences.sql")

    for expected in (
        "pg_sequence",
        "seqstart",
        "seqincrement",
        "seqmin",
        "seqmax",
        "seqcache",
        "seqcycle",
        "pg_get_userbyid(sequence_class.relowner)",
        "owned_column",
    ):
        assert expected in sql


@pytest.mark.unit
def test_sequences_sql_excludes_identity_extension_and_system_sequences() -> None:
    sql = _load_sql("sequences.sql")

    assert "relkind = 'S'" in sql
    assert "deptype = 'i'" in sql
    assert "deptype = 'e'" in sql
    assert "left(sequence_namespace.nspname, 3) != 'pg_'" in sql
    assert "nspname != 'information_schema'" in sql
    assert "nspname != 'pgschemadiff'" in sql


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filename", "prefix_filters"),
    [
        ("sequences.sql", ("left(sequence_namespace.nspname, 3) != 'pg_'",)),
        (
            "sequence_prerequisites.sql",
            (
                "left(table_namespace.nspname, 3) != 'pg_'",
                "left(sequence_namespace.nspname, 3) != 'pg_'",
            ),
        ),
    ],
)
def test_sequence_catalog_sql_filters_literal_pg_prefix(
    filename: str, prefix_filters: tuple[str, ...]
) -> None:
    sql = " ".join(_load_sql(filename).split())

    for prefix_filter in prefix_filters:
        assert prefix_filter in sql
    assert "NOT LIKE 'pg_%'" not in sql


@pytest.mark.unit
def test_sequence_prerequisites_sql_uses_catalog_dependencies_not_default_parsing() -> None:
    sql = _load_sql("sequence_prerequisites.sql")

    assert "pg_attrdef" in sql
    assert "pg_depend" in sql
    assert "deptype = 'n'" in sql
    assert "dependent_column" in sql
    assert "sequence_schema" in sql
    assert "sequence_name" in sql
    assert "nextval" not in sql


# ---------------------------------------------------------------------------
# Snapshot tests — catch unintended query drift
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("filename", _CATALOG_FILES)
def test_catalog_sql_snapshot(filename: str, snapshot: SnapshotAssertion) -> None:
    """Snapshot each SQL file to detect accidental edits."""
    sql = _load_sql(filename)
    assert sql == snapshot
