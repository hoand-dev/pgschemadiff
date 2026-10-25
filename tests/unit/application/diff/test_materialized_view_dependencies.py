from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.domain.delta.base import DeltaSet
from pgschemadiff.domain.delta.materialized_view import (
    CreateMaterializedView,
    DropMaterializedView,
)
from pgschemadiff.domain.delta.sequence import CreateSequence, DropSequence
from pgschemadiff.domain.delta.table import CreateTable, DropTable
from pgschemadiff.domain.delta.view import CreateView, DropView
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.materialized_view import MaterializedView
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import Table
from pgschemadiff.domain.view import View


def _ref(kind: ObjectKind, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace="public", name=name))


def _assert_ordered(*expected: object, deltas: tuple[object, ...]) -> None:
    positions = [deltas.index(delta) for delta in expected]
    assert positions == sorted(positions)


def test_create_and_drop_order_table_materialized_view_then_dependent_view() -> None:
    table = Table(ref=_ref(ObjectKind.TABLE, "items"))
    materialized_view = MaterializedView(
        ref=_ref(ObjectKind.MATERIALIZED_VIEW, "items_mv"),
        columns=(("id", "integer"),),
        definition="SELECT id FROM public.items",
        prerequisites=(table.ref,),
    )
    view = View(
        ref=_ref(ObjectKind.VIEW, "items_view"),
        columns=(("id", "integer"),),
        definition="SELECT id FROM public.items_mv",
        prerequisites=(materialized_view.ref,),
    )
    create_table = CreateTable(target=table.ref, table=table)
    create_materialized_view = CreateMaterializedView(
        target=materialized_view.ref,
        materialized_view=materialized_view,
    )
    create_view = CreateView(target=view.ref, view=view)
    create_order = order_deltas(
        DeltaSet.from_iterable((create_view, create_materialized_view, create_table))
    ).deltas

    _assert_ordered(create_table, create_materialized_view, create_view, deltas=create_order)

    drop_view = DropView(target=view.ref, view=view)
    drop_materialized_view = DropMaterializedView(
        target=materialized_view.ref,
        materialized_view=materialized_view,
    )
    drop_table = DropTable(target=table.ref, table=table)
    drop_order = order_deltas(
        DeltaSet.from_iterable((drop_table, drop_materialized_view, drop_view))
    ).deltas

    _assert_ordered(drop_view, drop_materialized_view, drop_table, deltas=drop_order)


def test_create_and_drop_order_table_view_then_dependent_materialized_view() -> None:
    table = Table(ref=_ref(ObjectKind.TABLE, "items"))
    view = View(
        ref=_ref(ObjectKind.VIEW, "items_view"),
        columns=(("id", "integer"),),
        definition="SELECT id FROM public.items",
        prerequisites=(table.ref,),
    )
    materialized_view = MaterializedView(
        ref=_ref(ObjectKind.MATERIALIZED_VIEW, "items_mv"),
        columns=(("id", "integer"),),
        definition="SELECT id FROM public.items_view",
        prerequisites=(view.ref,),
    )
    create_table = CreateTable(target=table.ref, table=table)
    create_view = CreateView(target=view.ref, view=view)
    create_materialized_view = CreateMaterializedView(
        target=materialized_view.ref,
        materialized_view=materialized_view,
    )
    create_order = order_deltas(
        DeltaSet.from_iterable((create_materialized_view, create_table, create_view))
    ).deltas

    _assert_ordered(create_table, create_view, create_materialized_view, deltas=create_order)

    drop_table = DropTable(target=table.ref, table=table)
    drop_view = DropView(target=view.ref, view=view)
    drop_materialized_view = DropMaterializedView(
        target=materialized_view.ref,
        materialized_view=materialized_view,
    )
    drop_order = order_deltas(
        DeltaSet.from_iterable((drop_view, drop_materialized_view, drop_table))
    ).deltas

    _assert_ordered(drop_materialized_view, drop_view, drop_table, deltas=drop_order)


def test_create_and_drop_order_sequence_then_dependent_materialized_view() -> None:
    sequence = Sequence(
        ref=_ref(ObjectKind.SEQUENCE, "z_source_seq"),
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=100,
        cache=1,
        cycle=False,
    )
    materialized_view = MaterializedView(
        ref=_ref(ObjectKind.MATERIALIZED_VIEW, "a_sequence_state"),
        columns=(("last_value", "bigint"),),
        definition="SELECT last_value FROM public.z_source_seq",
        prerequisites=(sequence.ref,),
    )
    create_sequence = CreateSequence(target=sequence.ref, sequence=sequence)
    create_materialized_view = CreateMaterializedView(
        target=materialized_view.ref,
        materialized_view=materialized_view,
    )
    create_order = order_deltas(
        DeltaSet.from_iterable((create_materialized_view, create_sequence))
    ).deltas

    _assert_ordered(create_sequence, create_materialized_view, deltas=create_order)

    drop_sequence = DropSequence(target=sequence.ref, sequence=sequence)
    drop_materialized_view = DropMaterializedView(
        target=materialized_view.ref,
        materialized_view=materialized_view,
    )
    drop_order = order_deltas(
        DeltaSet.from_iterable((drop_sequence, drop_materialized_view))
    ).deltas

    _assert_ordered(drop_materialized_view, drop_sequence, deltas=drop_order)
