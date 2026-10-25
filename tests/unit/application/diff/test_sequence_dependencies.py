from __future__ import annotations

import pytest

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta.base import DeltaSet
from pgschemadiff.domain.delta.column import AddColumn, DropColumn, SetColumnDefault
from pgschemadiff.domain.delta.sequence import (
    AlterSequenceOwnedBy,
    AlterSequenceOwner,
    CreateSequence,
    DropSequence,
)
from pgschemadiff.domain.delta.table import AlterTableAttrs, CreateTable, DropTable
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import Table


def _ref(kind: ObjectKind, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace="public", name=name))


def _column_ref(table_ref: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
        parent=table_ref,
    )


def _sequence(name: str = "z_ticket_seq", *, owned_by: ObjectRef | None = None) -> Sequence:
    return Sequence(
        ref=_ref(ObjectKind.SEQUENCE, name),
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=999,
        cache=1,
        cycle=False,
        owner="app_owner",
        owned_by=owned_by,
    )


def _position(deltas: tuple[object, ...], target: object) -> int:
    return deltas.index(target)


@pytest.mark.unit
def test_sequence_precedes_table_default_and_owned_by_follows_owner_column() -> None:
    table_ref = _ref(ObjectKind.TABLE, "a_tickets")
    column_ref = _column_ref(table_ref, "id")
    sequence = _sequence(owned_by=column_ref)
    column = Column(
        name="id",
        position=1,
        data_type="bigint",
        default_expr="nextval('public.z_ticket_seq'::regclass)",
        sequence_prerequisites=(sequence.ref,),
    )
    table = Table(ref=table_ref, columns=(column,))
    create_sequence = CreateSequence(target=sequence.ref, sequence=sequence)
    create_table = CreateTable(target=table.ref, table=table)
    owned_by = AlterSequenceOwnedBy(target=sequence.ref, new_owned_by=column_ref)

    ordered = order_deltas(DeltaSet(deltas=(owned_by, create_table, create_sequence))).deltas

    assert _position(ordered, create_sequence) < _position(ordered, create_table)
    assert _position(ordered, create_table) < _position(ordered, owned_by)


@pytest.mark.unit
@pytest.mark.parametrize("drop_owner_kind", ["column", "table"])
def test_sequence_owner_transition_precedes_relink_and_old_owner_drop(
    drop_owner_kind: str,
) -> None:
    sequence = _sequence()
    old_table_ref = _ref(ObjectKind.TABLE, "old_tickets")
    new_table_ref = _ref(ObjectKind.TABLE, "new_tickets")
    old_column = _column_ref(old_table_ref, "id")
    new_column = _column_ref(new_table_ref, "id")
    change_owner = AlterSequenceOwner(
        target=sequence.ref,
        new_owner="new_owner",
        old_owned_by=old_column,
    )
    change_owned_by = AlterSequenceOwnedBy(
        target=sequence.ref,
        old_owned_by=old_column,
        new_owned_by=new_column,
    )
    create_new_table = CreateTable(
        target=new_table_ref,
        table=Table(
            ref=new_table_ref,
            columns=(Column(name="id", position=1, data_type="bigint"),),
            owner="new_owner",
        ),
    )
    if drop_owner_kind == "column":
        drop_old_owner: DropColumn | DropTable = DropColumn(
            target=old_column,
            column=Column(name="id", position=1, data_type="bigint"),
        )
    else:
        drop_old_owner = DropTable(
            target=old_table_ref,
            table=Table(
                ref=old_table_ref,
                columns=(Column(name="id", position=1, data_type="bigint"),),
                owner="old_owner",
            ),
        )

    ordered = order_deltas(
        DeltaSet(deltas=(drop_old_owner, change_owned_by, change_owner, create_new_table))
    ).deltas

    assert _position(ordered, create_new_table) < _position(ordered, change_owner)
    assert _position(ordered, change_owner) < _position(ordered, change_owned_by)
    assert _position(ordered, change_owner) < _position(ordered, drop_old_owner)
    assert _position(ordered, change_owned_by) < _position(ordered, drop_old_owner)


@pytest.mark.unit
def test_sequence_owned_by_link_waits_for_sequence_and_table_owner_changes() -> None:
    sequence = _sequence()
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    column_ref = _column_ref(table_ref, "id")
    change_owner = AlterSequenceOwner(target=sequence.ref, new_owner="new_owner")
    change_table_owner = AlterTableAttrs(target=table_ref, new_owner="new_owner")
    change_owned_by = AlterSequenceOwnedBy(
        target=sequence.ref,
        new_owned_by=column_ref,
    )

    ordered = order_deltas(
        DeltaSet(deltas=(change_owned_by, change_table_owner, change_owner))
    ).deltas

    assert _position(ordered, change_owner) < _position(ordered, change_owned_by)
    assert _position(ordered, change_table_owner) < _position(ordered, change_owned_by)


@pytest.mark.unit
def test_sequence_precedes_added_column_default() -> None:
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    sequence = _sequence()
    add_column = AddColumn(
        target=_column_ref(table_ref, "id"),
        column=Column(
            name="id",
            position=1,
            data_type="bigint",
            default_expr="nextval('public.z_ticket_seq'::regclass)",
            sequence_prerequisites=(sequence.ref,),
        ),
    )
    create_sequence = CreateSequence(target=sequence.ref, sequence=sequence)

    ordered = order_deltas(DeltaSet(deltas=(add_column, create_sequence))).deltas

    assert _position(ordered, create_sequence) < _position(ordered, add_column)


@pytest.mark.unit
def test_sequence_prerequisites_order_default_set_and_drop_before_sequence_drop() -> None:
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    sequence = _sequence()
    column_ref = _column_ref(table_ref, "id")
    set_default = SetColumnDefault(
        target=column_ref,
        new_default="nextval('public.z_ticket_seq'::regclass)",
        old_sequence_prerequisites=(),
        new_sequence_prerequisites=(sequence.ref,),
    )
    drop_default = SetColumnDefault(
        target=column_ref,
        new_default=None,
        old_sequence_prerequisites=(sequence.ref,),
        new_sequence_prerequisites=(),
    )
    create_sequence = CreateSequence(target=sequence.ref, sequence=sequence)
    drop_sequence = DropSequence(target=sequence.ref, sequence=sequence)

    creates_ordered = order_deltas(DeltaSet(deltas=(set_default, create_sequence))).deltas
    drops_ordered = order_deltas(DeltaSet(deltas=(drop_sequence, drop_default))).deltas

    assert _position(creates_ordered, create_sequence) < _position(creates_ordered, set_default)
    assert _position(drops_ordered, drop_default) < _position(drops_ordered, drop_sequence)


@pytest.mark.unit
@pytest.mark.parametrize("drop_owner_kind", ["column", "table"])
def test_owned_sequence_drop_is_omitted_when_owner_is_dropped(drop_owner_kind: str) -> None:
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    column_ref = _column_ref(table_ref, "id")
    sequence = _sequence(owned_by=column_ref)
    drop_sequence = DropSequence(target=sequence.ref, sequence=sequence)
    if drop_owner_kind == "column":
        drop_owner: DropColumn | DropTable = DropColumn(
            target=column_ref,
            column=Column(name="id", position=1, data_type="bigint"),
        )
    else:
        table = Table(
            ref=table_ref,
            columns=(Column(name="id", position=1, data_type="bigint"),),
        )
        drop_owner = DropTable(target=table_ref, table=table)

    ordered = order_deltas(DeltaSet(deltas=(drop_sequence, drop_owner)))

    assert drop_sequence not in ordered.deltas
    assert drop_owner in ordered.deltas
