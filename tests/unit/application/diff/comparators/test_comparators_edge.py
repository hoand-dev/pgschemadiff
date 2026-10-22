"""Edge cases shared across per-object comparators."""

from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.column import ColumnComparator
from pgschemadiff.application.diff.comparators.constraint import ConstraintComparator
from pgschemadiff.application.diff.comparators.index import IndexComparator
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    Constraint,
    ExclusionConstraint,
    ExclusionElement,
    FKAction,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.delta.column import AlterColumnType
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.delta.index import ReplaceIndex
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, NullsOrder


def _table_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )


def _column_ref(table_ref: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
        parent=table_ref,
    )


def _constraint_ref(table_ref: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
        parent=table_ref,
    )


def _index(table_ref: ObjectRef, key_columns: tuple[IndexKeyColumn, ...]) -> Index:
    return Index(
        ref=ObjectRef(
            kind=ObjectKind.INDEX,
            qname=QualifiedName(namespace=table_ref.qname.namespace, name="items_idx"),
        ),
        table_ref=table_ref,
        key_columns=key_columns,
    )


@pytest.mark.unit
def test_changed_columns_follow_position_not_snapshot_tuple_order() -> None:
    table_ref = _table_ref()
    source = (
        Column(name="second", position=2, data_type="text", nullable=False),
        Column(name="first", position=1, data_type="text", nullable=False),
    )
    target = (
        Column(name="second", position=2, data_type="varchar", nullable=False),
        Column(name="first", position=1, data_type="varchar", nullable=False),
    )

    assert ColumnComparator().compare_columns(table_ref, source, target) == (
        AlterColumnType(target=_column_ref(table_ref, "first"), new_data_type="varchar"),
        AlterColumnType(target=_column_ref(table_ref, "second"), new_data_type="varchar"),
    )


@pytest.mark.unit
def test_type_and_collation_change_share_one_type_delta() -> None:
    table_ref = _table_ref()
    source = Column(name="label", position=1, data_type="text", nullable=False)
    target = Column(
        name="label",
        position=1,
        data_type="varchar",
        nullable=False,
        collation="en_US",
    )

    assert ColumnComparator().compare_columns(table_ref, (source,), (target,)) == (
        AlterColumnType(
            target=_column_ref(table_ref, "label"),
            new_data_type="varchar",
            new_collation="en_US",
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source_keys", "target_keys"),
    [
        pytest.param(
            (IndexKeyColumn(column_name="created_at", nulls_order=NullsOrder.FIRST),),
            (IndexKeyColumn(column_name="created_at", nulls_order=NullsOrder.LAST),),
            id="nulls-order",
        ),
        pytest.param(
            (IndexKeyColumn(expression="lower(email)"),),
            (IndexKeyColumn(expression="upper(email)"),),
            id="expression",
        ),
        pytest.param(
            (IndexKeyColumn(column_name="tenant_id"), IndexKeyColumn(column_name="id")),
            (IndexKeyColumn(column_name="id"), IndexKeyColumn(column_name="tenant_id")),
            id="composite-key-order",
        ),
    ],
)
def test_nested_key_difference_replaces_index(
    source_keys: tuple[IndexKeyColumn, ...],
    target_keys: tuple[IndexKeyColumn, ...],
) -> None:
    table_ref = _table_ref()
    source = _index(table_ref, source_keys)
    target = _index(table_ref, target_keys)

    (delta,) = IndexComparator().compare(source, target)

    assert isinstance(delta, ReplaceIndex)
    assert delta.target == target.ref
    assert delta.old_index == source
    assert delta.new_index == target


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "target"),
    [
        pytest.param(
            PrimaryKeyConstraint(name="items_pk", columns=("id",), index_method="btree"),
            PrimaryKeyConstraint(name="items_pk", columns=("id",), index_method="hash"),
            id="primary-key-index-method",
        ),
        pytest.param(
            UniqueConstraint(name="items_uq", columns=("tenant_id", "code")),
            UniqueConstraint(name="items_uq", columns=("code", "tenant_id")),
            id="unique-column-order",
        ),
        pytest.param(
            CheckConstraint(name="items_chk", expression="price > 0", no_inherit=False),
            CheckConstraint(name="items_chk", expression="price > 0", no_inherit=True),
            id="check-no-inherit",
        ),
        pytest.param(
            ForeignKeyConstraint(
                name="items_fk",
                columns=("owner_id",),
                ref_namespace="public",
                ref_table="owners",
                ref_columns=("id",),
                on_update=FKAction.NO_ACTION,
            ),
            ForeignKeyConstraint(
                name="items_fk",
                columns=("owner_id",),
                ref_namespace="public",
                ref_table="owners",
                ref_columns=("id",),
                on_update=FKAction.CASCADE,
            ),
            id="foreign-key-on-update",
        ),
        pytest.param(
            ForeignKeyConstraint(
                name="items_fk",
                columns=("owner_id",),
                ref_namespace="public",
                ref_table="owners",
                ref_columns=("id",),
            ),
            ForeignKeyConstraint(
                name="items_fk",
                columns=("owner_id",),
                ref_namespace="public",
                ref_table="owners",
                ref_columns=("uuid",),
            ),
            id="foreign-key-referenced-columns",
        ),
        pytest.param(
            ExclusionConstraint(
                name="items_excl",
                index_method="gist",
                elements=(ExclusionElement(column_or_expr="period", operator="&&"),),
            ),
            ExclusionConstraint(
                name="items_excl",
                index_method="gist",
                elements=(ExclusionElement(column_or_expr="period", operator="="),),
            ),
            id="exclusion-operator",
        ),
        pytest.param(
            ExclusionConstraint(
                name="items_excl",
                index_method="gist",
                elements=(ExclusionElement(column_or_expr="period", operator="&&"),),
            ),
            ExclusionConstraint(
                name="items_excl",
                index_method="gist",
                elements=(
                    ExclusionElement(column_or_expr="period", operator="&&", opclass="range_ops"),
                ),
            ),
            id="exclusion-opclass",
        ),
    ],
)
def test_constraint_definition_edge_change_emits_drop_then_add(
    source: Constraint,
    target: Constraint,
) -> None:
    table_ref = _table_ref()
    constraint_ref = _constraint_ref(table_ref, source.name)

    assert ConstraintComparator().compare_sets(table_ref, (source,), (target,)) == (
        DropConstraint(target=constraint_ref, constraint=source),
        AddConstraint(target=constraint_ref, constraint=target),
    )
