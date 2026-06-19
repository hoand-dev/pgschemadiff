"""Unit tests for ``pgschemadiff.infrastructure.postgres.inspector`` (task P1-INFRA-05).

These tests do NOT require a live PostgreSQL instance.  They verify:

- ``PgCatalogInspector`` is importable and satisfies the ``SchemaInspector``
  protocol.
- ``inspect()`` calls all 6 SQL queries via the mocked connection.
- Schema filter (``schemas=["public"]``) excludes non-matching schemas.
- Column rows are correctly mapped to :class:`Column` domain objects.
- Each constraint type (p/u/c/f/x) is dispatched to the right domain class.
- The returned :class:`Database` is a valid, frozen Pydantic v2 object.
- Helper functions (_map_deferrability, _map_fk_action, _map_fk_match,
  _map_index_method, _map_partition_strategy, _parse_index_key_columns, etc.)
  behave correctly in isolation.
"""

from __future__ import annotations

from collections import namedtuple
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.column import GeneratedTiming, IdentitySpec
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ConstraintDeferrability,
    ExclusionConstraint,
    FKAction,
    FKMatch,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.index import IndexMethod, NullsOrder, SortOrder
from pgschemadiff.domain.ports import SchemaInspector
from pgschemadiff.domain.table import PartitionStrategy
from pgschemadiff.infrastructure.postgres.inspector import (
    PgCatalogInspector,
    _build_partition_info,
    _build_partition_of,
    _extract_paren_body,
    _map_check_constraint,
    _map_column,
    _map_constraint,
    _map_deferrability,
    _map_fk_action,
    _map_fk_constraint,
    _map_fk_match,
    _map_index_method,
    _map_partition_strategy,
    _map_pk_constraint,
    _map_unique_constraint,
    _parse_exclusion_elements,
    _parse_index_key_columns,
    _parse_key_column_entry,
    _split_top_level_commas,
)
from pgschemadiff.shared.errors import InspectionError

# ---------------------------------------------------------------------------
# Row factories — mimic namedtuple_row output
# ---------------------------------------------------------------------------

_SchemaRow = namedtuple("_SchemaRow", ["schema_name"])
_TableRow = namedtuple(
    "_TableRow",
    [
        "schema_name",
        "table_name",
        "persistence",
        "partition_strategy",
        "partition_expr",
        "partition_of_schema",
        "partition_of_table",
        "partition_bound",
    ],
)
_ColumnRow = namedtuple(
    "_ColumnRow",
    [
        "schema_name",
        "table_name",
        "column_name",
        "ordinal_position",
        "data_type",
        "is_nullable",
        "default_expr",
        "collation",
        "is_identity",
        "identity_generated",
        "is_generated",
        "generated_expr",
    ],
)
_IndexRow = namedtuple(
    "_IndexRow",
    [
        "schema_name",
        "table_name",
        "index_name",
        "index_method",
        "is_unique",
        "is_primary",
        "is_exclusion",
        "index_definition",
        "predicate",
    ],
)
_ConstraintRow = namedtuple(
    "_ConstraintRow",
    [
        "schema_name",
        "table_name",
        "constraint_name",
        "constraint_type",
        "definition",
        "ref_schema",
        "ref_table",
        "deferrable",
        "initially_deferred",
    ],
)
_ExtensionRow = namedtuple(
    "_ExtensionRow",
    ["extension_name", "default_version", "installed_version"],
)


def _make_table_row(
    schema: str = "public",
    table: str = "users",
    *,
    partition_strategy: str | None = None,
    partition_expr: str | None = None,
    partition_of_schema: str | None = None,
    partition_of_table: str | None = None,
    partition_bound: str | None = None,
) -> Any:
    return _TableRow(
        schema_name=schema,
        table_name=table,
        persistence="p",
        partition_strategy=partition_strategy,
        partition_expr=partition_expr,
        partition_of_schema=partition_of_schema,
        partition_of_table=partition_of_table,
        partition_bound=partition_bound,
    )


def _make_column_row(
    schema: str = "public",
    table: str = "users",
    column: str = "id",
    *,
    position: int = 1,
    data_type: str = "integer",
    nullable: bool = False,
    default_expr: str | None = None,
    collation: str | None = None,
    is_identity: bool = False,
    identity_generated: str | None = None,
    is_generated: bool = False,
    generated_expr: str | None = None,
) -> Any:
    return _ColumnRow(
        schema_name=schema,
        table_name=table,
        column_name=column,
        ordinal_position=position,
        data_type=data_type,
        is_nullable=nullable,
        default_expr=default_expr,
        collation=collation,
        is_identity=is_identity,
        identity_generated=identity_generated,
        is_generated=is_generated,
        generated_expr=generated_expr,
    )


def _make_constraint_row(
    schema: str = "public",
    table: str = "users",
    name: str = "users_pkey",
    *,
    constraint_type: str = "p",
    definition: str = "PRIMARY KEY (id)",
    ref_schema: str | None = None,
    ref_table: str | None = None,
    deferrable: bool = False,
    initially_deferred: bool = False,
) -> Any:
    return _ConstraintRow(
        schema_name=schema,
        table_name=table,
        constraint_name=name,
        constraint_type=constraint_type,
        definition=definition,
        ref_schema=ref_schema,
        ref_table=ref_table,
        deferrable=deferrable,
        initially_deferred=initially_deferred,
    )


def _make_index_row(
    schema: str = "public",
    table: str = "users",
    index: str = "users_email_idx",
    *,
    method: str = "btree",
    is_unique: bool = False,
    definition: str = "CREATE INDEX users_email_idx ON public.users USING btree (email)",
    predicate: str | None = None,
) -> Any:
    return _IndexRow(
        schema_name=schema,
        table_name=table,
        index_name=index,
        index_method=method,
        is_unique=is_unique,
        is_primary=False,
        is_exclusion=False,
        index_definition=definition,
        predicate=predicate,
    )


def _make_extension_row(
    name: str = "pgcrypto",
    installed: str = "1.3",
    default: str = "1.3",
) -> Any:
    return _ExtensionRow(
        extension_name=name,
        installed_version=installed,
        default_version=default,
    )


# ---------------------------------------------------------------------------
# Mock pool + connection factory
# ---------------------------------------------------------------------------


def _build_mock_pool(
    schemas_rows: list[Any] | None = None,
    tables_rows: list[Any] | None = None,
    columns_rows: list[Any] | None = None,
    indexes_rows: list[Any] | None = None,
    constraints_rows: list[Any] | None = None,
    extensions_rows: list[Any] | None = None,
) -> MagicMock:
    """Build a mock Pool that yields a mocked psycopg connection.

    The cursor's ``fetchall`` is wired to return rows in this order:
    schemas → tables → columns → indexes → constraints → extensions.
    """
    fetch_sequence = [
        schemas_rows or [],
        tables_rows or [],
        columns_rows or [],
        indexes_rows or [],
        constraints_rows or [],
        extensions_rows or [],
    ]

    cur = AsyncMock()
    cur.execute = AsyncMock()
    cur.fetchall = AsyncMock(side_effect=fetch_sequence)
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)

    conn = AsyncMock()
    conn.set_autocommit = AsyncMock()
    conn.execute = AsyncMock()
    conn.cursor = MagicMock(return_value=cur)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)

    # acquire() is an async context manager that yields the connection
    pool = MagicMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)

    return pool


# ===========================================================================
# Tests: Protocol compliance
# ===========================================================================


@pytest.mark.unit
def test_inspector_satisfies_schema_inspector_protocol() -> None:
    """PgCatalogInspector must satisfy the SchemaInspector runtime-checkable Protocol."""
    pool = MagicMock()
    inspector = PgCatalogInspector(pool)
    assert isinstance(inspector, SchemaInspector)


@pytest.mark.unit
def test_inspector_is_importable() -> None:
    assert PgCatalogInspector is not None


# ===========================================================================
# Tests: inspect() calls all 6 queries
# ===========================================================================


@pytest.mark.unit
async def test_inspect_calls_all_six_queries() -> None:
    """inspect() must execute exactly 6 SQL queries (one per catalog file)."""
    pool = _build_mock_pool(
        schemas_rows=[_SchemaRow("public")],
        tables_rows=[],
        columns_rows=[],
        indexes_rows=[],
        constraints_rows=[],
        extensions_rows=[],
    )
    inspector = PgCatalogInspector(pool)
    result = await inspector.inspect()

    # fetchall should have been called 6 times (one per catalog SQL file)
    cur = pool.acquire.return_value.__aenter__.return_value.cursor.return_value
    assert cur.fetchall.call_count == 6
    assert isinstance(result, Database)


@pytest.mark.unit
async def test_inspect_starts_repeatable_read_transaction() -> None:
    """inspect() must issue BEGIN ISOLATION LEVEL REPEATABLE READ."""
    pool = _build_mock_pool()
    inspector = PgCatalogInspector(pool)
    await inspector.inspect()

    conn = pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_any_call("BEGIN ISOLATION LEVEL REPEATABLE READ")


@pytest.mark.unit
async def test_inspect_rollback_in_finally() -> None:
    """inspect() must issue ROLLBACK even when no error occurs."""
    pool = _build_mock_pool()
    inspector = PgCatalogInspector(pool)
    await inspector.inspect()

    conn = pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_any_call("ROLLBACK")


# ===========================================================================
# Tests: schema filter
# ===========================================================================


@pytest.mark.unit
async def test_schema_filter_excludes_non_matching() -> None:
    """When schemas=['public'], only 'public' schema should appear in the result."""
    pool = _build_mock_pool(
        schemas_rows=[_SchemaRow("public"), _SchemaRow("audit")],
        tables_rows=[
            _make_table_row("public", "users"),
            _make_table_row("audit", "logs"),
        ],
        columns_rows=[
            _make_column_row("public", "users", "id"),
            _make_column_row("audit", "logs", "id"),
        ],
    )
    inspector = PgCatalogInspector(pool, schemas=["public"])
    result = await inspector.inspect()

    schema_names = [s.name for s in result.schemas]
    assert "public" in schema_names
    assert "audit" not in schema_names


@pytest.mark.unit
async def test_schema_filter_none_includes_all() -> None:
    """When schemas=None, all schemas returned by the DB query are included."""
    pool = _build_mock_pool(
        schemas_rows=[_SchemaRow("public"), _SchemaRow("audit")],
    )
    inspector = PgCatalogInspector(pool, schemas=None)
    result = await inspector.inspect()

    schema_names = [s.name for s in result.schemas]
    assert "public" in schema_names
    assert "audit" in schema_names


# ===========================================================================
# Tests: column mapping
# ===========================================================================


@pytest.mark.unit
def test_map_column_plain() -> None:
    """A plain column row should produce a Column with no identity or generated."""
    row = _make_column_row(
        column="email",
        position=2,
        data_type="text",
        nullable=True,
        default_expr=None,
    )
    col = _map_column(row)
    assert col.name == "email"
    assert col.position == 2
    assert col.data_type == "text"
    assert col.nullable is True
    assert col.identity is None
    assert col.generated_expression is None
    assert col.default_expr is None


@pytest.mark.unit
def test_map_column_with_default() -> None:
    """A column row with a default expression should set default_expr."""
    row = _make_column_row(column="created_at", default_expr="now()")
    col = _map_column(row)
    assert col.default_expr == "now()"


@pytest.mark.unit
def test_map_column_identity_always() -> None:
    """An IDENTITY ALWAYS column should have an IdentitySpec with ALWAYS."""
    row = _make_column_row(
        column="id",
        is_identity=True,
        identity_generated="ALWAYS",
    )
    col = _map_column(row)
    assert col.identity is not None
    assert col.identity.generated == GeneratedTiming.ALWAYS
    assert col.default_expr is None


@pytest.mark.unit
def test_map_column_identity_by_default() -> None:
    """An IDENTITY BY DEFAULT column should have an IdentitySpec with BY_DEFAULT."""
    row = _make_column_row(
        column="id",
        is_identity=True,
        identity_generated="BY DEFAULT",
    )
    col = _map_column(row)
    assert isinstance(col.identity, IdentitySpec)
    assert col.identity.generated == GeneratedTiming.BY_DEFAULT


@pytest.mark.unit
def test_map_column_generated() -> None:
    """A GENERATED ALWAYS AS STORED column should set generated_expression."""
    row = _make_column_row(
        column="full_name",
        data_type="text",
        is_generated=True,
        generated_expr="first_name || ' ' || last_name",
    )
    col = _map_column(row)
    assert col.generated_expression == "first_name || ' ' || last_name"
    assert col.default_expr is None
    assert col.identity is None


@pytest.mark.unit
def test_map_column_with_collation() -> None:
    """A column with a non-default collation should set collation."""
    row = _make_column_row(column="name", collation="en_US.utf8")
    col = _map_column(row)
    assert col.collation == "en_US.utf8"


# ===========================================================================
# Tests: constraint dispatch
# ===========================================================================


@pytest.mark.unit
def test_map_constraint_primary_key() -> None:
    """Constraint type 'p' should produce PrimaryKeyConstraint."""
    row = _make_constraint_row(
        name="users_pkey",
        constraint_type="p",
        definition="PRIMARY KEY (id)",
    )
    ct = _map_constraint(row)
    assert isinstance(ct, PrimaryKeyConstraint)
    assert ct.name == "users_pkey"
    assert ct.columns == ("id",)


@pytest.mark.unit
def test_map_constraint_primary_key_composite() -> None:
    """PK with multiple columns should produce a tuple of column names."""
    row = _make_constraint_row(
        constraint_type="p",
        definition="PRIMARY KEY (tenant_id, user_id)",
    )
    ct = _map_pk_constraint(
        row.constraint_name, row.definition, ConstraintDeferrability.NOT_DEFERRABLE
    )
    assert ct.columns == ("tenant_id", "user_id")


@pytest.mark.unit
def test_map_constraint_unique() -> None:
    """Constraint type 'u' should produce UniqueConstraint."""
    row = _make_constraint_row(
        name="users_email_key",
        constraint_type="u",
        definition="UNIQUE (email)",
    )
    ct = _map_constraint(row)
    assert isinstance(ct, UniqueConstraint)
    assert ct.columns == ("email",)
    assert ct.nulls_not_distinct is False


@pytest.mark.unit
def test_map_constraint_unique_nulls_not_distinct() -> None:
    """NULLS NOT DISTINCT should set the flag on UniqueConstraint."""
    ct = _map_unique_constraint(
        "u1",
        "UNIQUE NULLS NOT DISTINCT (email)",
        ConstraintDeferrability.NOT_DEFERRABLE,
    )
    assert ct.nulls_not_distinct is True


@pytest.mark.unit
def test_map_constraint_check() -> None:
    """Constraint type 'c' should produce CheckConstraint."""
    row = _make_constraint_row(
        name="users_age_check",
        constraint_type="c",
        definition="CHECK ((age > 0))",
    )
    ct = _map_constraint(row)
    assert isinstance(ct, CheckConstraint)
    assert "age" in ct.expression


@pytest.mark.unit
def test_map_constraint_check_no_inherit() -> None:
    """NO INHERIT in CHECK definition should set the flag."""
    ct = _map_check_constraint(
        "chk",
        "CHECK ((x > 0)) NO INHERIT",
        ConstraintDeferrability.NOT_DEFERRABLE,
    )
    assert ct.no_inherit is True


@pytest.mark.unit
def test_map_constraint_foreign_key() -> None:
    """Constraint type 'f' should produce ForeignKeyConstraint."""
    row = _make_constraint_row(
        name="orders_user_id_fkey",
        constraint_type="f",
        definition="FOREIGN KEY (user_id) REFERENCES public.users (id)",
        ref_schema="public",
        ref_table="users",
    )
    ct = _map_constraint(row)
    assert isinstance(ct, ForeignKeyConstraint)
    assert ct.columns == ("user_id",)
    assert ct.ref_namespace == "public"
    assert ct.ref_table == "users"
    assert ct.ref_columns == ("id",)


@pytest.mark.unit
def test_map_constraint_foreign_key_actions() -> None:
    """ON DELETE CASCADE / ON UPDATE SET NULL should be parsed from definition."""
    ct = _map_fk_constraint(
        "fk",
        "FOREIGN KEY (x) REFERENCES t (id) ON DELETE CASCADE ON UPDATE SET NULL",
        ConstraintDeferrability.NOT_DEFERRABLE,
        MagicMock(ref_schema=None, ref_table=None),
    )
    assert ct.on_delete == FKAction.CASCADE
    assert ct.on_update == FKAction.SET_NULL


@pytest.mark.unit
def test_map_constraint_foreign_key_match_full() -> None:
    """MATCH FULL should be parsed from definition."""
    ct = _map_fk_constraint(
        "fk",
        "FOREIGN KEY (x) REFERENCES t (id) MATCH FULL",
        ConstraintDeferrability.NOT_DEFERRABLE,
        MagicMock(ref_schema=None, ref_table=None),
    )
    assert ct.match_type == FKMatch.FULL


@pytest.mark.unit
def test_map_constraint_exclusion() -> None:
    """Constraint type 'x' should produce ExclusionConstraint."""
    row = _make_constraint_row(
        name="room_excl",
        constraint_type="x",
        definition="EXCLUDE USING gist (room WITH =, during WITH &&)",
    )
    ct = _map_constraint(row)
    assert isinstance(ct, ExclusionConstraint)
    assert ct.index_method == "gist"
    assert len(ct.elements) >= 1


@pytest.mark.unit
def test_map_constraint_unknown_type_raises() -> None:
    """An unknown constraint type should raise InspectionError."""
    row = _make_constraint_row(constraint_type="z", definition="???")
    with pytest.raises(InspectionError, match="Unknown constraint type"):
        _map_constraint(row)


# ===========================================================================
# Tests: deferrability mapping
# ===========================================================================


@pytest.mark.unit
def test_deferrability_not_deferrable() -> None:
    assert _map_deferrability(False, False) == ConstraintDeferrability.NOT_DEFERRABLE


@pytest.mark.unit
def test_deferrability_initially_immediate() -> None:
    assert _map_deferrability(True, False) == ConstraintDeferrability.DEFERRABLE_INITIALLY_IMMEDIATE


@pytest.mark.unit
def test_deferrability_initially_deferred() -> None:
    assert _map_deferrability(True, True) == ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED


# ===========================================================================
# Tests: _map_fk_action and _map_fk_match
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CASCADE", FKAction.CASCADE),
        ("cascade", FKAction.CASCADE),
        ("RESTRICT", FKAction.RESTRICT),
        ("SET NULL", FKAction.SET_NULL),
        ("SET DEFAULT", FKAction.SET_DEFAULT),
        ("NO ACTION", FKAction.NO_ACTION),
        ("unknown", FKAction.NO_ACTION),
    ],
)
def test_map_fk_action(text: str, expected: FKAction) -> None:
    assert _map_fk_action(text) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("FULL", FKMatch.FULL),
        ("PARTIAL", FKMatch.PARTIAL),
        ("SIMPLE", FKMatch.SIMPLE),
        ("other", FKMatch.SIMPLE),
    ],
)
def test_map_fk_match(text: str, expected: FKMatch) -> None:
    assert _map_fk_match(text) == expected


# ===========================================================================
# Tests: index key column parsing
# ===========================================================================


@pytest.mark.unit
def test_parse_index_key_columns_simple() -> None:
    """Simple single-column btree index definition."""
    defn = "CREATE INDEX i ON t USING btree (email)"
    keys = _parse_index_key_columns(defn)
    assert len(keys) == 1
    assert keys[0].column_name == "email"
    assert keys[0].sort_order == SortOrder.ASC


@pytest.mark.unit
def test_parse_index_key_columns_multi() -> None:
    """Multi-column index."""
    defn = "CREATE INDEX i ON t USING btree (last_name, first_name)"
    keys = _parse_index_key_columns(defn)
    assert len(keys) == 2
    assert keys[0].column_name == "last_name"
    assert keys[1].column_name == "first_name"


@pytest.mark.unit
def test_parse_index_key_columns_desc() -> None:
    """DESC sort order should be parsed."""
    defn = "CREATE INDEX i ON t USING btree (created_at DESC)"
    keys = _parse_index_key_columns(defn)
    assert keys[0].sort_order == SortOrder.DESC


@pytest.mark.unit
def test_parse_index_key_columns_nulls_first() -> None:
    """NULLS FIRST should be captured."""
    defn = "CREATE INDEX i ON t USING btree (score DESC NULLS FIRST)"
    keys = _parse_index_key_columns(defn)
    assert keys[0].nulls_order == NullsOrder.FIRST


@pytest.mark.unit
def test_parse_index_key_columns_expression() -> None:
    """Expression index key should set ``expression`` not ``column_name``."""
    entry = _parse_key_column_entry("(lower(email))")
    assert entry.expression is not None
    assert entry.column_name is None


@pytest.mark.unit
def test_map_index_method_known() -> None:
    assert _map_index_method("btree") == IndexMethod.BTREE
    assert _map_index_method("hash") == IndexMethod.HASH
    assert _map_index_method("gist") == IndexMethod.GIST
    assert _map_index_method("gin") == IndexMethod.GIN


@pytest.mark.unit
def test_map_index_method_unknown_falls_back() -> None:
    """An unknown method name should fall back to BTREE."""
    assert _map_index_method("custom_am") == IndexMethod.BTREE


# ===========================================================================
# Tests: partition helpers
# ===========================================================================


@pytest.mark.unit
def test_map_partition_strategy() -> None:
    assert _map_partition_strategy("r") == PartitionStrategy.RANGE
    assert _map_partition_strategy("l") == PartitionStrategy.LIST
    assert _map_partition_strategy("h") == PartitionStrategy.HASH


@pytest.mark.unit
def test_build_partition_info_present() -> None:
    row = _make_table_row(partition_strategy="r", partition_expr="created_at")
    info = _build_partition_info(row)
    assert info is not None
    assert info.strategy == PartitionStrategy.RANGE
    assert info.partition_key == "created_at"


@pytest.mark.unit
def test_build_partition_info_absent() -> None:
    row = _make_table_row()
    assert _build_partition_info(row) is None


@pytest.mark.unit
def test_build_partition_of_present() -> None:
    row = _make_table_row(
        partition_of_schema="public",
        partition_of_table="orders",
        partition_bound="FOR VALUES FROM (1) TO (100)",
    )
    po = _build_partition_of(row)
    assert po is not None
    assert po.parent_namespace == "public"
    assert po.parent_name == "orders"
    assert po.partition_bound == "FOR VALUES FROM (1) TO (100)"


@pytest.mark.unit
def test_build_partition_of_absent() -> None:
    row = _make_table_row()
    assert _build_partition_of(row) is None


# ===========================================================================
# Tests: exclusion element parsing
# ===========================================================================


@pytest.mark.unit
def test_parse_exclusion_elements_single() -> None:
    elements = _parse_exclusion_elements("room WITH =")
    assert len(elements) == 1
    assert elements[0].column_or_expr == "room"
    assert elements[0].operator == "="


@pytest.mark.unit
def test_parse_exclusion_elements_multiple() -> None:
    elements = _parse_exclusion_elements("room WITH =, during WITH &&")
    assert len(elements) == 2


@pytest.mark.unit
def test_parse_exclusion_elements_fallback() -> None:
    """When the body has no WITH tokens, fall back to a minimal element."""
    elements = _parse_exclusion_elements("garbage no operators here")
    assert len(elements) == 1
    assert elements[0].column_or_expr == "?"


# ===========================================================================
# Tests: _extract_paren_body and _split_top_level_commas
# ===========================================================================


@pytest.mark.unit
def test_extract_paren_body_basic() -> None:
    assert _extract_paren_body("foo(a, b)bar") == "a, b"


@pytest.mark.unit
def test_extract_paren_body_nested() -> None:
    # Should return body of outermost pair
    assert _extract_paren_body("(a, (b, c), d)") == "a, (b, c), d"


@pytest.mark.unit
def test_extract_paren_body_none() -> None:
    assert _extract_paren_body("no parens here") is None


@pytest.mark.unit
def test_split_top_level_commas_simple() -> None:
    assert _split_top_level_commas("a, b, c") == ["a", "b", "c"]


@pytest.mark.unit
def test_split_top_level_commas_nested() -> None:
    # Commas inside parens must not split
    result = _split_top_level_commas("func(a, b), c")
    assert result == ["func(a, b)", "c"]


# ===========================================================================
# Tests: full inspect() round-trip returning a valid Database
# ===========================================================================


@pytest.mark.unit
async def test_inspect_returns_database() -> None:
    """A minimal mock should produce a valid Database domain object."""
    pool = _build_mock_pool(
        schemas_rows=[_SchemaRow("public")],
        tables_rows=[_make_table_row("public", "users")],
        columns_rows=[
            _make_column_row("public", "users", "id", position=1, data_type="integer"),
            _make_column_row("public", "users", "email", position=2, data_type="text"),
        ],
        indexes_rows=[
            _make_index_row(
                "public",
                "users",
                "users_email_idx",
                definition="CREATE INDEX users_email_idx ON public.users USING btree (email)",
            )
        ],
        constraints_rows=[
            _make_constraint_row(
                "public",
                "users",
                "users_pkey",
                constraint_type="p",
                definition="PRIMARY KEY (id)",
            )
        ],
        extensions_rows=[_make_extension_row("pgcrypto", "1.3", "1.3")],
    )

    inspector = PgCatalogInspector(pool)
    db = await inspector.inspect()

    assert isinstance(db, Database)
    assert len(db.schemas) == 1
    schema = db.schemas[0]
    assert schema.name == "public"
    assert len(schema.tables) == 1
    table = schema.tables[0]
    assert table.ref.qname.name == "users"
    assert len(table.columns) == 2
    assert len(table.constraints) == 1
    assert len(schema.indexes) == 1
    assert len(db.extensions) == 1
    assert db.extensions[0].name == "pgcrypto"


@pytest.mark.unit
async def test_inspect_with_extension() -> None:
    """Extension rows should be mapped correctly to Extension domain objects."""
    pool = _build_mock_pool(
        extensions_rows=[
            _make_extension_row("postgis", "3.3", "3.3"),
            _make_extension_row("pgcrypto", "1.3", "1.3"),
        ],
    )
    inspector = PgCatalogInspector(pool)
    db = await inspector.inspect()

    ext_names = [e.name for e in db.extensions]
    assert "postgis" in ext_names
    assert "pgcrypto" in ext_names


@pytest.mark.unit
async def test_inspect_wraps_unexpected_exception() -> None:
    """Unexpected exceptions from the pool should be wrapped in InspectionError."""
    pool = MagicMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("connection refused"))
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)

    inspector = PgCatalogInspector(pool)
    with pytest.raises(InspectionError, match="Catalog inspection failed"):
        await inspector.inspect()


@pytest.mark.unit
async def test_inspect_reraises_inspection_error() -> None:
    """An InspectionError from inside _run_inspect should propagate as-is."""
    pool = MagicMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(side_effect=InspectionError("catalog error"))
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)

    inspector = PgCatalogInspector(pool)
    with pytest.raises(InspectionError, match="catalog error"):
        await inspector.inspect()


@pytest.mark.unit
async def test_inspect_columns_ordered_by_position() -> None:
    """Columns should be ordered by position regardless of query row order."""
    pool = _build_mock_pool(
        schemas_rows=[_SchemaRow("public")],
        tables_rows=[_make_table_row("public", "users")],
        columns_rows=[
            # Intentionally out of order
            _make_column_row("public", "users", "email", position=2, data_type="text"),
            _make_column_row("public", "users", "id", position=1, data_type="integer"),
        ],
    )
    inspector = PgCatalogInspector(pool)
    db = await inspector.inspect()

    cols = db.schemas[0].tables[0].columns
    assert cols[0].name == "id"
    assert cols[1].name == "email"


@pytest.mark.unit
async def test_inspect_database_is_frozen() -> None:
    """The returned Database should be a frozen Pydantic model."""
    pool = _build_mock_pool()
    inspector = PgCatalogInspector(pool)
    db = await inspector.inspect()

    with pytest.raises((TypeError, AttributeError, ValidationError)):
        db.name = "should_not_work"  # type: ignore[misc]
