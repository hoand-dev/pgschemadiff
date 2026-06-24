"""Unit tests for ``pgschemadiff.domain.delta.column`` (task P2-DOM-01c).

Covers:
- Construction of each concrete column-level delta subclass
- ``op`` Literal is fixed/auto-defaulted and rejects wrong ops
- ``kind`` Literal is fixed/auto-defaulted and is the union discriminator
- Frozen behaviour (``frozen=True``) and ``extra="forbid"``
- All model validators (happy + raising paths):
  - target.kind must be ObjectKind.COLUMN
  - AddColumn/DropColumn: target.qname.name must equal column.name
  - RenameColumn: target.qname.name == old_name, old_name != new_name
- ``sort_key`` shape for a sub-object: ``(parent_ns, parent_name, local_name, op_value)``
- Discriminated-union round-trip via ``TypeAdapter[ColumnDelta]``
  (``model_validate`` / ``model_dump`` selects the right subclass by ``kind``)
- Wrong-kind rejection via the TypeAdapter
- Package-level re-export (``from pgschemadiff.domain.delta import …``)
- ``SetColumnDefault`` semantics: None means DROP DEFAULT, not "unchanged"
- ``SetColumnNullability``: nullable=True means DROP NOT NULL, nullable=False means SET NOT NULL
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta import (
    AddColumn,
    AlterColumnType,
    ColumnDelta,
    DropColumn,
    RenameColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.domain.delta.base import DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _table_ref(namespace: str = "public", name: str = "users") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace=namespace, name=name))


def _col_ref(
    namespace: str = "public",
    table: str = "users",
    column: str = "email",
) -> ObjectRef:
    """Build an ObjectRef for a column (sub-object of a TABLE)."""
    parent = _table_ref(namespace, table)
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=namespace, name=column),
        parent=parent,
    )


def _minimal_column(name: str = "email", data_type: str = "text") -> Column:
    return Column(name=name, position=2, data_type=data_type)


@pytest.fixture
def email_ref() -> ObjectRef:
    return _col_ref("public", "users", "email")


@pytest.fixture
def email_col() -> Column:
    return _minimal_column("email", "text")


# ---------------------------------------------------------------------------
# TypeAdapter for the discriminated union
# ---------------------------------------------------------------------------

_COL_DELTA_TA: TypeAdapter[ColumnDelta] = TypeAdapter(ColumnDelta)


# ===========================================================================
# AddColumn
# ===========================================================================


@pytest.mark.unit
def test_add_column_constructs(email_ref: ObjectRef, email_col: Column) -> None:
    delta = AddColumn(target=email_ref, column=email_col)
    assert delta.op is DeltaOp.CREATE
    assert delta.kind == "add_column"
    assert delta.column is email_col
    assert delta.target is email_ref


@pytest.mark.unit
def test_add_column_op_defaults_to_create(email_ref: ObjectRef, email_col: Column) -> None:
    delta = AddColumn(target=email_ref, column=email_col)
    assert delta.op is DeltaOp.CREATE


@pytest.mark.unit
def test_add_column_kind_defaults(email_ref: ObjectRef, email_col: Column) -> None:
    delta = AddColumn(target=email_ref, column=email_col)
    assert delta.kind == "add_column"


@pytest.mark.unit
def test_add_column_rejects_wrong_op(email_ref: ObjectRef, email_col: Column) -> None:
    with pytest.raises(ValidationError):
        AddColumn(target=email_ref, column=email_col, op=DeltaOp.DROP)  # type: ignore[arg-type]


@pytest.mark.unit
def test_add_column_is_frozen(email_ref: ObjectRef, email_col: Column) -> None:
    delta = AddColumn(target=email_ref, column=email_col)
    other_col = _minimal_column("phone", "text")
    with pytest.raises(ValidationError):
        delta.column = other_col  # type: ignore[misc]


@pytest.mark.unit
def test_add_column_rejects_extra_fields(email_ref: ObjectRef, email_col: Column) -> None:
    with pytest.raises(ValidationError):
        AddColumn(target=email_ref, column=email_col, extra="nope")  # type: ignore[call-arg]


@pytest.mark.unit
def test_add_column_sort_key(email_ref: ObjectRef, email_col: Column) -> None:
    """Sub-object sort_key: (parent_ns, parent_name, col_name, op_value)."""
    delta = AddColumn(target=email_ref, column=email_col)
    assert delta.sort_key == ("public", "users", "email", "create")


@pytest.mark.unit
def test_add_column_sort_key_cross_schema() -> None:
    """Columns in a different schema produce a distinct sort_key prefix."""
    ref = _col_ref("billing", "invoices", "amount")
    col = _minimal_column("amount", "numeric")
    delta = AddColumn(target=ref, column=col)
    assert delta.sort_key == ("billing", "invoices", "amount", "create")


@pytest.mark.unit
def test_add_column_json_round_trip(email_ref: ObjectRef, email_col: Column) -> None:
    delta = AddColumn(target=email_ref, column=email_col)
    payload = delta.model_dump_json()
    restored = AddColumn.model_validate_json(payload)
    assert restored == delta


# ---------------------------------------------------------------------------
# AddColumn validators — happy + raising
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_add_column_rejects_non_column_target(email_col: Column) -> None:
    """target.kind must be COLUMN; passing a TABLE ref raises ValidationError."""
    table_ref = _table_ref("public", "users")
    with pytest.raises(ValidationError, match=r"ObjectKind\.COLUMN"):
        AddColumn(target=table_ref, column=email_col)


@pytest.mark.unit
def test_add_column_rejects_name_mismatch() -> None:
    """target.qname.name must equal column.name; mismatch raises ValidationError."""
    ref = _col_ref("public", "users", "email")  # column name in ref is 'email'
    col = _minimal_column("phone", "text")  # but column.name is 'phone'
    with pytest.raises(ValidationError, match="must equal"):
        AddColumn(target=ref, column=col)


@pytest.mark.unit
def test_add_column_name_match_succeeds(email_ref: ObjectRef, email_col: Column) -> None:
    """target.qname.name == column.name → construction succeeds."""
    delta = AddColumn(target=email_ref, column=email_col)
    assert delta.target.qname.name == delta.column.name


# ===========================================================================
# DropColumn
# ===========================================================================


@pytest.mark.unit
def test_drop_column_constructs(email_ref: ObjectRef, email_col: Column) -> None:
    delta = DropColumn(target=email_ref, column=email_col)
    assert delta.op is DeltaOp.DROP
    assert delta.kind == "drop_column"
    assert delta.column is email_col


@pytest.mark.unit
def test_drop_column_op_defaults_to_drop(email_ref: ObjectRef, email_col: Column) -> None:
    delta = DropColumn(target=email_ref, column=email_col)
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_drop_column_kind_defaults(email_ref: ObjectRef, email_col: Column) -> None:
    delta = DropColumn(target=email_ref, column=email_col)
    assert delta.kind == "drop_column"


@pytest.mark.unit
def test_drop_column_rejects_wrong_op(email_ref: ObjectRef, email_col: Column) -> None:
    with pytest.raises(ValidationError):
        DropColumn(target=email_ref, column=email_col, op=DeltaOp.CREATE)  # type: ignore[arg-type]


@pytest.mark.unit
def test_drop_column_is_frozen(email_ref: ObjectRef, email_col: Column) -> None:
    delta = DropColumn(target=email_ref, column=email_col)
    with pytest.raises(ValidationError):
        delta.op = DeltaOp.DROP  # type: ignore[misc]


@pytest.mark.unit
def test_drop_column_rejects_extra_fields(email_ref: ObjectRef, email_col: Column) -> None:
    with pytest.raises(ValidationError):
        DropColumn(target=email_ref, column=email_col, nope=True)  # type: ignore[call-arg]


@pytest.mark.unit
def test_drop_column_sort_key() -> None:
    ref = _col_ref("myns", "archive", "deleted_at")
    col = _minimal_column("deleted_at", "timestamp with time zone")
    delta = DropColumn(target=ref, column=col)
    assert delta.sort_key == ("myns", "archive", "deleted_at", "drop")


@pytest.mark.unit
def test_drop_column_json_round_trip(email_ref: ObjectRef, email_col: Column) -> None:
    delta = DropColumn(target=email_ref, column=email_col)
    payload = delta.model_dump_json()
    restored = DropColumn.model_validate_json(payload)
    assert restored == delta


# ---------------------------------------------------------------------------
# DropColumn validators
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_drop_column_rejects_non_column_target(email_col: Column) -> None:
    table_ref = _table_ref("public", "users")
    with pytest.raises(ValidationError, match=r"ObjectKind\.COLUMN"):
        DropColumn(target=table_ref, column=email_col)


@pytest.mark.unit
def test_drop_column_rejects_name_mismatch() -> None:
    ref = _col_ref("public", "users", "email")
    col = _minimal_column("phone", "text")
    with pytest.raises(ValidationError, match="must equal"):
        DropColumn(target=ref, column=col)


@pytest.mark.unit
def test_drop_column_name_match_succeeds(email_ref: ObjectRef, email_col: Column) -> None:
    delta = DropColumn(target=email_ref, column=email_col)
    assert delta.target.qname.name == delta.column.name


# ===========================================================================
# AlterColumnType
# ===========================================================================


@pytest.mark.unit
def test_alter_column_type_constructs(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(target=email_ref, new_data_type="character varying(255)")
    assert delta.op is DeltaOp.ALTER
    assert delta.kind == "alter_column_type"
    assert delta.new_data_type == "character varying(255)"
    assert delta.using_expression is None
    assert delta.new_collation is None


@pytest.mark.unit
def test_alter_column_type_with_using(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(
        target=email_ref,
        new_data_type="integer",
        using_expression="email::integer",
    )
    assert delta.using_expression == "email::integer"


@pytest.mark.unit
def test_alter_column_type_with_collation(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(
        target=email_ref,
        new_data_type="text",
        new_collation="en_US.utf8",
    )
    assert delta.new_collation == "en_US.utf8"


@pytest.mark.unit
def test_alter_column_type_all_optional_fields(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(
        target=email_ref,
        new_data_type="bigint",
        using_expression="CAST(email AS bigint)",
        new_collation="C",
    )
    assert delta.using_expression == "CAST(email AS bigint)"
    assert delta.new_collation == "C"


@pytest.mark.unit
def test_alter_column_type_op_defaults_to_alter(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(target=email_ref, new_data_type="integer")
    assert delta.op is DeltaOp.ALTER


@pytest.mark.unit
def test_alter_column_type_kind_defaults(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(target=email_ref, new_data_type="integer")
    assert delta.kind == "alter_column_type"


@pytest.mark.unit
def test_alter_column_type_rejects_wrong_op(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        AlterColumnType(
            target=email_ref,
            new_data_type="integer",
            op=DeltaOp.DROP,  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_alter_column_type_is_frozen(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(target=email_ref, new_data_type="integer")
    with pytest.raises(ValidationError):
        delta.new_data_type = "text"  # type: ignore[misc]


@pytest.mark.unit
def test_alter_column_type_rejects_extra_fields(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        AlterColumnType(  # type: ignore[call-arg]
            target=email_ref,
            new_data_type="integer",
            surprise="oops",
        )


@pytest.mark.unit
def test_alter_column_type_sort_key(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(target=email_ref, new_data_type="integer")
    assert delta.sort_key == ("public", "users", "email", "alter")


@pytest.mark.unit
def test_alter_column_type_json_round_trip(email_ref: ObjectRef) -> None:
    delta = AlterColumnType(
        target=email_ref,
        new_data_type="bigint",
        using_expression="email::bigint",
        new_collation="C",
    )
    payload = delta.model_dump_json()
    restored = AlterColumnType.model_validate_json(payload)
    assert restored == delta


# ---------------------------------------------------------------------------
# AlterColumnType validators
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_alter_column_type_rejects_non_column_target() -> None:
    table_ref = _table_ref("public", "users")
    with pytest.raises(ValidationError, match=r"ObjectKind\.COLUMN"):
        AlterColumnType(target=table_ref, new_data_type="integer")


@pytest.mark.unit
def test_alter_column_type_rejects_empty_data_type(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        AlterColumnType(target=email_ref, new_data_type="")


# ===========================================================================
# SetColumnDefault
# ===========================================================================


@pytest.mark.unit
def test_set_column_default_with_expression(email_ref: ObjectRef) -> None:
    """new_default='<expr>' → SET DEFAULT semantic."""
    delta = SetColumnDefault(target=email_ref, new_default="now()")
    assert delta.op is DeltaOp.ALTER
    assert delta.kind == "set_column_default"
    assert delta.new_default == "now()"


@pytest.mark.unit
def test_set_column_default_drop_default(email_ref: ObjectRef) -> None:
    """new_default=None → DROP DEFAULT semantic."""
    delta = SetColumnDefault(target=email_ref, new_default=None)
    assert delta.new_default is None


@pytest.mark.unit
def test_set_column_default_op_defaults_to_alter(email_ref: ObjectRef) -> None:
    delta = SetColumnDefault(target=email_ref, new_default="'active'")
    assert delta.op is DeltaOp.ALTER


@pytest.mark.unit
def test_set_column_default_kind_defaults(email_ref: ObjectRef) -> None:
    delta = SetColumnDefault(target=email_ref, new_default="'active'")
    assert delta.kind == "set_column_default"


@pytest.mark.unit
def test_set_column_default_rejects_wrong_op(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        SetColumnDefault(target=email_ref, new_default=None, op=DeltaOp.DROP)  # type: ignore[arg-type]


@pytest.mark.unit
def test_set_column_default_is_frozen(email_ref: ObjectRef) -> None:
    delta = SetColumnDefault(target=email_ref, new_default="now()")
    with pytest.raises(ValidationError):
        delta.new_default = None  # type: ignore[misc]


@pytest.mark.unit
def test_set_column_default_rejects_extra_fields(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        SetColumnDefault(target=email_ref, new_default="now()", extra="oops")  # type: ignore[call-arg]


@pytest.mark.unit
def test_set_column_default_sort_key(email_ref: ObjectRef) -> None:
    delta = SetColumnDefault(target=email_ref, new_default="now()")
    assert delta.sort_key == ("public", "users", "email", "alter")


@pytest.mark.unit
def test_set_column_default_json_round_trip_with_expr(email_ref: ObjectRef) -> None:
    delta = SetColumnDefault(target=email_ref, new_default="'default@example.com'")
    payload = delta.model_dump_json()
    restored = SetColumnDefault.model_validate_json(payload)
    assert restored == delta


@pytest.mark.unit
def test_set_column_default_json_round_trip_none(email_ref: ObjectRef) -> None:
    """new_default=None (DROP DEFAULT) round-trips correctly."""
    delta = SetColumnDefault(target=email_ref, new_default=None)
    payload = delta.model_dump_json()
    restored = SetColumnDefault.model_validate_json(payload)
    assert restored == delta
    assert restored.new_default is None


# ---------------------------------------------------------------------------
# SetColumnDefault validators
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_column_default_rejects_non_column_target() -> None:
    table_ref = _table_ref("public", "users")
    with pytest.raises(ValidationError, match=r"ObjectKind\.COLUMN"):
        SetColumnDefault(target=table_ref, new_default="now()")


# ===========================================================================
# SetColumnNullability
# ===========================================================================


@pytest.mark.unit
def test_set_column_nullability_set_not_null(email_ref: ObjectRef) -> None:
    """nullable=False → SET NOT NULL."""
    delta = SetColumnNullability(target=email_ref, nullable=False)
    assert delta.op is DeltaOp.ALTER
    assert delta.kind == "set_column_nullability"
    assert delta.nullable is False


@pytest.mark.unit
def test_set_column_nullability_drop_not_null(email_ref: ObjectRef) -> None:
    """nullable=True → DROP NOT NULL."""
    delta = SetColumnNullability(target=email_ref, nullable=True)
    assert delta.nullable is True


@pytest.mark.unit
def test_set_column_nullability_op_defaults_to_alter(email_ref: ObjectRef) -> None:
    delta = SetColumnNullability(target=email_ref, nullable=False)
    assert delta.op is DeltaOp.ALTER


@pytest.mark.unit
def test_set_column_nullability_kind_defaults(email_ref: ObjectRef) -> None:
    delta = SetColumnNullability(target=email_ref, nullable=True)
    assert delta.kind == "set_column_nullability"


@pytest.mark.unit
def test_set_column_nullability_rejects_wrong_op(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        SetColumnNullability(target=email_ref, nullable=False, op=DeltaOp.RENAME)  # type: ignore[arg-type]


@pytest.mark.unit
def test_set_column_nullability_is_frozen(email_ref: ObjectRef) -> None:
    delta = SetColumnNullability(target=email_ref, nullable=False)
    with pytest.raises(ValidationError):
        delta.nullable = True  # type: ignore[misc]


@pytest.mark.unit
def test_set_column_nullability_rejects_extra_fields(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        SetColumnNullability(target=email_ref, nullable=True, extra="nope")  # type: ignore[call-arg]


@pytest.mark.unit
def test_set_column_nullability_sort_key(email_ref: ObjectRef) -> None:
    delta = SetColumnNullability(target=email_ref, nullable=False)
    assert delta.sort_key == ("public", "users", "email", "alter")


@pytest.mark.unit
def test_set_column_nullability_json_round_trip(email_ref: ObjectRef) -> None:
    delta = SetColumnNullability(target=email_ref, nullable=False)
    payload = delta.model_dump_json()
    restored = SetColumnNullability.model_validate_json(payload)
    assert restored == delta


# ---------------------------------------------------------------------------
# SetColumnNullability validators
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_column_nullability_rejects_non_column_target() -> None:
    table_ref = _table_ref("public", "users")
    with pytest.raises(ValidationError, match=r"ObjectKind\.COLUMN"):
        SetColumnNullability(target=table_ref, nullable=False)


# ===========================================================================
# RenameColumn
# ===========================================================================


@pytest.mark.unit
def test_rename_column_constructs(email_ref: ObjectRef) -> None:
    delta = RenameColumn(target=email_ref, old_name="email", new_name="email_address")
    assert delta.op is DeltaOp.RENAME
    assert delta.kind == "rename_column"
    assert delta.old_name == "email"
    assert delta.new_name == "email_address"


@pytest.mark.unit
def test_rename_column_op_defaults_to_rename(email_ref: ObjectRef) -> None:
    delta = RenameColumn(target=email_ref, old_name="email", new_name="email_address")
    assert delta.op is DeltaOp.RENAME


@pytest.mark.unit
def test_rename_column_kind_defaults(email_ref: ObjectRef) -> None:
    delta = RenameColumn(target=email_ref, old_name="email", new_name="email_address")
    assert delta.kind == "rename_column"


@pytest.mark.unit
def test_rename_column_rejects_wrong_op(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        RenameColumn(
            target=email_ref,
            old_name="email",
            new_name="email_address",
            op=DeltaOp.ALTER,  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_rename_column_is_frozen(email_ref: ObjectRef) -> None:
    delta = RenameColumn(target=email_ref, old_name="email", new_name="email_address")
    with pytest.raises(ValidationError):
        delta.new_name = "contact_email"  # type: ignore[misc]


@pytest.mark.unit
def test_rename_column_rejects_extra_fields(email_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        RenameColumn(  # type: ignore[call-arg]
            target=email_ref,
            old_name="email",
            new_name="email_address",
            extra="bad",
        )


@pytest.mark.unit
def test_rename_column_sort_key(email_ref: ObjectRef) -> None:
    """sort_key uses the old name (from target), not new_name."""
    delta = RenameColumn(target=email_ref, old_name="email", new_name="email_address")
    # target.qname.name == "email" → old name in sort key
    assert delta.sort_key == ("public", "users", "email", "rename")


@pytest.mark.unit
def test_rename_column_json_round_trip(email_ref: ObjectRef) -> None:
    delta = RenameColumn(target=email_ref, old_name="email", new_name="email_address")
    payload = delta.model_dump_json()
    restored = RenameColumn.model_validate_json(payload)
    assert restored == delta


# ---------------------------------------------------------------------------
# RenameColumn validators — happy + raising
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rename_column_rejects_non_column_target() -> None:
    table_ref = _table_ref("public", "users")
    with pytest.raises(ValidationError, match=r"ObjectKind\.COLUMN"):
        RenameColumn(target=table_ref, old_name="email", new_name="email_address")


@pytest.mark.unit
def test_rename_column_rejects_target_qname_mismatch() -> None:
    """target.qname.name must equal old_name; mismatched pair raises ValidationError."""
    # target.qname.name is 'email' but old_name is 'phone'
    ref = _col_ref("public", "users", "email")
    with pytest.raises(ValidationError, match="must equal"):
        RenameColumn(target=ref, old_name="phone", new_name="phone_number")


@pytest.mark.unit
def test_rename_column_rejects_same_old_and_new_name(email_ref: ObjectRef) -> None:
    """old_name == new_name (no-op rename) must be rejected."""
    with pytest.raises(ValidationError, match="no-op rename"):
        RenameColumn(target=email_ref, old_name="email", new_name="email")


@pytest.mark.unit
def test_rename_column_allows_valid_rename(email_ref: ObjectRef) -> None:
    """A valid rename succeeds and old_name != new_name."""
    delta = RenameColumn(target=email_ref, old_name="email", new_name="email_address")
    assert delta.old_name != delta.new_name


# ===========================================================================
# Discriminated-union (ColumnDelta) round-trip — discriminated on ``kind``
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        {
            "kind": "add_column",
            "op": "create",
            "target": {
                "kind": "column",
                "qname": {"namespace": "public", "name": "email"},
                "parent": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "users"},
                    "parent": None,
                    "arg_signature": None,
                },
                "arg_signature": None,
            },
            "column": {
                "name": "email",
                "position": 2,
                "data_type": "text",
                "nullable": True,
                "default_expr": None,
                "identity": None,
                "generated_expression": None,
                "collation": None,
            },
        },
        {
            "kind": "drop_column",
            "op": "drop",
            "target": {
                "kind": "column",
                "qname": {"namespace": "public", "name": "phone"},
                "parent": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "users"},
                    "parent": None,
                    "arg_signature": None,
                },
                "arg_signature": None,
            },
            "column": {
                "name": "phone",
                "position": 3,
                "data_type": "text",
                "nullable": True,
                "default_expr": None,
                "identity": None,
                "generated_expression": None,
                "collation": None,
            },
        },
        {
            "kind": "alter_column_type",
            "op": "alter",
            "target": {
                "kind": "column",
                "qname": {"namespace": "public", "name": "amount"},
                "parent": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "orders"},
                    "parent": None,
                    "arg_signature": None,
                },
                "arg_signature": None,
            },
            "new_data_type": "bigint",
            "using_expression": None,
            "new_collation": None,
        },
        {
            "kind": "set_column_default",
            "op": "alter",
            "target": {
                "kind": "column",
                "qname": {"namespace": "public", "name": "status"},
                "parent": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "users"},
                    "parent": None,
                    "arg_signature": None,
                },
                "arg_signature": None,
            },
            "new_default": "'active'",
        },
        {
            "kind": "set_column_default",
            "op": "alter",
            "target": {
                "kind": "column",
                "qname": {"namespace": "public", "name": "status"},
                "parent": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "users"},
                    "parent": None,
                    "arg_signature": None,
                },
                "arg_signature": None,
            },
            "new_default": None,  # DROP DEFAULT
        },
        {
            "kind": "set_column_nullability",
            "op": "alter",
            "target": {
                "kind": "column",
                "qname": {"namespace": "public", "name": "email"},
                "parent": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "users"},
                    "parent": None,
                    "arg_signature": None,
                },
                "arg_signature": None,
            },
            "nullable": False,
        },
        {
            "kind": "rename_column",
            "op": "rename",
            "target": {
                "kind": "column",
                "qname": {"namespace": "public", "name": "email"},
                "parent": {
                    "kind": "table",
                    "qname": {"namespace": "public", "name": "users"},
                    "parent": None,
                    "arg_signature": None,
                },
                "arg_signature": None,
            },
            "old_name": "email",
            "new_name": "email_address",
        },
    ],
    ids=[
        "add_column",
        "drop_column",
        "alter_column_type",
        "set_column_default_expr",
        "set_column_default_none",
        "set_column_nullability",
        "rename_column",
    ],
)
def test_column_delta_discriminated_union_round_trip(raw: dict[str, object]) -> None:
    """TypeAdapter[ColumnDelta] routes to the right subclass by ``kind`` discriminator."""
    delta = _COL_DELTA_TA.validate_python(raw)
    assert delta.kind == raw["kind"]
    dumped = _COL_DELTA_TA.dump_python(delta, mode="json")
    restored = _COL_DELTA_TA.validate_python(dumped)
    assert restored == delta


@pytest.mark.unit
def test_column_delta_unknown_kind_rejected() -> None:
    """An unknown ``kind`` value must raise ValidationError."""
    raw = {
        "kind": "create_table",  # valid table delta kind, but not in ColumnDelta union
        "op": "create",
        "target": {
            "kind": "column",
            "qname": {"namespace": "public", "name": "email"},
            "parent": {
                "kind": "table",
                "qname": {"namespace": "public", "name": "users"},
                "parent": None,
                "arg_signature": None,
            },
            "arg_signature": None,
        },
    }
    with pytest.raises(ValidationError):
        _COL_DELTA_TA.validate_python(raw)


@pytest.mark.unit
def test_column_delta_type_adapter_selects_add(email_ref: ObjectRef, email_col: Column) -> None:
    """TypeAdapter returns an AddColumn instance for kind='add_column'."""
    delta = AddColumn(target=email_ref, column=email_col)
    dumped = _COL_DELTA_TA.dump_python(delta, mode="json")
    restored = _COL_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, AddColumn)
    assert restored.op is DeltaOp.CREATE
    assert restored.kind == "add_column"


@pytest.mark.unit
def test_column_delta_type_adapter_selects_drop(email_ref: ObjectRef, email_col: Column) -> None:
    """TypeAdapter returns a DropColumn instance for kind='drop_column'."""
    delta = DropColumn(target=email_ref, column=email_col)
    dumped = _COL_DELTA_TA.dump_python(delta, mode="json")
    restored = _COL_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, DropColumn)
    assert restored.op is DeltaOp.DROP
    assert restored.kind == "drop_column"


@pytest.mark.unit
def test_column_delta_type_adapter_selects_alter_type(email_ref: ObjectRef) -> None:
    """TypeAdapter returns AlterColumnType for kind='alter_column_type'."""
    delta = AlterColumnType(target=email_ref, new_data_type="bigint")
    dumped = _COL_DELTA_TA.dump_python(delta, mode="json")
    restored = _COL_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, AlterColumnType)
    assert restored.kind == "alter_column_type"


@pytest.mark.unit
def test_column_delta_type_adapter_selects_set_default(email_ref: ObjectRef) -> None:
    """TypeAdapter returns SetColumnDefault for kind='set_column_default'."""
    delta = SetColumnDefault(target=email_ref, new_default="now()")
    dumped = _COL_DELTA_TA.dump_python(delta, mode="json")
    restored = _COL_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, SetColumnDefault)
    assert restored.kind == "set_column_default"
    assert restored.new_default == "now()"


@pytest.mark.unit
def test_column_delta_type_adapter_selects_set_default_none(email_ref: ObjectRef) -> None:
    """TypeAdapter preserves new_default=None (DROP DEFAULT) through round-trip."""
    delta = SetColumnDefault(target=email_ref, new_default=None)
    dumped = _COL_DELTA_TA.dump_python(delta, mode="json")
    restored = _COL_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, SetColumnDefault)
    assert restored.new_default is None


@pytest.mark.unit
def test_column_delta_type_adapter_selects_set_nullability(email_ref: ObjectRef) -> None:
    """TypeAdapter returns SetColumnNullability for kind='set_column_nullability'."""
    delta = SetColumnNullability(target=email_ref, nullable=False)
    dumped = _COL_DELTA_TA.dump_python(delta, mode="json")
    restored = _COL_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, SetColumnNullability)
    assert restored.kind == "set_column_nullability"
    assert restored.nullable is False


@pytest.mark.unit
def test_column_delta_type_adapter_selects_rename(email_ref: ObjectRef) -> None:
    """TypeAdapter returns a RenameColumn instance for kind='rename_column'."""
    delta = RenameColumn(target=email_ref, old_name="email", new_name="email_address")
    dumped = _COL_DELTA_TA.dump_python(delta, mode="json")
    restored = _COL_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, RenameColumn)
    assert restored.op is DeltaOp.RENAME
    assert restored.kind == "rename_column"
    assert restored.old_name == "email"
    assert restored.new_name == "email_address"


# ===========================================================================
# Package-level re-export verification
# ===========================================================================


@pytest.mark.unit
def test_package_exports_add_column() -> None:
    """AddColumn is importable from pgschemadiff.domain.delta."""
    assert issubclass(AddColumn, object)


@pytest.mark.unit
def test_package_exports_drop_column() -> None:
    """DropColumn is importable from pgschemadiff.domain.delta."""
    assert issubclass(DropColumn, object)


@pytest.mark.unit
def test_package_exports_alter_column_type() -> None:
    """AlterColumnType is importable from pgschemadiff.domain.delta."""
    assert issubclass(AlterColumnType, object)


@pytest.mark.unit
def test_package_exports_set_column_default() -> None:
    """SetColumnDefault is importable from pgschemadiff.domain.delta."""
    assert issubclass(SetColumnDefault, object)


@pytest.mark.unit
def test_package_exports_set_column_nullability() -> None:
    """SetColumnNullability is importable from pgschemadiff.domain.delta."""
    assert issubclass(SetColumnNullability, object)


@pytest.mark.unit
def test_package_exports_rename_column() -> None:
    """RenameColumn is importable from pgschemadiff.domain.delta."""
    assert issubclass(RenameColumn, object)


@pytest.mark.unit
def test_package_exports_column_delta() -> None:
    """ColumnDelta is importable from pgschemadiff.domain.delta (verified via top-level import)."""
    assert ColumnDelta is not None
