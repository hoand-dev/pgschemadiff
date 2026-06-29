"""Unit tests for ``pgschemadiff.domain.delta.constraint`` (task P2-DOM-01e).

Covers:
- Construction of each concrete constraint-level delta subclass
- ``op`` Literal is fixed/auto-defaulted and rejects wrong ops
- ``kind`` Literal is fixed/auto-defaulted and is the union discriminator
- Frozen behaviour (``frozen=True``) and ``extra="forbid"``
- All model validators (happy + raising paths):
  - target.kind must be ObjectKind.CONSTRAINT
  - AddConstraint / DropConstraint: target.qname.name must equal constraint.name
- ``sort_key`` shape for a sub-object: ``(parent_ns, parent_name, local_name, op_value)``
  (4-tuple because CONSTRAINT is in SUB_OBJECT_KINDS)
- Discriminated-union round-trip via ``TypeAdapter[ConstraintDelta]``
  (``model_validate`` / ``model_dump`` selects the right subclass by ``kind``)
- Wrong-kind rejection via the TypeAdapter
- Package-level re-export (``from pgschemadiff.domain.delta import …``)
- All five constraint kinds in the payload: PK, Unique, Check, FK, Exclusion
- CONSTRAINT is a sub-object: target.parent must be set to a TABLE ref
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ExclusionConstraint,
    ExclusionElement,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.delta import AddConstraint, ConstraintDelta, DropConstraint
from pgschemadiff.domain.delta.base import DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _table_ref(namespace: str = "public", name: str = "users") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace=namespace, name=name))


def _constraint_ref(
    namespace: str = "public",
    table: str = "users",
    constraint: str = "users_pkey",
) -> ObjectRef:
    """Build an ObjectRef for a constraint (sub-object of a TABLE)."""
    parent = _table_ref(namespace, table)
    return ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=namespace, name=constraint),
        parent=parent,
    )


# --- Constraint payload factories ---


def _pk_constraint(name: str = "users_pkey") -> PrimaryKeyConstraint:
    return PrimaryKeyConstraint(name=name, columns=("id",))


def _unique_constraint(name: str = "users_email_key") -> UniqueConstraint:
    return UniqueConstraint(name=name, columns=("email",))


def _check_constraint(name: str = "users_age_check") -> CheckConstraint:
    return CheckConstraint(name=name, expression="age > 0")


def _fk_constraint(name: str = "orders_user_id_fkey") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        name=name,
        columns=("user_id",),
        ref_namespace="public",
        ref_table="users",
        ref_columns=("id",),
    )


def _exclusion_constraint(name: str = "reservations_period_excl") -> ExclusionConstraint:
    elem = ExclusionElement(column_or_expr="period", operator="&&")
    return ExclusionConstraint(name=name, index_method="gist", elements=(elem,))


# --- Pytest fixtures ---


@pytest.fixture
def pk_ref() -> ObjectRef:
    return _constraint_ref("public", "users", "users_pkey")


@pytest.fixture
def pk_constraint() -> PrimaryKeyConstraint:
    return _pk_constraint("users_pkey")


@pytest.fixture
def unique_ref() -> ObjectRef:
    return _constraint_ref("public", "users", "users_email_key")


@pytest.fixture
def unique_constraint() -> UniqueConstraint:
    return _unique_constraint("users_email_key")


@pytest.fixture
def check_ref() -> ObjectRef:
    return _constraint_ref("public", "users", "users_age_check")


@pytest.fixture
def check_constraint() -> CheckConstraint:
    return _check_constraint("users_age_check")


@pytest.fixture
def fk_ref() -> ObjectRef:
    return _constraint_ref("public", "orders", "orders_user_id_fkey")


@pytest.fixture
def fk_constraint() -> ForeignKeyConstraint:
    return _fk_constraint("orders_user_id_fkey")


@pytest.fixture
def excl_ref() -> ObjectRef:
    return _constraint_ref("public", "reservations", "reservations_period_excl")


@pytest.fixture
def excl_constraint() -> ExclusionConstraint:
    return _exclusion_constraint("reservations_period_excl")


# ---------------------------------------------------------------------------
# TypeAdapter for the discriminated union
# ---------------------------------------------------------------------------

_CONSTR_DELTA_TA: TypeAdapter[ConstraintDelta] = TypeAdapter(ConstraintDelta)


# ===========================================================================
# AddConstraint — PrimaryKey
# ===========================================================================


@pytest.mark.unit
def test_add_constraint_pk_constructs(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.op is DeltaOp.CREATE
    assert delta.kind == "add_constraint"
    assert delta.constraint is pk_constraint
    assert delta.target is pk_ref


@pytest.mark.unit
def test_add_constraint_op_defaults_to_create(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """op has a default of DeltaOp.CREATE so callers need not pass it."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.op is DeltaOp.CREATE


@pytest.mark.unit
def test_add_constraint_kind_defaults(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """kind has a default of 'add_constraint' so callers need not pass it."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.kind == "add_constraint"


@pytest.mark.unit
def test_add_constraint_rejects_wrong_op(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """Passing op=DROP to AddConstraint must raise ValidationError."""
    with pytest.raises(ValidationError):
        AddConstraint(target=pk_ref, constraint=pk_constraint, op=DeltaOp.DROP)  # type: ignore[arg-type]


@pytest.mark.unit
def test_add_constraint_is_frozen(pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint) -> None:
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    other = _unique_constraint("users_email_key")
    with pytest.raises(ValidationError):
        delta.constraint = other  # type: ignore[misc]


@pytest.mark.unit
def test_add_constraint_rejects_extra_fields(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    with pytest.raises(ValidationError):
        AddConstraint(target=pk_ref, constraint=pk_constraint, surprise="oops")  # type: ignore[call-arg]


@pytest.mark.unit
def test_add_constraint_sort_key_pk(pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint) -> None:
    """Sub-object sort_key: (parent_ns, parent_name, local_name, op_value) — 4-tuple."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.sort_key == ("public", "users", "users_pkey", "create")


@pytest.mark.unit
def test_add_constraint_sort_key_cross_schema() -> None:
    """Constraints in a different schema produce a distinct sort_key prefix."""
    ref = _constraint_ref("billing", "invoices", "invoices_pkey")
    c = _pk_constraint("invoices_pkey")
    delta = AddConstraint(target=ref, constraint=c)
    assert delta.sort_key == ("billing", "invoices", "invoices_pkey", "create")


@pytest.mark.unit
def test_add_constraint_json_round_trip(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    payload = delta.model_dump_json()
    restored = AddConstraint.model_validate_json(payload)
    assert restored == delta


# ===========================================================================
# AddConstraint — all five constraint kinds
# ===========================================================================


@pytest.mark.unit
def test_add_constraint_with_unique(
    unique_ref: ObjectRef, unique_constraint: UniqueConstraint
) -> None:
    """AddConstraint works with a UniqueConstraint payload."""
    delta = AddConstraint(target=unique_ref, constraint=unique_constraint)
    assert delta.constraint.kind == "unique"
    assert delta.sort_key == ("public", "users", "users_email_key", "create")


@pytest.mark.unit
def test_add_constraint_with_check(check_ref: ObjectRef, check_constraint: CheckConstraint) -> None:
    """AddConstraint works with a CheckConstraint payload."""
    delta = AddConstraint(target=check_ref, constraint=check_constraint)
    assert delta.constraint.kind == "check"
    assert delta.sort_key == ("public", "users", "users_age_check", "create")


@pytest.mark.unit
def test_add_constraint_with_fk(fk_ref: ObjectRef, fk_constraint: ForeignKeyConstraint) -> None:
    """AddConstraint works with a ForeignKeyConstraint payload."""
    delta = AddConstraint(target=fk_ref, constraint=fk_constraint)
    assert delta.constraint.kind == "foreign_key"
    assert delta.sort_key == ("public", "orders", "orders_user_id_fkey", "create")


@pytest.mark.unit
def test_add_constraint_with_exclusion(
    excl_ref: ObjectRef, excl_constraint: ExclusionConstraint
) -> None:
    """AddConstraint works with an ExclusionConstraint payload."""
    delta = AddConstraint(target=excl_ref, constraint=excl_constraint)
    assert delta.constraint.kind == "exclusion"
    assert delta.sort_key == ("public", "reservations", "reservations_period_excl", "create")


# ---------------------------------------------------------------------------
# AddConstraint validators — happy + raising
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_add_constraint_rejects_wrong_target_kind(pk_constraint: PrimaryKeyConstraint) -> None:
    """target.kind must be CONSTRAINT; wrong kind raises ValidationError."""
    wrong_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="users_pkey"),
        parent=_table_ref("public", "users"),
    )
    with pytest.raises(ValidationError, match=r"must be ObjectKind\.CONSTRAINT"):
        AddConstraint(target=wrong_ref, constraint=pk_constraint)


@pytest.mark.unit
def test_add_constraint_rejects_name_mismatch(pk_ref: ObjectRef) -> None:
    """target.qname.name must equal constraint.name; mismatch raises ValidationError."""
    mismatched = _pk_constraint("totally_different_pkey")
    with pytest.raises(ValidationError, match=r"must equal"):
        AddConstraint(target=pk_ref, constraint=mismatched)


@pytest.mark.unit
def test_add_constraint_target_name_matches_constraint_name(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """Successful construction: target.qname.name == constraint.name."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.qname.name == delta.constraint.name


@pytest.mark.unit
def test_add_constraint_target_is_sub_object(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """CONSTRAINT is a sub-object kind: target.parent must be set."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.parent is not None
    assert delta.target.parent.kind is ObjectKind.TABLE


@pytest.mark.unit
def test_add_constraint_requires_parent() -> None:
    """Creating an ObjectRef of CONSTRAINT kind without a parent must fail at the ref level."""
    with pytest.raises(ValidationError):
        ObjectRef(
            kind=ObjectKind.CONSTRAINT,
            qname=QualifiedName(namespace="public", name="users_pkey"),
        )


# ===========================================================================
# DropConstraint — PrimaryKey
# ===========================================================================


@pytest.mark.unit
def test_drop_constraint_pk_constructs(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.op is DeltaOp.DROP
    assert delta.kind == "drop_constraint"
    assert delta.constraint is pk_constraint


@pytest.mark.unit
def test_drop_constraint_op_defaults_to_drop(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_drop_constraint_kind_defaults(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.kind == "drop_constraint"


@pytest.mark.unit
def test_drop_constraint_rejects_wrong_op(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    with pytest.raises(ValidationError):
        DropConstraint(target=pk_ref, constraint=pk_constraint, op=DeltaOp.CREATE)  # type: ignore[arg-type]


@pytest.mark.unit
def test_drop_constraint_is_frozen(pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint) -> None:
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    with pytest.raises(ValidationError):
        delta.op = DeltaOp.DROP  # type: ignore[misc]


@pytest.mark.unit
def test_drop_constraint_rejects_extra_fields(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    with pytest.raises(ValidationError):
        DropConstraint(target=pk_ref, constraint=pk_constraint, nope=True)  # type: ignore[call-arg]


@pytest.mark.unit
def test_drop_constraint_sort_key_pk(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """Sub-object sort_key: (parent_ns, parent_name, local_name, op_value) — 4-tuple."""
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.sort_key == ("public", "users", "users_pkey", "drop")


@pytest.mark.unit
def test_drop_constraint_sort_key_cross_schema() -> None:
    """Cross-schema drop produces a distinct sort_key prefix."""
    ref = _constraint_ref("billing", "invoices", "invoices_pkey")
    c = _pk_constraint("invoices_pkey")
    delta = DropConstraint(target=ref, constraint=c)
    assert delta.sort_key == ("billing", "invoices", "invoices_pkey", "drop")


@pytest.mark.unit
def test_drop_constraint_json_round_trip(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    payload = delta.model_dump_json()
    restored = DropConstraint.model_validate_json(payload)
    assert restored == delta


# ===========================================================================
# DropConstraint — all five constraint kinds
# ===========================================================================


@pytest.mark.unit
def test_drop_constraint_with_unique(
    unique_ref: ObjectRef, unique_constraint: UniqueConstraint
) -> None:
    """DropConstraint works with a UniqueConstraint payload."""
    delta = DropConstraint(target=unique_ref, constraint=unique_constraint)
    assert delta.constraint.kind == "unique"
    assert delta.sort_key == ("public", "users", "users_email_key", "drop")


@pytest.mark.unit
def test_drop_constraint_with_check(
    check_ref: ObjectRef, check_constraint: CheckConstraint
) -> None:
    """DropConstraint works with a CheckConstraint payload."""
    delta = DropConstraint(target=check_ref, constraint=check_constraint)
    assert delta.constraint.kind == "check"
    assert delta.sort_key == ("public", "users", "users_age_check", "drop")


@pytest.mark.unit
def test_drop_constraint_with_fk(fk_ref: ObjectRef, fk_constraint: ForeignKeyConstraint) -> None:
    """DropConstraint works with a ForeignKeyConstraint payload."""
    delta = DropConstraint(target=fk_ref, constraint=fk_constraint)
    assert delta.constraint.kind == "foreign_key"
    assert delta.sort_key == ("public", "orders", "orders_user_id_fkey", "drop")


@pytest.mark.unit
def test_drop_constraint_with_exclusion(
    excl_ref: ObjectRef, excl_constraint: ExclusionConstraint
) -> None:
    """DropConstraint works with an ExclusionConstraint payload."""
    delta = DropConstraint(target=excl_ref, constraint=excl_constraint)
    assert delta.constraint.kind == "exclusion"
    assert delta.sort_key == ("public", "reservations", "reservations_period_excl", "drop")


# ---------------------------------------------------------------------------
# DropConstraint validators — happy + raising
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_drop_constraint_rejects_wrong_target_kind(pk_constraint: PrimaryKeyConstraint) -> None:
    """target.kind must be CONSTRAINT; wrong kind raises ValidationError."""
    wrong_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="users_pkey"),
        parent=_table_ref("public", "users"),
    )
    with pytest.raises(ValidationError, match=r"must be ObjectKind\.CONSTRAINT"):
        DropConstraint(target=wrong_ref, constraint=pk_constraint)


@pytest.mark.unit
def test_drop_constraint_rejects_name_mismatch(pk_ref: ObjectRef) -> None:
    """target.qname.name must equal constraint.name; mismatch raises ValidationError."""
    mismatched = _pk_constraint("totally_different_pkey")
    with pytest.raises(ValidationError, match=r"must equal"):
        DropConstraint(target=pk_ref, constraint=mismatched)


@pytest.mark.unit
def test_drop_constraint_target_name_matches_constraint_name(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """Successful construction: target.qname.name == constraint.name."""
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.qname.name == delta.constraint.name


@pytest.mark.unit
def test_drop_constraint_target_is_sub_object(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """CONSTRAINT is a sub-object kind: target.parent must be set."""
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.parent is not None
    assert delta.target.parent.kind is ObjectKind.TABLE


# ===========================================================================
# sort_key shape verification — 4-tuple for sub-objects
# ===========================================================================


@pytest.mark.unit
def test_add_constraint_sort_key_is_4_tuple(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """CONSTRAINT is a sub-object: sort_key must be a 4-tuple (parent-folded)."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert len(delta.sort_key) == 4


@pytest.mark.unit
def test_drop_constraint_sort_key_is_4_tuple(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """CONSTRAINT is a sub-object: sort_key must be a 4-tuple (parent-folded)."""
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert len(delta.sort_key) == 4


@pytest.mark.unit
def test_sort_key_parent_folding_prevents_collision() -> None:
    """Two constraints with the same name on different tables produce distinct sort keys."""
    ref_users = _constraint_ref("public", "users", "chk_active")
    ref_orders = _constraint_ref("public", "orders", "chk_active")
    c = CheckConstraint(name="chk_active", expression="is_active = true")
    delta_users = AddConstraint(target=ref_users, constraint=c)
    delta_orders = AddConstraint(target=ref_orders, constraint=c)
    assert delta_users.sort_key != delta_orders.sort_key
    assert delta_users.sort_key == ("public", "users", "chk_active", "create")
    assert delta_orders.sort_key == ("public", "orders", "chk_active", "create")


# ===========================================================================
# Discriminated-union (ConstraintDelta) round-trip — discriminated on ``kind``
# ===========================================================================


def _table_ref_dict(namespace: str = "public", name: str = "users") -> dict[str, object]:
    return {
        "kind": "table",
        "qname": {"namespace": namespace, "name": name},
        "parent": None,
        "arg_signature": None,
    }


def _constraint_ref_dict(
    namespace: str = "public",
    table: str = "users",
    constraint: str = "users_pkey",
) -> dict[str, object]:
    return {
        "kind": "constraint",
        "qname": {"namespace": namespace, "name": constraint},
        "parent": _table_ref_dict(namespace, table),
        "arg_signature": None,
    }


def _pk_dict(name: str = "users_pkey") -> dict[str, object]:
    return {
        "kind": "primary_key",
        "name": name,
        "deferrability": "not_deferrable",
        "columns": ["id"],
        "index_method": "btree",
    }


def _unique_dict(name: str = "users_email_key") -> dict[str, object]:
    return {
        "kind": "unique",
        "name": name,
        "deferrability": "not_deferrable",
        "columns": ["email"],
        "nulls_not_distinct": False,
        "index_method": "btree",
    }


def _check_dict(name: str = "users_age_check") -> dict[str, object]:
    return {
        "kind": "check",
        "name": name,
        "deferrability": "not_deferrable",
        "expression": "age > 0",
        "no_inherit": False,
    }


def _fk_dict(name: str = "orders_user_id_fkey") -> dict[str, object]:
    return {
        "kind": "foreign_key",
        "name": name,
        "deferrability": "not_deferrable",
        "columns": ["user_id"],
        "ref_namespace": "public",
        "ref_table": "users",
        "ref_columns": ["id"],
        "on_delete": "no_action",
        "on_update": "no_action",
        "match_type": "simple",
    }


def _exclusion_dict(name: str = "reservations_period_excl") -> dict[str, object]:
    return {
        "kind": "exclusion",
        "name": name,
        "deferrability": "not_deferrable",
        "index_method": "gist",
        "elements": [{"column_or_expr": "period", "operator": "&&", "opclass": None}],
        "predicate": None,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        {
            "kind": "add_constraint",
            "op": "create",
            "target": _constraint_ref_dict("public", "users", "users_pkey"),
            "constraint": _pk_dict("users_pkey"),
        },
        {
            "kind": "drop_constraint",
            "op": "drop",
            "target": _constraint_ref_dict("public", "users", "users_pkey"),
            "constraint": _pk_dict("users_pkey"),
        },
        {
            "kind": "add_constraint",
            "op": "create",
            "target": _constraint_ref_dict("public", "users", "users_email_key"),
            "constraint": _unique_dict("users_email_key"),
        },
        {
            "kind": "add_constraint",
            "op": "create",
            "target": _constraint_ref_dict("public", "users", "users_age_check"),
            "constraint": _check_dict("users_age_check"),
        },
        {
            "kind": "add_constraint",
            "op": "create",
            "target": _constraint_ref_dict("public", "orders", "orders_user_id_fkey"),
            "constraint": _fk_dict("orders_user_id_fkey"),
        },
        {
            "kind": "add_constraint",
            "op": "create",
            "target": _constraint_ref_dict("public", "reservations", "reservations_period_excl"),
            "constraint": _exclusion_dict("reservations_period_excl"),
        },
    ],
    ids=[
        "add_constraint_pk",
        "drop_constraint_pk",
        "add_constraint_unique",
        "add_constraint_check",
        "add_constraint_fk",
        "add_constraint_exclusion",
    ],
)
def test_constraint_delta_discriminated_union_round_trip(raw: dict[str, object]) -> None:
    """TypeAdapter[ConstraintDelta] routes to the right subclass by ``kind`` discriminator."""
    delta = _CONSTR_DELTA_TA.validate_python(raw)
    assert delta.kind == raw["kind"]
    dumped = _CONSTR_DELTA_TA.dump_python(delta, mode="json")
    restored = _CONSTR_DELTA_TA.validate_python(dumped)
    assert restored == delta


@pytest.mark.unit
def test_constraint_delta_round_trip_preserves_nested_constraint_kind() -> None:
    """model_dump round-trip preserves the nested constraint.kind discriminator."""
    ref = _constraint_ref("public", "users", "users_pkey")
    c = _pk_constraint("users_pkey")
    delta = AddConstraint(target=ref, constraint=c)
    dumped = _CONSTR_DELTA_TA.dump_python(delta, mode="json")
    # The nested constraint kind must survive serialisation
    assert dumped["constraint"]["kind"] == "primary_key"
    restored = _CONSTR_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, AddConstraint)
    assert restored.constraint.kind == "primary_key"


@pytest.mark.unit
def test_constraint_delta_round_trip_fk_preserves_ref_columns() -> None:
    """FK constraint's ref_columns survive a ConstraintDelta round-trip."""
    ref = _constraint_ref("public", "orders", "orders_user_id_fkey")
    fk = _fk_constraint("orders_user_id_fkey")
    delta = AddConstraint(target=ref, constraint=fk)
    dumped = _CONSTR_DELTA_TA.dump_python(delta, mode="json")
    restored = _CONSTR_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, AddConstraint)
    assert isinstance(restored.constraint, ForeignKeyConstraint)
    assert restored.constraint.ref_table == "users"
    assert restored.constraint.ref_columns == ("id",)


@pytest.mark.unit
def test_constraint_delta_round_trip_exclusion_preserves_elements() -> None:
    """Exclusion constraint elements survive a ConstraintDelta round-trip."""
    ref = _constraint_ref("public", "reservations", "reservations_period_excl")
    excl = _exclusion_constraint("reservations_period_excl")
    delta = AddConstraint(target=ref, constraint=excl)
    dumped = _CONSTR_DELTA_TA.dump_python(delta, mode="json")
    restored = _CONSTR_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, AddConstraint)
    assert isinstance(restored.constraint, ExclusionConstraint)
    assert restored.constraint.elements[0].operator == "&&"


@pytest.mark.unit
def test_constraint_delta_unknown_kind_rejected() -> None:
    """An unknown ``kind`` value must raise ValidationError."""
    raw = {
        "kind": "create_index",  # valid index delta kind, not in ConstraintDelta union
        "op": "create",
        "target": _constraint_ref_dict(),
    }
    with pytest.raises(ValidationError):
        _CONSTR_DELTA_TA.validate_python(raw)


@pytest.mark.unit
def test_constraint_delta_type_adapter_selects_add(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """TypeAdapter returns an AddConstraint instance for kind='add_constraint'."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    dumped = _CONSTR_DELTA_TA.dump_python(delta, mode="json")
    restored = _CONSTR_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, AddConstraint)
    assert restored.op is DeltaOp.CREATE
    assert restored.kind == "add_constraint"


@pytest.mark.unit
def test_constraint_delta_type_adapter_selects_drop(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """TypeAdapter returns a DropConstraint instance for kind='drop_constraint'."""
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    dumped = _CONSTR_DELTA_TA.dump_python(delta, mode="json")
    restored = _CONSTR_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, DropConstraint)
    assert restored.op is DeltaOp.DROP
    assert restored.kind == "drop_constraint"


# ===========================================================================
# Sub-object — target has a TABLE parent
# ===========================================================================


@pytest.mark.unit
def test_add_constraint_target_has_parent(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """CONSTRAINT is in SUB_OBJECT_KINDS → target.parent must be set."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.parent is not None


@pytest.mark.unit
def test_drop_constraint_target_has_parent(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.parent is not None


@pytest.mark.unit
def test_add_constraint_parent_kind_is_table(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """target.parent must be a TABLE ref."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.parent is not None
    assert delta.target.parent.kind is ObjectKind.TABLE


@pytest.mark.unit
def test_drop_constraint_parent_kind_is_table(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    delta = DropConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.parent is not None
    assert delta.target.parent.kind is ObjectKind.TABLE


@pytest.mark.unit
def test_constraint_ref_target_kind_is_constraint(
    pk_ref: ObjectRef, pk_constraint: PrimaryKeyConstraint
) -> None:
    """target.kind must be ObjectKind.CONSTRAINT for constraint deltas."""
    delta = AddConstraint(target=pk_ref, constraint=pk_constraint)
    assert delta.target.kind is ObjectKind.CONSTRAINT


# ===========================================================================
# Package-level re-export verification
# ===========================================================================


@pytest.mark.unit
def test_package_exports_add_constraint() -> None:
    """AddConstraint is importable from pgschemadiff.domain.delta."""
    assert issubclass(AddConstraint, object)


@pytest.mark.unit
def test_package_exports_drop_constraint() -> None:
    """DropConstraint is importable from pgschemadiff.domain.delta."""
    assert issubclass(DropConstraint, object)


@pytest.mark.unit
def test_package_exports_constraint_delta() -> None:
    """ConstraintDelta is importable from pgschemadiff.domain.delta."""
    assert ConstraintDelta is not None
