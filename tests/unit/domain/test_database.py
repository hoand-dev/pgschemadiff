"""Unit tests for ``pgschemadiff.domain.database`` (task P1-DOM-07)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.extension import Extension
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


def _ext_ref(name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.EXTENSION, qname=QualifiedName(namespace="public", name=name))


def _make_table(schema: str, name: str) -> Table:
    ref = _table_ref(schema, name)
    col = Column(name="id", position=1, data_type="integer", nullable=False)
    return Table(ref=ref, columns=(col,))


def _make_index(schema: str, name: str, table_name: str) -> Index:
    ref = _index_ref(schema, name)
    tbl_ref = _table_ref(schema, table_name)
    key = IndexKeyColumn(column_name="id")
    return Index(ref=ref, table_ref=tbl_ref, key_columns=(key,))


def _make_schema(
    name: str, tables: tuple[Table, ...] = (), indexes: tuple[Index, ...] = ()
) -> Schema:
    ref = _schema_ref(name)
    return Schema(ref=ref, tables=tables, indexes=indexes)


def _make_extension(name: str, version: str = "1.0") -> Extension:
    ref = _ext_ref(name)
    return Extension(ref=ref, version=version)


# ---------------------------------------------------------------------------
# Database — construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_minimal() -> None:
    db = Database(name="mydb")
    assert db.name == "mydb"
    assert db.schemas == ()
    assert db.extensions == ()
    assert db.server_version is None


@pytest.mark.unit
def test_database_with_server_version() -> None:
    db = Database(name="db", server_version="18.0")
    assert db.server_version == "18.0"


@pytest.mark.unit
def test_database_with_schemas() -> None:
    pub = _make_schema("public")
    priv = _make_schema("private")
    db = Database(name="db", schemas=(pub, priv))
    assert len(db.schemas) == 2


@pytest.mark.unit
def test_database_with_extensions() -> None:
    ext = _make_extension("pgcrypto", "1.3")
    db = Database(name="db", extensions=(ext,))
    assert len(db.extensions) == 1


@pytest.mark.unit
def test_database_name_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        Database(name="")


# ---------------------------------------------------------------------------
# Database — uniqueness validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_duplicate_schema_name_rejected() -> None:
    pub_a = _make_schema("public")
    pub_b = _make_schema("public")
    with pytest.raises(ValidationError, match="Duplicate schema name"):
        Database(name="db", schemas=(pub_a, pub_b))


@pytest.mark.unit
def test_database_duplicate_extension_name_rejected() -> None:
    ext_a = _make_extension("pgcrypto", "1.3")
    ext_b = _make_extension("pgcrypto", "1.4")
    with pytest.raises(ValidationError, match="Duplicate extension name"):
        Database(name="db", extensions=(ext_a, ext_b))


# ---------------------------------------------------------------------------
# Database — schema_by_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_schema_by_name_found() -> None:
    pub = _make_schema("public")
    db = Database(name="db", schemas=(pub,))
    found = db.schema_by_name("public")
    assert found is pub


@pytest.mark.unit
def test_database_schema_by_name_missing() -> None:
    db = Database(name="db")
    assert db.schema_by_name("nonexistent") is None


# ---------------------------------------------------------------------------
# Database — table lookups
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_table_by_qname_found() -> None:
    tbl = _make_table("public", "users")
    pub = _make_schema("public", tables=(tbl,))
    db = Database(name="db", schemas=(pub,))
    qname = QualifiedName(namespace="public", name="users")
    found = db.table_by_qname(qname)
    assert found is tbl


@pytest.mark.unit
def test_database_table_by_qname_missing_schema() -> None:
    db = Database(name="db")
    qname = QualifiedName(namespace="missing", name="users")
    assert db.table_by_qname(qname) is None


@pytest.mark.unit
def test_database_table_by_qname_missing_table() -> None:
    pub = _make_schema("public")
    db = Database(name="db", schemas=(pub,))
    qname = QualifiedName(namespace="public", name="missing")
    assert db.table_by_qname(qname) is None


@pytest.mark.unit
def test_database_table_by_ref_found() -> None:
    tbl = _make_table("public", "orders")
    pub = _make_schema("public", tables=(tbl,))
    db = Database(name="db", schemas=(pub,))
    ref = _table_ref("public", "orders")
    found = db.table_by_ref(ref)
    assert found is tbl


@pytest.mark.unit
def test_database_table_by_ref_missing() -> None:
    db = Database(name="db")
    ref = _table_ref("public", "missing")
    assert db.table_by_ref(ref) is None


# ---------------------------------------------------------------------------
# Database — index lookups
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_index_by_qname_found() -> None:
    idx = _make_index("public", "users_pkey", "users")
    pub = _make_schema("public", indexes=(idx,))
    db = Database(name="db", schemas=(pub,))
    qname = QualifiedName(namespace="public", name="users_pkey")
    found = db.index_by_qname(qname)
    assert found is idx


@pytest.mark.unit
def test_database_index_by_qname_missing_schema() -> None:
    db = Database(name="db")
    qname = QualifiedName(namespace="missing", name="idx")
    assert db.index_by_qname(qname) is None


@pytest.mark.unit
def test_database_index_by_qname_missing_index() -> None:
    pub = _make_schema("public")
    db = Database(name="db", schemas=(pub,))
    qname = QualifiedName(namespace="public", name="nonexistent")
    assert db.index_by_qname(qname) is None


@pytest.mark.unit
def test_database_index_by_ref_found() -> None:
    idx = _make_index("public", "orders_idx", "orders")
    pub = _make_schema("public", indexes=(idx,))
    db = Database(name="db", schemas=(pub,))
    ref = _index_ref("public", "orders_idx")
    found = db.index_by_ref(ref)
    assert found is idx


# ---------------------------------------------------------------------------
# Database — extension lookups
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_extension_by_name_found() -> None:
    ext = _make_extension("pgcrypto", "1.3")
    db = Database(name="db", extensions=(ext,))
    found = db.extension_by_name("pgcrypto")
    assert found is ext


@pytest.mark.unit
def test_database_extension_by_name_missing() -> None:
    db = Database(name="db")
    assert db.extension_by_name("nonexistent") is None


# ---------------------------------------------------------------------------
# Database — aggregate helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_all_tables() -> None:
    tbl_a = _make_table("public", "users")
    tbl_b = _make_table("public", "orders")
    tbl_c = _make_table("private", "secrets")
    pub = _make_schema("public", tables=(tbl_a, tbl_b))
    priv = _make_schema("private", tables=(tbl_c,))
    db = Database(name="db", schemas=(pub, priv))
    all_tables = db.all_tables()
    assert len(all_tables) == 3
    assert tbl_a in all_tables
    assert tbl_c in all_tables


@pytest.mark.unit
def test_database_all_tables_empty() -> None:
    db = Database(name="db")
    assert db.all_tables() == ()


@pytest.mark.unit
def test_database_all_indexes() -> None:
    idx_a = _make_index("public", "users_pkey", "users")
    idx_b = _make_index("public", "orders_idx", "orders")
    pub = _make_schema("public", indexes=(idx_a, idx_b))
    db = Database(name="db", schemas=(pub,))
    all_indexes = db.all_indexes()
    assert len(all_indexes) == 2
    assert idx_a in all_indexes
    assert idx_b in all_indexes


@pytest.mark.unit
def test_database_all_indexes_empty() -> None:
    db = Database(name="db")
    assert db.all_indexes() == ()


# ---------------------------------------------------------------------------
# Database — immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_is_frozen() -> None:
    db = Database(name="db")
    with pytest.raises(ValidationError):
        db.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Database — JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_json_round_trip() -> None:
    tbl = _make_table("public", "users")
    idx = _make_index("public", "users_id_idx", "users")
    pub = _make_schema("public", tables=(tbl,), indexes=(idx,))
    ext = _make_extension("pgcrypto", "1.3")
    db = Database(name="testdb", schemas=(pub,), extensions=(ext,), server_version="18.0")
    restored = Database.model_validate_json(db.model_dump_json())
    assert restored == db


# ---------------------------------------------------------------------------
# Database — equality / hash
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_equality_and_hash() -> None:
    a = Database(name="db")
    b = Database(name="db")
    c = Database(name="other")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
