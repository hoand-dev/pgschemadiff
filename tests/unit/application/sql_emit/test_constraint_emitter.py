from collections.abc import Iterable

import pytest
from syrupy.assertion import SnapshotAssertion

from pgschemadiff.application.sql_emit.constraint_emitter import handlers
from pgschemadiff.application.sql_emit.emitter import SqlStatement
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ConstraintDeferrability,
    ExclusionConstraint,
    ExclusionElement,
    FKAction,
    FKMatch,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.delta.base import DeltaBase
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.shared.errors import MigrationError


def _table_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="Sales", name='Order"Items'),
    )


def _constraint_ref(name: str, parent: ObjectRef | None = None) -> ObjectRef:
    table = parent or _table_ref()
    return ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=table.qname.namespace, name=name),
        parent=table,
    )


def _add(constraint: object) -> AddConstraint:
    return AddConstraint(
        target=_constraint_ref(constraint.name),  # type: ignore[attr-defined]
        constraint=constraint,  # type: ignore[arg-type]
    )


def _drop(constraint: object) -> DropConstraint:
    return DropConstraint(
        target=_constraint_ref(constraint.name),  # type: ignore[attr-defined]
        constraint=constraint,  # type: ignore[arg-type]
    )


def _assert_emitted(
    statements: Iterable[SqlStatement],
    delta: DeltaBase,
    transactional: tuple[bool, ...],
    new_unit: tuple[bool, ...],
) -> tuple[SqlStatement, ...]:
    result = tuple(statements)
    assert tuple(statement.transactional for statement in result) == transactional
    assert tuple(statement.new_unit for statement in result) == new_unit
    assert all(statement.delta is delta for statement in result)
    return result


def _constraints_for_drop() -> tuple[object, ...]:
    return (
        PrimaryKeyConstraint(name="constraint", columns=("id",), definition='PRIMARY KEY ("id")'),
        UniqueConstraint(name="constraint", columns=("id",), definition='UNIQUE ("id")'),
        CheckConstraint(name="constraint", expression="id > 0", definition="CHECK (id > 0)"),
        ForeignKeyConstraint(
            name="constraint",
            columns=("id",),
            ref_namespace="Sales",
            ref_table="Other",
            ref_columns=("id",),
        ),
        ExclusionConstraint(
            name="constraint",
            index_method="gist",
            elements=(ExclusionElement(column_or_expr="id", operator="="),),
            definition="EXCLUDE USING gist (id WITH =)",
        ),
    )


def test_constraint_handlers_cover_exact_delta_types() -> None:
    assert set(handlers()) == {AddConstraint, DropConstraint}


def test_add_primary_key(snapshot: SnapshotAssertion) -> None:
    delta = _add(
        PrimaryKeyConstraint(
            name="pk_orders",
            columns=("id",),
            definition='PRIMARY KEY ("id")',
        )
    )

    statements = _assert_emitted(handlers()[AddConstraint](delta), delta, (True,), (False,))

    assert tuple(statement.sql for statement in statements) == snapshot


def test_add_unique_constraint(snapshot: SnapshotAssertion) -> None:
    delta = _add(
        UniqueConstraint(
            name="uq_orders_email",
            columns=("email",),
            nulls_not_distinct=True,
            definition='UNIQUE NULLS NOT DISTINCT ("email") DEFERRABLE INITIALLY DEFERRED',
            deferrability=ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED,
        )
    )

    statements = _assert_emitted(handlers()[AddConstraint](delta), delta, (True,), (False,))

    assert tuple(statement.sql for statement in statements) == snapshot


def test_add_check_no_inherit_and_validate(snapshot: SnapshotAssertion) -> None:
    delta = _add(
        CheckConstraint(
            name="check_positive",
            expression="value > 0",
            no_inherit=True,
            definition="CHECK (value > 0) NO INHERIT",
        )
    )

    statements = _assert_emitted(
        handlers()[AddConstraint](delta), delta, (True, True), (False, True)
    )

    assert tuple(statement.sql for statement in statements) == snapshot


def test_add_check_without_no_inherit(snapshot: SnapshotAssertion) -> None:
    delta = _add(
        CheckConstraint(
            name="check_positive",
            expression="value > 0",
            definition="CHECK (value > 0)",
        )
    )

    statements = _assert_emitted(
        handlers()[AddConstraint](delta), delta, (True, True), (False, True)
    )

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.parametrize(
    ("on_update", "on_delete", "match_type", "deferrability"),
    [
        (
            FKAction.NO_ACTION,
            FKAction.RESTRICT,
            FKMatch.SIMPLE,
            ConstraintDeferrability.NOT_DEFERRABLE,
        ),
        (
            FKAction.CASCADE,
            FKAction.SET_NULL,
            FKMatch.FULL,
            ConstraintDeferrability.DEFERRABLE_INITIALLY_IMMEDIATE,
        ),
        (
            FKAction.SET_DEFAULT,
            FKAction.CASCADE,
            FKMatch.FULL,
            ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED,
        ),
    ],
    ids=["defaults", "cascade-set-null", "set-default-deferred"],
)
def test_add_foreign_key_uses_structured_options(
    on_update: FKAction,
    on_delete: FKAction,
    match_type: FKMatch,
    deferrability: ConstraintDeferrability,
    snapshot: SnapshotAssertion,
) -> None:
    delta = _add(
        ForeignKeyConstraint(
            name="fk_order_customer",
            columns=("customer_id",),
            ref_namespace="CRM",
            ref_table='Customer"Record',
            ref_columns=("id",),
            on_update=on_update,
            on_delete=on_delete,
            match_type=match_type,
            deferrability=deferrability,
        )
    )

    statements = _assert_emitted(
        handlers()[AddConstraint](delta), delta, (True, True), (False, True)
    )

    assert tuple(statement.sql for statement in statements) == snapshot


def test_add_exclusion_constraint(snapshot: SnapshotAssertion) -> None:
    delta = _add(
        ExclusionConstraint(
            name="excl_order_range",
            index_method="gist",
            elements=(
                ExclusionElement(column_or_expr='"during"', operator="&&"),
                ExclusionElement(column_or_expr='"region"', operator="="),
            ),
            predicate='WHERE ("during" IS NOT NULL)',
            definition=(
                'EXCLUDE USING gist ("during" WITH &&, "region" WITH =) '
                'WHERE ("during" IS NOT NULL)'
            ),
        )
    )

    statements = _assert_emitted(handlers()[AddConstraint](delta), delta, (True,), (False,))

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.parametrize(
    "constraint", _constraints_for_drop(), ids=["pk", "unique", "check", "fk", "exclusion"]
)
def test_drop_constraint_for_each_kind(constraint: object, snapshot: SnapshotAssertion) -> None:
    delta = _drop(constraint)

    statements = _assert_emitted(handlers()[DropConstraint](delta), delta, (True,), (False,))

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.parametrize("delta_type", [AddConstraint, DropConstraint], ids=["add", "drop"])
def test_constraint_handlers_reject_wrong_delta_types(delta_type: type[DeltaBase]) -> None:
    constraint = CheckConstraint(
        name="check_positive", expression="value > 0", definition="CHECK (value > 0)"
    )
    wrong_delta: DeltaBase = (
        DropConstraint(target=_constraint_ref(constraint.name), constraint=constraint)
        if delta_type is AddConstraint
        else AddConstraint(target=_constraint_ref(constraint.name), constraint=constraint)
    )

    with pytest.raises(MigrationError):
        handlers()[delta_type](wrong_delta)


@pytest.mark.parametrize(
    ("constraint_kind", "definition"),
    [
        ("pk", None),
        ("pk", "  "),
        ("pk", "?"),
        ("unique", None),
        ("unique", "  "),
        ("unique", "?"),
        ("check", None),
        ("check", "  "),
        ("check", "?"),
        ("exclusion", None),
        ("exclusion", "  "),
        ("exclusion", "?"),
    ],
    ids=[
        "pk-none",
        "pk-blank",
        "pk-sentinel",
        "unique-none",
        "unique-blank",
        "unique-sentinel",
        "check-none",
        "check-blank",
        "check-sentinel",
        "exclusion-none",
        "exclusion-blank",
        "exclusion-sentinel",
    ],
)
def test_add_raw_definition_constraints_reject_missing_definitions(
    constraint_kind: str, definition: str | None
) -> None:
    constraint: object
    if constraint_kind == "pk":
        constraint = PrimaryKeyConstraint(name="raw", columns=("id",), definition=definition)
    elif constraint_kind == "unique":
        constraint = UniqueConstraint(name="raw", columns=("id",), definition=definition)
    elif constraint_kind == "check":
        constraint = CheckConstraint(name="raw", expression="id > 0", definition=definition)
    else:
        constraint = ExclusionConstraint(
            name="raw",
            index_method="gist",
            elements=(ExclusionElement(column_or_expr="id", operator="="),),
            definition=definition,
        )

    with pytest.raises(MigrationError):
        handlers()[AddConstraint](_add(constraint))


def test_check_no_inherit_requires_catalog_clause() -> None:
    delta = _add(
        CheckConstraint(
            name="check_positive",
            expression="value > 0",
            no_inherit=True,
            definition="CHECK (value > 0)",
        )
    )

    with pytest.raises(MigrationError, match="NO INHERIT"):
        handlers()[AddConstraint](delta)


def test_foreign_key_rejects_match_partial() -> None:
    delta = _add(
        ForeignKeyConstraint(
            name="fk_order_customer",
            columns=("customer_id",),
            ref_namespace="CRM",
            ref_table="Customer",
            ref_columns=("id",),
            match_type=FKMatch.PARTIAL,
        )
    )

    with pytest.raises(MigrationError, match="MATCH PARTIAL"):
        handlers()[AddConstraint](delta)


@pytest.mark.parametrize(
    ("definition", "on_update", "on_delete"),
    [
        (
            "FOREIGN KEY (author_id) REFERENCES app.users (id) ON DELETE SET NULL (author_id)",
            FKAction.NO_ACTION,
            FKAction.SET_NULL,
        ),
        (
            "FOREIGN KEY (author_id) REFERENCES app.users (id) ON UPDATE SET DEFAULT (author_id)",
            FKAction.SET_DEFAULT,
            FKAction.NO_ACTION,
        ),
    ],
    ids=["delete-set-null-columns", "update-set-default-columns"],
)
def test_foreign_key_rejects_action_column_subsets(
    definition: str, on_update: FKAction, on_delete: FKAction
) -> None:
    delta = _add(
        ForeignKeyConstraint(
            name="fk_order_author",
            columns=("author_id",),
            ref_namespace="app",
            ref_table="users",
            ref_columns=("id",),
            on_update=on_update,
            on_delete=on_delete,
            definition=definition,
        )
    )

    with pytest.raises(MigrationError, match="column lists"):
        handlers()[AddConstraint](delta)


def test_foreign_key_action_subset_detection_ignores_quoted_identifiers() -> None:
    delta = _add(
        ForeignKeyConstraint(
            name="fk_order_author",
            columns=('ON DELETE SET NULL (x"y',),
            ref_namespace="app",
            ref_table="users",
            ref_columns=("id",),
            on_delete=FKAction.SET_NULL,
            definition=(
                'FOREIGN KEY ("ON DELETE SET NULL (x""y") REFERENCES app.users (id) '
                "ON DELETE SET NULL"
            ),
        )
    )

    statements = tuple(handlers()[AddConstraint](delta))

    assert 'FOREIGN KEY ("ON DELETE SET NULL (x""y")' in statements[0].sql


def test_foreign_key_rejects_parser_placeholder_column() -> None:
    delta = _add(
        ForeignKeyConstraint(
            name="fk_order_customer",
            columns=("?",),
            ref_namespace="CRM",
            ref_table="Customer",
            ref_columns=("id",),
        )
    )

    with pytest.raises(MigrationError):
        handlers()[AddConstraint](delta)


@pytest.mark.parametrize(
    ("ref_namespace", "ref_table"),
    [("?", "Customer"), ("CRM", "?")],
    ids=["namespace", "table"],
)
def test_foreign_key_rejects_reference_placeholders(ref_namespace: str, ref_table: str) -> None:
    delta = _add(
        ForeignKeyConstraint(
            name="fk_order_customer",
            columns=("customer_id",),
            ref_namespace=ref_namespace,
            ref_table=ref_table,
            ref_columns=("id",),
        )
    )

    with pytest.raises(MigrationError):
        handlers()[AddConstraint](delta)


def test_foreign_key_rejects_empty_columns_from_invalid_model() -> None:
    constraint = ForeignKeyConstraint.model_construct(
        name="fk_order_customer",
        columns=(),
        ref_namespace="CRM",
        ref_table="Customer",
        ref_columns=(),
    )
    delta = AddConstraint(target=_constraint_ref(constraint.name), constraint=constraint)

    with pytest.raises(MigrationError, match="missing catalog columns"):
        handlers()[AddConstraint](delta)


def test_foreign_key_rejects_mismatched_column_counts() -> None:
    delta = _add(
        ForeignKeyConstraint(
            name="fk_order_customer",
            columns=("customer_id", "tenant_id"),
            ref_namespace="CRM",
            ref_table="Customer",
            ref_columns=("id",),
        )
    )

    with pytest.raises(MigrationError, match="do not match in count"):
        handlers()[AddConstraint](delta)


@pytest.mark.parametrize("delta_type", [AddConstraint, DropConstraint], ids=["add", "drop"])
def test_constraint_handlers_reject_inherited_constraints(
    delta_type: type[DeltaBase],
) -> None:
    constraint = CheckConstraint(
        name="check_positive",
        expression="value > 0",
        definition="CHECK (value > 0)",
        inherited=True,
    )
    delta: DeltaBase = (
        AddConstraint(target=_constraint_ref(constraint.name), constraint=constraint)
        if delta_type is AddConstraint
        else DropConstraint(target=_constraint_ref(constraint.name), constraint=constraint)
    )

    with pytest.raises(MigrationError, match=r"(?i)inherited"):
        handlers()[delta_type](delta)


@pytest.mark.parametrize("delta_type", [AddConstraint, DropConstraint], ids=["add", "drop"])
@pytest.mark.parametrize("parent_kind", [None, ObjectKind.INDEX], ids=["missing", "wrong-kind"])
def test_constraint_handlers_reject_missing_owner_table(
    delta_type: type[DeltaBase], parent_kind: ObjectKind | None
) -> None:
    constraint = CheckConstraint(
        name="check_positive", expression="value > 0", definition="CHECK (value > 0)"
    )
    parent = (
        None
        if parent_kind is None
        else ObjectRef.model_construct(
            kind=parent_kind,
            qname=QualifiedName(namespace="Sales", name='Order"Items'),
            parent=None,
        )
    )
    target = ObjectRef.model_construct(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace="Sales", name=constraint.name),
        parent=parent,
    )
    delta: DeltaBase = (
        AddConstraint.model_construct(target=target, constraint=constraint)
        if delta_type is AddConstraint
        else DropConstraint.model_construct(target=target, constraint=constraint)
    )

    with pytest.raises(MigrationError, match="parent table"):
        handlers()[delta_type](delta)


def test_constraint_handler_rejects_invalid_identifier() -> None:
    delta = _add(
        PrimaryKeyConstraint(name="bad\x00name", columns=("id",), definition='PRIMARY KEY ("id")')
    )

    with pytest.raises(MigrationError):
        handlers()[AddConstraint](delta)
