"""Tests for column-level schema comparisons."""

from __future__ import annotations

from typing import Literal

import pytest

import pgschemadiff.application.diff.comparators as comparator_package
from pgschemadiff.application.diff.comparators.column import ColumnComparator
from pgschemadiff.application.diff.comparators.table import (
    ColumnComparing,
    TableComparator,
)
from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.delta import (
    AddColumn,
    AlterColumnType,
    DropColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.table import Table
from pgschemadiff.shared.errors import DiffError


def _table_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )


def _column_ref(table_ref: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
        parent=table_ref,
    )


def _column(
    name: str = "id",
    *,
    position: int = 1,
    data_type: str = "integer",
    nullable: bool = False,
    default_expr: str | None = None,
    collation: str | None = None,
    identity: IdentitySpec | None = None,
    generated_expression: str | None = None,
    generated_kind: Literal["stored", "virtual"] | None = None,
) -> Column:
    return Column(
        name=name,
        position=position,
        data_type=data_type,
        nullable=nullable,
        default_expr=default_expr,
        collation=collation,
        identity=identity,
        generated_expression=generated_expression,
        generated_kind=generated_kind,
    )


@pytest.mark.unit
def test_column_comparator_satisfies_table_column_protocol() -> None:
    assert isinstance(ColumnComparator(), ColumnComparing)


@pytest.mark.unit
def test_column_comparator_is_exported_and_wires_into_table_comparator() -> None:
    table_ref = _table_ref()
    source_column = _column("email", data_type="text")
    target_column = _column("email", data_type="varchar")
    source = Table(ref=table_ref, columns=(source_column,))
    target = Table(ref=table_ref, columns=(target_column,))

    assert comparator_package.ColumnComparator is ColumnComparator
    assert TableComparator(column_comparator=ColumnComparator()).compare(source, target) == (
        AlterColumnType(
            target=_column_ref(table_ref, "email"),
            new_data_type="varchar",
        ),
    )


@pytest.mark.unit
def test_identical_columns_produce_no_deltas() -> None:
    column = _column()

    assert ColumnComparator().compare_columns(_table_ref(), (column,), (column,)) == ()


@pytest.mark.unit
def test_added_and_dropped_columns_follow_snapshot_position_order() -> None:
    table_ref = _table_ref()
    added = _column("alpha", position=2, data_type="text")
    dropped = _column("zeta", position=3, data_type="text")

    deltas = ColumnComparator().compare_columns(
        table_ref,
        (dropped,),
        (added,),
    )

    assert deltas == (
        AddColumn(target=_column_ref(table_ref, "alpha"), column=added),
        DropColumn(target=_column_ref(table_ref, "zeta"), column=dropped),
    )


@pytest.mark.unit
def test_added_columns_follow_target_position_order() -> None:
    table_ref = _table_ref()
    zeta = _column("zeta", position=2, data_type="text")
    alpha = _column("alpha", position=3, data_type="text")

    assert ColumnComparator().compare_columns(table_ref, (), (zeta, alpha)) == (
        AddColumn(target=_column_ref(table_ref, "zeta"), column=zeta),
        AddColumn(target=_column_ref(table_ref, "alpha"), column=alpha),
    )


@pytest.mark.unit
def test_type_default_and_nullability_changes_emit_deterministic_deltas() -> None:
    table_ref = _table_ref()
    source = _column("email", data_type="text", nullable=True)
    target = _column(
        "email",
        data_type="character varying(255)",
        nullable=False,
        default_expr="'unknown'",
    )
    ref = _column_ref(table_ref, "email")

    assert ColumnComparator().compare_columns(table_ref, (source,), (target,)) == (
        AlterColumnType(target=ref, new_data_type="character varying(255)"),
        SetColumnDefault(target=ref, new_default="'unknown'"),
        SetColumnNullability(target=ref, nullable=False),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("old_default", "new_default"),
    [(None, "42"), ("42", None)],
    ids=["set-default", "drop-default"],
)
def test_default_transitions_preserve_none_semantics(
    old_default: str | None,
    new_default: str | None,
) -> None:
    table_ref = _table_ref()
    source = _column("id", default_expr=old_default)
    target = _column("id", default_expr=new_default)

    assert ColumnComparator().compare_columns(table_ref, (source,), (target,)) == (
        SetColumnDefault(
            target=_column_ref(table_ref, "id"),
            new_default=new_default,
        ),
    )


@pytest.mark.unit
def test_setting_collation_uses_existing_type_delta() -> None:
    table_ref = _table_ref()
    source = _column("label", data_type="text")
    target = _column("label", data_type="text", collation="en_US")

    assert ColumnComparator().compare_columns(table_ref, (source,), (target,)) == (
        AlterColumnType(
            target=_column_ref(table_ref, "label"),
            new_data_type="text",
            new_collation="en_US",
        ),
    )


@pytest.mark.unit
def test_removing_collation_raises_diff_error() -> None:
    table_ref = _table_ref()
    source = _column("label", data_type="text", collation="en_US")
    target = _column("label", data_type="text")

    with pytest.raises(DiffError, match="collation"):
        ColumnComparator().compare_columns(table_ref, (source,), (target,))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "target", "field"),
    [
        pytest.param(_column(position=1), _column(position=2), "position", id="position"),
        pytest.param(
            _column(),
            _column(identity=IdentitySpec(generated=GeneratedTiming.ALWAYS)),
            "identity",
            id="identity",
        ),
        pytest.param(
            _column(),
            _column(generated_expression="id * 2"),
            "generated_expression",
            id="generated-expression",
        ),
        pytest.param(
            _column(generated_expression="id * 2"),
            _column(generated_expression="id * 2", generated_kind="virtual"),
            "generated_expression",
            id="generated-kind",
        ),
    ],
)
def test_unrepresentable_metadata_changes_raise_diff_error(
    source: Column,
    target: Column,
    field: str,
) -> None:
    with pytest.raises(DiffError, match=field):
        ColumnComparator().compare_columns(_table_ref(), (source,), (target,))


@pytest.mark.unit
def test_column_rename_is_not_inferred_and_becomes_drop_plus_add() -> None:
    table_ref = _table_ref()
    source = _column("old_name")
    target = _column("new_name")

    deltas = ColumnComparator().compare_columns(table_ref, (source,), (target,))

    assert deltas == (
        AddColumn(target=_column_ref(table_ref, "new_name"), column=target),
        DropColumn(target=_column_ref(table_ref, "old_name"), column=source),
    )
