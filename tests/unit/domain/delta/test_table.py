"""Unit tests for ``pgschemadiff.domain.delta.table`` (task P2-DOM-01b).

Covers:
- Construction of each concrete table-level delta subclass
- ``op`` Literal is fixed/auto-defaulted and rejects wrong ops
- Frozen behaviour (``frozen=True``) and ``extra="forbid"``
- ``sort_key`` behaviour for table targets
- Discriminated-union round-trip via ``TypeAdapter[TableDelta]``
  (``model_validate`` / ``model_dump`` selects the right subclass by ``op``)
- Package-level re-export (``from pgschemadiff.domain.delta import …``)
- ``AlterTableAttrs`` optional-field semantics (all None, some set)
- ``RenameTable`` old/new name payload
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import PrimaryKeyConstraint
from pgschemadiff.domain.delta import (
    AlterTableAttrs,
    CreateTable,
    DeltaOp,
    DropTable,
    RenameTable,
    TableDelta,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.table import PartitionInfo, PartitionOf, PartitionStrategy, Table

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _qname(namespace: str = "public", name: str = "users") -> QualifiedName:
    return QualifiedName(namespace=namespace, name=name)


def _table_ref(namespace: str = "public", name: str = "users") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=_qname(namespace, name))


def _minimal_table(namespace: str = "public", name: str = "users") -> Table:
    """Return a minimal valid Table with one column and no constraints."""
    ref = _table_ref(namespace, name)
    col = Column(name="id", position=1, data_type="integer", nullable=False)
    return Table(ref=ref, columns=(col,))


def _full_table() -> Table:
    """Return a Table with columns, a PK constraint, owner and tablespace."""
    ref = _table_ref("public", "orders")
    cols = (
        Column(name="id", position=1, data_type="bigint", nullable=False),
        Column(name="amount", position=2, data_type="numeric", nullable=True),
    )
    pk = PrimaryKeyConstraint(name="orders_pkey", columns=("id",))
    return Table(ref=ref, columns=cols, constraints=(pk,), owner="alice", tablespace="fast_ssd")


@pytest.fixture
def users_ref() -> ObjectRef:
    return _table_ref("public", "users")


@pytest.fixture
def minimal_table() -> Table:
    return _minimal_table()


@pytest.fixture
def full_table() -> Table:
    return _full_table()


# ---------------------------------------------------------------------------
# TypeAdapter for the discriminated union
# ---------------------------------------------------------------------------

_TABLE_DELTA_TA: TypeAdapter[TableDelta] = TypeAdapter(TableDelta)


# ===========================================================================
# CreateTable
# ===========================================================================


@pytest.mark.unit
def test_create_table_constructs(minimal_table: Table, users_ref: ObjectRef) -> None:
    delta = CreateTable(target=users_ref, table=minimal_table)
    assert delta.op is DeltaOp.CREATE
    assert delta.table is minimal_table
    assert delta.target is users_ref


@pytest.mark.unit
def test_create_table_op_defaults_to_create(minimal_table: Table, users_ref: ObjectRef) -> None:
    """op has a default of DeltaOp.CREATE so callers need not pass it."""
    delta = CreateTable(target=users_ref, table=minimal_table)
    assert delta.op is DeltaOp.CREATE


@pytest.mark.unit
def test_create_table_rejects_wrong_op(minimal_table: Table, users_ref: ObjectRef) -> None:
    """Passing op=DROP to CreateTable must raise ValidationError."""
    with pytest.raises(ValidationError):
        CreateTable(target=users_ref, table=minimal_table, op=DeltaOp.DROP)  # type: ignore[arg-type]


@pytest.mark.unit
def test_create_table_is_frozen(minimal_table: Table, users_ref: ObjectRef) -> None:
    delta = CreateTable(target=users_ref, table=minimal_table)
    other_table = _minimal_table("public", "products")
    with pytest.raises(ValidationError):
        delta.table = other_table  # type: ignore[misc]


@pytest.mark.unit
def test_create_table_rejects_extra_fields(minimal_table: Table, users_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        CreateTable(target=users_ref, table=minimal_table, surprise="oops")  # type: ignore[call-arg]


@pytest.mark.unit
def test_create_table_sort_key(minimal_table: Table, users_ref: ObjectRef) -> None:
    delta = CreateTable(target=users_ref, table=minimal_table)
    # top-level table → 3-tuple (namespace, name, op_value)
    assert delta.sort_key == ("public", "users", "create")


@pytest.mark.unit
def test_create_table_json_round_trip(minimal_table: Table, users_ref: ObjectRef) -> None:
    delta = CreateTable(target=users_ref, table=minimal_table)
    payload = delta.model_dump_json()
    restored = CreateTable.model_validate_json(payload)
    assert restored == delta


# ===========================================================================
# DropTable
# ===========================================================================


@pytest.mark.unit
def test_drop_table_constructs(minimal_table: Table, users_ref: ObjectRef) -> None:
    delta = DropTable(target=users_ref, table=minimal_table)
    assert delta.op is DeltaOp.DROP
    assert delta.table is minimal_table


@pytest.mark.unit
def test_drop_table_op_defaults_to_drop(minimal_table: Table, users_ref: ObjectRef) -> None:
    delta = DropTable(target=users_ref, table=minimal_table)
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_drop_table_rejects_wrong_op(minimal_table: Table, users_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        DropTable(target=users_ref, table=minimal_table, op=DeltaOp.CREATE)  # type: ignore[arg-type]


@pytest.mark.unit
def test_drop_table_is_frozen(minimal_table: Table, users_ref: ObjectRef) -> None:
    delta = DropTable(target=users_ref, table=minimal_table)
    with pytest.raises(ValidationError):
        delta.op = DeltaOp.DROP  # type: ignore[misc]


@pytest.mark.unit
def test_drop_table_rejects_extra_fields(minimal_table: Table, users_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        DropTable(target=users_ref, table=minimal_table, nope=True)  # type: ignore[call-arg]


@pytest.mark.unit
def test_drop_table_sort_key(minimal_table: Table) -> None:
    ref = _table_ref("myns", "archive")
    delta = DropTable(target=ref, table=minimal_table)
    assert delta.sort_key == ("myns", "archive", "drop")


@pytest.mark.unit
def test_drop_table_json_round_trip(full_table: Table) -> None:
    ref = _table_ref("public", "orders")
    delta = DropTable(target=ref, table=full_table)
    payload = delta.model_dump_json()
    restored = DropTable.model_validate_json(payload)
    assert restored == delta


# ===========================================================================
# RenameTable
# ===========================================================================


@pytest.mark.unit
def test_rename_table_constructs(users_ref: ObjectRef) -> None:
    old = _qname("public", "users")
    new = _qname("public", "accounts")
    delta = RenameTable(target=users_ref, old_name=old, new_name=new)
    assert delta.op is DeltaOp.RENAME
    assert delta.old_name == old
    assert delta.new_name == new


@pytest.mark.unit
def test_rename_table_op_defaults_to_rename(users_ref: ObjectRef) -> None:
    delta = RenameTable(
        target=users_ref,
        old_name=_qname("public", "users"),
        new_name=_qname("public", "accounts"),
    )
    assert delta.op is DeltaOp.RENAME


@pytest.mark.unit
def test_rename_table_rejects_wrong_op(users_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        RenameTable(
            target=users_ref,
            old_name=_qname("public", "users"),
            new_name=_qname("public", "accounts"),
            op=DeltaOp.ALTER,  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_rename_table_is_frozen(users_ref: ObjectRef) -> None:
    delta = RenameTable(
        target=users_ref,
        old_name=_qname("public", "users"),
        new_name=_qname("public", "accounts"),
    )
    with pytest.raises(ValidationError):
        delta.new_name = _qname("public", "clients")  # type: ignore[misc]


@pytest.mark.unit
def test_rename_table_rejects_extra_fields(users_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        RenameTable(
            target=users_ref,
            old_name=_qname("public", "users"),
            new_name=_qname("public", "accounts"),
            extra_key="oops",  # type: ignore[call-arg]
        )


@pytest.mark.unit
def test_rename_table_sort_key(users_ref: ObjectRef) -> None:
    """sort_key is derived from target (the old name), not new_name."""
    delta = RenameTable(
        target=users_ref,
        old_name=_qname("public", "users"),
        new_name=_qname("public", "accounts"),
    )
    # target is users_ref → ("public", "users", "rename")
    assert delta.sort_key == ("public", "users", "rename")


@pytest.mark.unit
def test_rename_table_sort_key_cross_schema(users_ref: ObjectRef) -> None:
    """Rename across schemas: sort_key uses target namespace."""
    ref = _table_ref("old_schema", "tbl")
    delta = RenameTable(
        target=ref,
        old_name=_qname("old_schema", "tbl"),
        new_name=_qname("new_schema", "tbl"),
    )
    assert delta.sort_key == ("old_schema", "tbl", "rename")


@pytest.mark.unit
def test_rename_table_json_round_trip(users_ref: ObjectRef) -> None:
    delta = RenameTable(
        target=users_ref,
        old_name=_qname("public", "users"),
        new_name=_qname("public", "accounts"),
    )
    payload = delta.model_dump_json()
    restored = RenameTable.model_validate_json(payload)
    assert restored == delta


# ===========================================================================
# AlterTableAttrs
# ===========================================================================


@pytest.mark.unit
def test_alter_table_attrs_all_none(users_ref: ObjectRef) -> None:
    """AlterTableAttrs is valid with all optional fields left as None."""
    delta = AlterTableAttrs(target=users_ref)
    assert delta.op is DeltaOp.ALTER
    assert delta.new_owner is None
    assert delta.new_tablespace is None
    assert delta.new_comment is None
    assert delta.new_partition_info is None
    assert delta.new_partition_of is None


@pytest.mark.unit
def test_alter_table_attrs_owner_only(users_ref: ObjectRef) -> None:
    delta = AlterTableAttrs(target=users_ref, new_owner="bob")
    assert delta.new_owner == "bob"
    assert delta.new_tablespace is None


@pytest.mark.unit
def test_alter_table_attrs_tablespace_only(users_ref: ObjectRef) -> None:
    delta = AlterTableAttrs(target=users_ref, new_tablespace="pg_default")
    assert delta.new_tablespace == "pg_default"
    assert delta.new_owner is None


@pytest.mark.unit
def test_alter_table_attrs_comment_only(users_ref: ObjectRef) -> None:
    delta = AlterTableAttrs(target=users_ref, new_comment="Stores user accounts")
    assert delta.new_comment == "Stores user accounts"


@pytest.mark.unit
def test_alter_table_attrs_owner_and_tablespace(users_ref: ObjectRef) -> None:
    delta = AlterTableAttrs(target=users_ref, new_owner="alice", new_tablespace="fast_ssd")
    assert delta.new_owner == "alice"
    assert delta.new_tablespace == "fast_ssd"


@pytest.mark.unit
def test_alter_table_attrs_partition_info(users_ref: ObjectRef) -> None:
    ref = _table_ref("public", "events")
    pi = PartitionInfo(strategy=PartitionStrategy.RANGE, partition_key="created_at")
    delta = AlterTableAttrs(target=ref, new_partition_info=pi)
    assert delta.new_partition_info == pi
    assert delta.new_partition_of is None


@pytest.mark.unit
def test_alter_table_attrs_partition_of(users_ref: ObjectRef) -> None:
    ref = _table_ref("public", "events_2024")
    po = PartitionOf(
        parent_namespace="public",
        parent_name="events",
        partition_bound="FOR VALUES FROM ('2024-01-01') TO ('2025-01-01')",
    )
    delta = AlterTableAttrs(target=ref, new_partition_of=po)
    assert delta.new_partition_of == po
    assert delta.new_partition_info is None


@pytest.mark.unit
def test_alter_table_attrs_op_defaults_to_alter(users_ref: ObjectRef) -> None:
    delta = AlterTableAttrs(target=users_ref)
    assert delta.op is DeltaOp.ALTER


@pytest.mark.unit
def test_alter_table_attrs_rejects_wrong_op(users_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        AlterTableAttrs(target=users_ref, op=DeltaOp.DROP)  # type: ignore[arg-type]


@pytest.mark.unit
def test_alter_table_attrs_is_frozen(users_ref: ObjectRef) -> None:
    delta = AlterTableAttrs(target=users_ref, new_owner="alice")
    with pytest.raises(ValidationError):
        delta.new_owner = "bob"  # type: ignore[misc]


@pytest.mark.unit
def test_alter_table_attrs_rejects_extra_fields(users_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        AlterTableAttrs(target=users_ref, unknown="x")  # type: ignore[call-arg]


@pytest.mark.unit
def test_alter_table_attrs_sort_key(users_ref: ObjectRef) -> None:
    delta = AlterTableAttrs(target=users_ref, new_owner="carol")
    assert delta.sort_key == ("public", "users", "alter")


@pytest.mark.unit
def test_alter_table_attrs_json_round_trip(users_ref: ObjectRef) -> None:
    pi = PartitionInfo(strategy=PartitionStrategy.HASH, partition_key="id")
    delta = AlterTableAttrs(
        target=users_ref,
        new_owner="dave",
        new_tablespace="big_ssd",
        new_comment="main users",
        new_partition_info=pi,
    )
    payload = delta.model_dump_json()
    restored = AlterTableAttrs.model_validate_json(payload)
    assert restored == delta


# ===========================================================================
# Discriminated-union (TableDelta) round-trip
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        {
            "op": "create",
            "target": {
                "kind": "table",
                "qname": {"namespace": "public", "name": "users"},
                "parent": None,
                "arg_signature": None,
            },
            "table": {
                "ref": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "users"},
                    "parent": None,
                    "arg_signature": None,
                },
                "columns": [
                    {
                        "name": "id",
                        "position": 1,
                        "data_type": "integer",
                        "nullable": False,
                        "default_expr": None,
                        "identity": None,
                        "generated_expression": None,
                        "collation": None,
                    }
                ],
                "constraints": [],
                "owner": None,
                "tablespace": None,
                "partition_info": None,
                "partition_of": None,
                "comment": None,
            },
        },
        {
            "op": "drop",
            "target": {
                "kind": "table",
                "qname": {"namespace": "public", "name": "orders"},
                "parent": None,
                "arg_signature": None,
            },
            "table": {
                "ref": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "orders"},
                    "parent": None,
                    "arg_signature": None,
                },
                "columns": [
                    {
                        "name": "id",
                        "position": 1,
                        "data_type": "bigint",
                        "nullable": False,
                        "default_expr": None,
                        "identity": None,
                        "generated_expression": None,
                        "collation": None,
                    }
                ],
                "constraints": [],
                "owner": None,
                "tablespace": None,
                "partition_info": None,
                "partition_of": None,
                "comment": None,
            },
        },
        {
            "op": "rename",
            "target": {
                "kind": "table",
                "qname": {"namespace": "public", "name": "users"},
                "parent": None,
                "arg_signature": None,
            },
            "old_name": {"namespace": "public", "name": "users"},
            "new_name": {"namespace": "public", "name": "accounts"},
        },
        {
            "op": "alter",
            "target": {
                "kind": "table",
                "qname": {"namespace": "public", "name": "logs"},
                "parent": None,
                "arg_signature": None,
            },
            "new_owner": "admin",
            "new_tablespace": None,
            "new_comment": None,
            "new_partition_info": None,
            "new_partition_of": None,
        },
    ],
    ids=["create", "drop", "rename", "alter"],
)
def test_table_delta_discriminated_union_round_trip(raw: dict[str, object]) -> None:
    """TypeAdapter[TableDelta] routes to the right subclass by ``op`` discriminator."""
    delta = _TABLE_DELTA_TA.validate_python(raw)
    assert delta.op.value == raw["op"]
    dumped = _TABLE_DELTA_TA.dump_python(delta, mode="json")
    restored = _TABLE_DELTA_TA.validate_python(dumped)
    assert restored == delta


@pytest.mark.unit
def test_table_delta_unknown_op_rejected() -> None:
    """An unknown ``op`` value must raise ValidationError."""
    raw = {
        "op": "replace",  # valid DeltaOp value, but not in TableDelta union
        "target": {
            "kind": "table",
            "qname": {"namespace": "public", "name": "t"},
            "parent": None,
            "arg_signature": None,
        },
    }
    with pytest.raises(ValidationError):
        _TABLE_DELTA_TA.validate_python(raw)


@pytest.mark.unit
def test_table_delta_type_adapter_selects_create(
    minimal_table: Table, users_ref: ObjectRef
) -> None:
    """TypeAdapter returns a CreateTable instance for op='create'."""
    delta = CreateTable(target=users_ref, table=minimal_table)
    dumped = _TABLE_DELTA_TA.dump_python(delta, mode="json")
    restored = _TABLE_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, CreateTable)
    assert restored.op is DeltaOp.CREATE


@pytest.mark.unit
def test_table_delta_type_adapter_selects_drop(minimal_table: Table, users_ref: ObjectRef) -> None:
    """TypeAdapter returns a DropTable instance for op='drop'."""
    delta = DropTable(target=users_ref, table=minimal_table)
    dumped = _TABLE_DELTA_TA.dump_python(delta, mode="json")
    restored = _TABLE_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, DropTable)
    assert restored.op is DeltaOp.DROP


@pytest.mark.unit
def test_table_delta_type_adapter_selects_rename(users_ref: ObjectRef) -> None:
    """TypeAdapter returns a RenameTable instance for op='rename'."""
    delta = RenameTable(
        target=users_ref,
        old_name=_qname("public", "users"),
        new_name=_qname("public", "accounts"),
    )
    dumped = _TABLE_DELTA_TA.dump_python(delta, mode="json")
    restored = _TABLE_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, RenameTable)
    assert restored.op is DeltaOp.RENAME


@pytest.mark.unit
def test_table_delta_type_adapter_selects_alter(users_ref: ObjectRef) -> None:
    """TypeAdapter returns an AlterTableAttrs instance for op='alter'."""
    delta = AlterTableAttrs(target=users_ref, new_owner="eve")
    dumped = _TABLE_DELTA_TA.dump_python(delta, mode="json")
    restored = _TABLE_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, AlterTableAttrs)
    assert restored.op is DeltaOp.ALTER
    assert restored.new_owner == "eve"


# ===========================================================================
# Package-level re-export verification
# ===========================================================================


@pytest.mark.unit
def test_package_exports_create_table() -> None:
    """CreateTable is importable from pgschemadiff.domain.delta."""
    assert issubclass(CreateTable, object)


@pytest.mark.unit
def test_package_exports_drop_table() -> None:
    """DropTable is importable from pgschemadiff.domain.delta."""
    assert issubclass(DropTable, object)


@pytest.mark.unit
def test_package_exports_rename_table() -> None:
    """RenameTable is importable from pgschemadiff.domain.delta."""
    assert issubclass(RenameTable, object)


@pytest.mark.unit
def test_package_exports_alter_table_attrs() -> None:
    """AlterTableAttrs is importable from pgschemadiff.domain.delta."""
    assert issubclass(AlterTableAttrs, object)


@pytest.mark.unit
def test_package_exports_table_delta() -> None:
    """TableDelta is importable from pgschemadiff.domain.delta (verified via top-level import)."""
    # TableDelta was imported from pgschemadiff.domain.delta at the top of this file.
    assert TableDelta is not None
