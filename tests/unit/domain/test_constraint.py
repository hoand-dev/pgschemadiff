"""Unit tests for ``pgschemadiff.domain.constraint`` (task P1-DOM-03)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.constraint import (
    CheckConstraint,
    Constraint,
    ConstraintDeferrability,
    ExclusionConstraint,
    ExclusionElement,
    FKAction,
    FKMatch,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fk_action_values() -> None:
    assert FKAction.NO_ACTION.value == "no_action"
    assert FKAction.RESTRICT.value == "restrict"
    assert FKAction.CASCADE.value == "cascade"
    assert FKAction.SET_NULL.value == "set_null"
    assert FKAction.SET_DEFAULT.value == "set_default"


@pytest.mark.unit
def test_fk_match_values() -> None:
    assert FKMatch.SIMPLE.value == "simple"
    assert FKMatch.PARTIAL.value == "partial"
    assert FKMatch.FULL.value == "full"


@pytest.mark.unit
def test_constraint_deferrability_values() -> None:
    assert ConstraintDeferrability.NOT_DEFERRABLE.value == "not_deferrable"
    assert (
        ConstraintDeferrability.DEFERRABLE_INITIALLY_IMMEDIATE.value
        == "deferrable_initially_immediate"
    )
    assert (
        ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED.value
        == "deferrable_initially_deferred"
    )


# ---------------------------------------------------------------------------
# PrimaryKeyConstraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pk_constraint_minimal() -> None:
    pk = PrimaryKeyConstraint(name="users_pkey", columns=("id",))
    assert pk.kind == "primary_key"
    assert pk.columns == ("id",)
    assert pk.index_method == "btree"
    assert pk.deferrability is ConstraintDeferrability.NOT_DEFERRABLE


@pytest.mark.unit
def test_pk_constraint_multi_column() -> None:
    pk = PrimaryKeyConstraint(name="orders_pk", columns=("order_id", "line_no"))
    assert pk.columns == ("order_id", "line_no")


@pytest.mark.unit
def test_pk_constraint_empty_columns_rejected() -> None:
    with pytest.raises(ValidationError):
        PrimaryKeyConstraint(name="pk", columns=())


@pytest.mark.unit
def test_pk_constraint_is_frozen() -> None:
    pk = PrimaryKeyConstraint(name="pk", columns=("id",))
    with pytest.raises(ValidationError):
        pk.name = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_pk_constraint_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PrimaryKeyConstraint(name="pk", columns=("id",), extra=1)  # type: ignore[call-arg]


@pytest.mark.unit
def test_pk_constraint_deferrable() -> None:
    pk = PrimaryKeyConstraint(
        name="pk",
        columns=("id",),
        deferrability=ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED,
    )
    assert pk.deferrability is ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED


@pytest.mark.unit
def test_pk_constraint_json_round_trip() -> None:
    pk = PrimaryKeyConstraint(name="pk", columns=("id", "tenant"))
    restored = PrimaryKeyConstraint.model_validate_json(pk.model_dump_json())
    assert restored == pk


# ---------------------------------------------------------------------------
# UniqueConstraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unique_constraint_minimal() -> None:
    u = UniqueConstraint(name="users_email_key", columns=("email",))
    assert u.kind == "unique"
    assert u.nulls_not_distinct is False
    assert u.index_method == "btree"


@pytest.mark.unit
def test_unique_constraint_nulls_not_distinct() -> None:
    u = UniqueConstraint(name="u", columns=("x",), nulls_not_distinct=True)
    assert u.nulls_not_distinct is True


@pytest.mark.unit
def test_unique_constraint_empty_columns_rejected() -> None:
    with pytest.raises(ValidationError):
        UniqueConstraint(name="u", columns=())


@pytest.mark.unit
def test_unique_constraint_json_round_trip() -> None:
    u = UniqueConstraint(name="u", columns=("a", "b"), nulls_not_distinct=True)
    assert UniqueConstraint.model_validate_json(u.model_dump_json()) == u


# ---------------------------------------------------------------------------
# CheckConstraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_constraint_minimal() -> None:
    chk = CheckConstraint(name="age_positive", expression="(age > 0)")
    assert chk.kind == "check"
    assert chk.expression == "(age > 0)"
    assert chk.no_inherit is False


@pytest.mark.unit
def test_check_constraint_no_inherit() -> None:
    chk = CheckConstraint(name="c", expression="true", no_inherit=True)
    assert chk.no_inherit is True


@pytest.mark.unit
def test_check_constraint_empty_expression_rejected() -> None:
    with pytest.raises(ValidationError):
        CheckConstraint(name="c", expression="")


@pytest.mark.unit
def test_check_constraint_json_round_trip() -> None:
    chk = CheckConstraint(name="c", expression="(x > 0)", no_inherit=True)
    assert CheckConstraint.model_validate_json(chk.model_dump_json()) == chk


# ---------------------------------------------------------------------------
# ForeignKeyConstraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fk_constraint_minimal() -> None:
    fk = ForeignKeyConstraint(
        name="orders_user_fk",
        columns=("user_id",),
        ref_namespace="public",
        ref_table="users",
        ref_columns=("id",),
    )
    assert fk.kind == "foreign_key"
    assert fk.on_delete is FKAction.NO_ACTION
    assert fk.on_update is FKAction.NO_ACTION
    assert fk.match_type is FKMatch.SIMPLE


@pytest.mark.unit
def test_fk_constraint_full_options() -> None:
    fk = ForeignKeyConstraint(
        name="fk",
        columns=("user_id",),
        ref_namespace="public",
        ref_table="users",
        ref_columns=("id",),
        on_delete=FKAction.CASCADE,
        on_update=FKAction.RESTRICT,
        match_type=FKMatch.FULL,
        deferrability=ConstraintDeferrability.DEFERRABLE_INITIALLY_IMMEDIATE,
    )
    assert fk.on_delete is FKAction.CASCADE
    assert fk.on_update is FKAction.RESTRICT
    assert fk.match_type is FKMatch.FULL


@pytest.mark.unit
def test_fk_constraint_empty_columns_rejected() -> None:
    with pytest.raises(ValidationError):
        ForeignKeyConstraint(
            name="fk",
            columns=(),
            ref_namespace="public",
            ref_table="users",
            ref_columns=("id",),
        )


@pytest.mark.unit
def test_fk_constraint_empty_ref_columns_rejected() -> None:
    with pytest.raises(ValidationError):
        ForeignKeyConstraint(
            name="fk",
            columns=("user_id",),
            ref_namespace="public",
            ref_table="users",
            ref_columns=(),
        )


@pytest.mark.unit
def test_fk_constraint_json_round_trip() -> None:
    fk = ForeignKeyConstraint(
        name="fk",
        columns=("a", "b"),
        ref_namespace="public",
        ref_table="t",
        ref_columns=("x", "y"),
        on_delete=FKAction.SET_NULL,
    )
    assert ForeignKeyConstraint.model_validate_json(fk.model_dump_json()) == fk


# ---------------------------------------------------------------------------
# ExclusionElement
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_exclusion_element_minimal() -> None:
    elem = ExclusionElement(column_or_expr="range_col", operator="&&")
    assert elem.column_or_expr == "range_col"
    assert elem.operator == "&&"
    assert elem.opclass is None


@pytest.mark.unit
def test_exclusion_element_with_opclass() -> None:
    elem = ExclusionElement(column_or_expr="geom", operator="&&", opclass="gist_geometry_ops")
    assert elem.opclass == "gist_geometry_ops"


@pytest.mark.unit
def test_exclusion_element_empty_operator_rejected() -> None:
    with pytest.raises(ValidationError):
        ExclusionElement(column_or_expr="x", operator="")


@pytest.mark.unit
def test_exclusion_element_is_frozen() -> None:
    elem = ExclusionElement(column_or_expr="x", operator="=")
    with pytest.raises(ValidationError):
        elem.operator = "!="  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ExclusionConstraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_exclusion_constraint_minimal() -> None:
    elem = ExclusionElement(column_or_expr="room", operator="=")
    exc = ExclusionConstraint(
        name="no_overlap",
        index_method="gist",
        elements=(elem,),
    )
    assert exc.kind == "exclusion"
    assert exc.predicate is None


@pytest.mark.unit
def test_exclusion_constraint_with_predicate() -> None:
    elem = ExclusionElement(column_or_expr="during", operator="&&")
    exc = ExclusionConstraint(
        name="room_overlap",
        index_method="gist",
        elements=(elem,),
        predicate="(cancelled = false)",
    )
    assert exc.predicate == "(cancelled = false)"


@pytest.mark.unit
def test_exclusion_constraint_empty_elements_rejected() -> None:
    with pytest.raises(ValidationError):
        ExclusionConstraint(name="e", index_method="gist", elements=())


@pytest.mark.unit
def test_exclusion_constraint_json_round_trip() -> None:
    elem = ExclusionElement(column_or_expr="x", operator="&&", opclass="ops")
    exc = ExclusionConstraint(name="e", index_method="gist", elements=(elem,))
    assert ExclusionConstraint.model_validate_json(exc.model_dump_json()) == exc


# ---------------------------------------------------------------------------
# Discriminated union — Constraint TypeAdapter
# ---------------------------------------------------------------------------


_CONSTRAINT_TA: TypeAdapter[Constraint] = TypeAdapter(Constraint)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        {"kind": "primary_key", "name": "pk", "columns": ["id"]},
        {"kind": "unique", "name": "u", "columns": ["email"]},
        {"kind": "check", "name": "c", "expression": "(x > 0)"},
        {
            "kind": "foreign_key",
            "name": "fk",
            "columns": ["user_id"],
            "ref_namespace": "public",
            "ref_table": "users",
            "ref_columns": ["id"],
        },
        {
            "kind": "exclusion",
            "name": "e",
            "index_method": "gist",
            "elements": [{"column_or_expr": "r", "operator": "&&"}],
        },
    ],
)
def test_constraint_discriminated_union_round_trip(raw: dict[str, object]) -> None:
    constraint = _CONSTRAINT_TA.validate_python(raw)
    assert constraint.kind == raw["kind"]
    dumped = _CONSTRAINT_TA.dump_python(constraint, mode="json")
    restored = _CONSTRAINT_TA.validate_python(dumped)
    assert restored == constraint


@pytest.mark.unit
def test_constraint_unknown_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        _CONSTRAINT_TA.validate_python({"kind": "unknown", "name": "x"})


@pytest.mark.unit
def test_constraint_missing_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        _CONSTRAINT_TA.validate_python({"name": "pk", "columns": ["id"]})
