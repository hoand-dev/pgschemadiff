"""Unit tests for ``pgschemadiff.domain.table`` (task P1-DOM-04)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.table import PartitionInfo, PartitionOf, PartitionStrategy, Table

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _table_ref(name: str, namespace: str = "public") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace=namespace, name=name))


def _col(name: str, position: int, data_type: str = "text", nullable: bool = True) -> Column:
    return Column(name=name, position=position, data_type=data_type, nullable=nullable)


@pytest.fixture
def users_table() -> Table:
    ref = _table_ref("users")
    cols = (
        _col("id", 1, "integer", nullable=False),
        _col("email", 2, "text", nullable=False),
        _col("created_at", 3, "timestamptz"),
    )
    pk = PrimaryKeyConstraint(name="users_pkey", columns=("id",))
    return Table(ref=ref, columns=cols, constraints=(pk,))


# ---------------------------------------------------------------------------
# PartitionStrategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_partition_strategy_values() -> None:
    assert PartitionStrategy.RANGE.value == "range"
    assert PartitionStrategy.LIST.value == "list"
    assert PartitionStrategy.HASH.value == "hash"


# ---------------------------------------------------------------------------
# PartitionInfo
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_partition_info_ok() -> None:
    info = PartitionInfo(strategy=PartitionStrategy.RANGE, partition_key="created_at")
    assert info.strategy is PartitionStrategy.RANGE
    assert info.partition_key == "created_at"


@pytest.mark.unit
def test_partition_info_empty_key_rejected() -> None:
    with pytest.raises(ValidationError):
        PartitionInfo(strategy=PartitionStrategy.LIST, partition_key="")


@pytest.mark.unit
def test_partition_info_is_frozen() -> None:
    info = PartitionInfo(strategy=PartitionStrategy.HASH, partition_key="id")
    with pytest.raises(ValidationError):
        info.partition_key = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PartitionOf
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_partition_of_ok() -> None:
    po = PartitionOf(
        parent_namespace="public",
        parent_name="events",
        partition_bound="FOR VALUES FROM ('2024-01-01') TO ('2025-01-01')",
    )
    assert po.parent_namespace == "public"
    assert po.parent_name == "events"
    assert po.partition_bound is not None


@pytest.mark.unit
def test_partition_of_default_partition() -> None:
    po = PartitionOf(parent_namespace="public", parent_name="events")
    assert po.partition_bound is None


@pytest.mark.unit
def test_partition_of_empty_parent_name_rejected() -> None:
    with pytest.raises(ValidationError):
        PartitionOf(parent_namespace="public", parent_name="")


# ---------------------------------------------------------------------------
# Table — construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_minimal_construction() -> None:
    ref = _table_ref("empty")
    table = Table(ref=ref)
    assert table.columns == ()
    assert table.constraints == ()
    assert table.owner is None
    assert table.tablespace is None
    assert table.partition_info is None
    assert table.partition_of is None
    assert table.comment is None


@pytest.mark.unit
def test_table_with_columns_and_pk(users_table: Table) -> None:
    assert len(users_table.columns) == 3
    assert len(users_table.constraints) == 1
    assert users_table.constraints[0].kind == "primary_key"


@pytest.mark.unit
def test_table_qname_shortcut(users_table: Table) -> None:
    assert users_table.qname == QualifiedName(namespace="public", name="users")


@pytest.mark.unit
def test_table_column_by_name_found(users_table: Table) -> None:
    col = users_table.column_by_name("email")
    assert col is not None
    assert col.name == "email"


@pytest.mark.unit
def test_table_column_by_name_missing(users_table: Table) -> None:
    assert users_table.column_by_name("nonexistent") is None


# ---------------------------------------------------------------------------
# Table — ref kind validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_rejects_non_table_ref() -> None:
    ref = ObjectRef(kind=ObjectKind.VIEW, qname=QualifiedName(namespace="public", name="v"))
    with pytest.raises(ValidationError, match="must have kind TABLE"):
        Table(ref=ref)


# ---------------------------------------------------------------------------
# Table — column name uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_duplicate_column_name_rejected() -> None:
    ref = _table_ref("t")
    cols = (_col("x", 1), _col("x", 2))
    with pytest.raises(ValidationError, match="Duplicate column name"):
        Table(ref=ref, columns=cols)


# ---------------------------------------------------------------------------
# Table — constraint column references
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_pk_references_nonexistent_column_rejected() -> None:
    ref = _table_ref("t")
    cols = (_col("id", 1),)
    pk = PrimaryKeyConstraint(name="pk", columns=("missing",))
    with pytest.raises(ValidationError, match="references column"):
        Table(ref=ref, columns=cols, constraints=(pk,))


@pytest.mark.unit
def test_table_unique_references_nonexistent_column_rejected() -> None:
    ref = _table_ref("t")
    cols = (_col("id", 1),)
    u = UniqueConstraint(name="u", columns=("nonexistent",))
    with pytest.raises(ValidationError, match="references column"):
        Table(ref=ref, columns=cols, constraints=(u,))


@pytest.mark.unit
def test_table_fk_references_nonexistent_column_rejected() -> None:
    ref = _table_ref("t")
    cols = (_col("id", 1),)
    fk = ForeignKeyConstraint(
        name="fk",
        columns=("missing_col",),
        ref_namespace="public",
        ref_table="other",
        ref_columns=("id",),
    )
    with pytest.raises(ValidationError, match="references column"):
        Table(ref=ref, columns=cols, constraints=(fk,))


@pytest.mark.unit
def test_table_check_constraint_no_column_check() -> None:
    """Check constraints don't reference specific columns, so no validation needed."""
    ref = _table_ref("t")
    cols = (_col("age", 1, "integer"),)
    chk = CheckConstraint(name="c", expression="(age > 0)")
    table = Table(ref=ref, columns=cols, constraints=(chk,))
    assert len(table.constraints) == 1


# ---------------------------------------------------------------------------
# Table — partition variants
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_with_partition_info() -> None:
    ref = _table_ref("events")
    info = PartitionInfo(strategy=PartitionStrategy.RANGE, partition_key="event_date")
    table = Table(ref=ref, partition_info=info)
    assert table.partition_info is info
    assert table.partition_of is None


@pytest.mark.unit
def test_table_with_partition_of() -> None:
    ref = _table_ref("events_2024")
    po = PartitionOf(
        parent_namespace="public",
        parent_name="events",
        partition_bound="FOR VALUES FROM ('2024-01-01') TO ('2025-01-01')",
    )
    table = Table(ref=ref, partition_of=po)
    assert table.partition_of is po
    assert table.partition_info is None


@pytest.mark.unit
def test_table_cannot_have_both_partition_variants() -> None:
    ref = _table_ref("t")
    info = PartitionInfo(strategy=PartitionStrategy.RANGE, partition_key="dt")
    po = PartitionOf(parent_namespace="public", parent_name="parent")
    with pytest.raises(ValidationError, match="cannot simultaneously"):
        Table(ref=ref, partition_info=info, partition_of=po)


# ---------------------------------------------------------------------------
# Table — immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_is_frozen(users_table: Table) -> None:
    with pytest.raises(ValidationError):
        users_table.owner = "alice"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Table — JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_json_round_trip(users_table: Table) -> None:
    restored = Table.model_validate_json(users_table.model_dump_json())
    assert restored == users_table


@pytest.mark.unit
def test_table_json_round_trip_with_all_constraint_types() -> None:
    ref = _table_ref("demo")
    cols = (
        _col("id", 1, "integer", False),
        _col("name", 2, "text", False),
        _col("age", 3, "integer"),
        _col("dept_id", 4, "integer"),
    )
    pk = PrimaryKeyConstraint(name="demo_pkey", columns=("id",))
    u = UniqueConstraint(name="demo_name_key", columns=("name",))
    chk = CheckConstraint(name="demo_age_chk", expression="(age >= 0)")
    fk = ForeignKeyConstraint(
        name="demo_dept_fk",
        columns=("dept_id",),
        ref_namespace="public",
        ref_table="departments",
        ref_columns=("id",),
    )
    table = Table(ref=ref, columns=cols, constraints=(pk, u, chk, fk))
    restored = Table.model_validate_json(table.model_dump_json())
    assert restored == table


# ---------------------------------------------------------------------------
# Table — equality / hash
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_equality_and_hash() -> None:
    ref_a = _table_ref("t")
    ref_b = _table_ref("t")
    a = Table(ref=ref_a)
    b = Table(ref=ref_b)
    c = Table(ref=_table_ref("other"))
    assert a == b
    assert hash(a) == hash(b)
    assert a != c


# ---------------------------------------------------------------------------
# Table — identity column in column set
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_table_with_identity_column() -> None:
    ref = _table_ref("accounts")
    spec = IdentitySpec(generated=GeneratedTiming.ALWAYS)
    id_col = Column(name="id", position=1, data_type="bigint", nullable=False, identity=spec)
    table = Table(ref=ref, columns=(id_col,))
    assert table.column_by_name("id") is id_col
    assert table.column_by_name("id").is_identity  # type: ignore[union-attr]
