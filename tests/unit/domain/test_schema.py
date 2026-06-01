"""Unit tests for ``pgschemadiff.domain.schema`` (task P1-DOM-06)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _schema_ref(name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.SCHEMA, qname=QualifiedName(namespace=name, name=name))


def _table_ref(schema: str, name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace=schema, name=name))


def _index_ref(schema: str, name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.INDEX, qname=QualifiedName(namespace=schema, name=name))


def _make_table(schema: str, name: str) -> Table:
    ref = _table_ref(schema, name)
    col = Column(name="id", position=1, data_type="integer", nullable=False)
    return Table(ref=ref, columns=(col,))


def _make_index(schema: str, name: str, table_name: str) -> Index:
    ref = _index_ref(schema, name)
    tbl_ref = _table_ref(schema, table_name)
    key = IndexKeyColumn(column_name="id")
    return Index(ref=ref, table_ref=tbl_ref, key_columns=(key,))


# ---------------------------------------------------------------------------
# Schema — construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_minimal() -> None:
    ref = _schema_ref("public")
    schema = Schema(ref=ref)
    assert schema.name == "public"
    assert schema.tables == ()
    assert schema.indexes == ()
    assert schema.owner is None
    assert schema.comment is None


@pytest.mark.unit
def test_schema_with_owner() -> None:
    ref = _schema_ref("app")
    schema = Schema(ref=ref, owner="app_user")
    assert schema.owner == "app_user"


@pytest.mark.unit
def test_schema_with_tables() -> None:
    ref = _schema_ref("public")
    tables = (_make_table("public", "users"), _make_table("public", "orders"))
    schema = Schema(ref=ref, tables=tables)
    assert len(schema.tables) == 2


@pytest.mark.unit
def test_schema_with_indexes() -> None:
    ref = _schema_ref("public")
    indexes = (_make_index("public", "users_pkey", "users"),)
    schema = Schema(ref=ref, indexes=indexes)
    assert len(schema.indexes) == 1


@pytest.mark.unit
def test_schema_name_property() -> None:
    ref = _schema_ref("reporting")
    schema = Schema(ref=ref)
    assert schema.name == "reporting"


@pytest.mark.unit
def test_schema_qname_property() -> None:
    ref = _schema_ref("public")
    schema = Schema(ref=ref)
    assert schema.qname == QualifiedName(namespace="public", name="public")


# ---------------------------------------------------------------------------
# Schema — validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_rejects_non_schema_ref() -> None:
    bad_ref = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="t"))
    with pytest.raises(ValidationError, match="must have kind SCHEMA"):
        Schema(ref=bad_ref)


@pytest.mark.unit
def test_schema_rejects_table_from_different_namespace() -> None:
    ref = _schema_ref("public")
    wrong_table = _make_table("private", "secret")
    with pytest.raises(ValidationError, match="belongs to namespace"):
        Schema(ref=ref, tables=(wrong_table,))


@pytest.mark.unit
def test_schema_rejects_extra_fields() -> None:
    ref = _schema_ref("public")
    with pytest.raises(ValidationError):
        Schema(ref=ref, bogus=1)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Schema — table_by_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_table_by_name_found() -> None:
    ref = _schema_ref("public")
    table = _make_table("public", "users")
    schema = Schema(ref=ref, tables=(table,))
    found = schema.table_by_name("users")
    assert found is table


@pytest.mark.unit
def test_schema_table_by_name_missing() -> None:
    ref = _schema_ref("public")
    schema = Schema(ref=ref)
    assert schema.table_by_name("nonexistent") is None


# ---------------------------------------------------------------------------
# Schema — immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_is_frozen() -> None:
    ref = _schema_ref("public")
    schema = Schema(ref=ref)
    with pytest.raises(ValidationError):
        schema.owner = "alice"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Schema — JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_json_round_trip() -> None:
    ref = _schema_ref("public")
    tables = (_make_table("public", "users"),)
    indexes = (_make_index("public", "users_id_idx", "users"),)
    schema = Schema(ref=ref, owner="postgres", tables=tables, indexes=indexes, comment="main")
    restored = Schema.model_validate_json(schema.model_dump_json())
    assert restored == schema


# ---------------------------------------------------------------------------
# Schema — equality / hash
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_equality_and_hash() -> None:
    ref_a = _schema_ref("public")
    ref_b = _schema_ref("public")
    a = Schema(ref=ref_a)
    b = Schema(ref=ref_b)
    c = Schema(ref=_schema_ref("private"))
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
