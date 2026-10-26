import pytest

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta import (
    AddColumn,
    CreateFunction,
    CreateTable,
    CreateTrigger,
    DeltaSet,
    DropColumn,
    DropTable,
    DropTrigger,
    RenameColumn,
    RenameTable,
    ReplaceFunction,
    ReplaceTrigger,
)
from pgschemadiff.domain.delta.function import DropFunction as DropFunctionDelta
from pgschemadiff.domain.function import Function
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.table import Table
from pgschemadiff.domain.trigger import Trigger


def _ref(kind: ObjectKind, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace="public", name=name))


def _function() -> Function:
    return Function(
        ref=ObjectRef(
            kind=ObjectKind.FUNCTION,
            qname=QualifiedName(namespace="public", name="audit_row"),
            arg_signature=(),
        ),
        return_type="trigger",
        language="plpgsql",
        volatility="volatile",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        body="RETURN NEW;",
        definition="CREATE OR REPLACE FUNCTION public.audit_row() RETURNS trigger",
    )


def _trigger(
    *,
    name: str = "items_audit",
    table_ref: ObjectRef | None = None,
    definition: str = "CREATE TRIGGER items_audit BEFORE UPDATE OF value ON public.items",
    columns: tuple[str, ...] = ("value",),
    when_expr: str | None = None,
    is_constraint: bool = False,
    deferrable: bool = False,
    initially_deferred: bool = False,
    referenced_table_ref: ObjectRef | None = None,
) -> Trigger:
    table_ref = table_ref or _ref(ObjectKind.TABLE, "items")
    return Trigger(
        ref=ObjectRef(
            kind=ObjectKind.TRIGGER,
            qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
            parent=table_ref,
        ),
        table_ref=table_ref,
        function_ref=_function().ref,
        definition=definition,
        timing="BEFORE",
        events=("UPDATE",),
        row_level=True,
        columns=columns,
        when_expr=when_expr,
        is_constraint=is_constraint,
        deferrable=deferrable,
        initially_deferred=initially_deferred,
        enabled="O",
        referenced_table_ref=referenced_table_ref,
    )


def _column_ref(table_ref: ObjectRef, name: str = "value") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
        parent=table_ref,
    )


def test_trigger_create_follows_new_table_function_and_referenced_column() -> None:
    trigger = _trigger()
    function = _function()
    table = Table(
        ref=trigger.table_ref,
        columns=(Column(name="value", position=1, data_type="integer"),),
        triggers=(trigger,),
    )
    create_trigger = CreateTrigger(target=trigger.ref, trigger=trigger)
    ordered = order_deltas(
        DeltaSet.from_iterable(
            (
                create_trigger,
                CreateFunction(target=function.ref, function=function),
                CreateTable(target=table.ref, table=table),
            )
        )
    ).deltas

    assert ordered.index(CreateTable(target=table.ref, table=table)) < ordered.index(create_trigger)
    assert ordered.index(CreateFunction(target=function.ref, function=function)) < ordered.index(
        create_trigger
    )


def test_trigger_create_follows_added_update_column() -> None:
    trigger = _trigger()
    column = Column(name="value", position=1, data_type="integer")
    add_column = AddColumn(target=_column_ref(trigger.table_ref), column=column)
    create_trigger = CreateTrigger(target=trigger.ref, trigger=trigger)

    ordered = order_deltas(DeltaSet.from_iterable((create_trigger, add_column))).deltas

    assert ordered.index(add_column) < ordered.index(create_trigger)


def test_trigger_drop_precedes_table_function_and_referenced_column_drops() -> None:
    trigger = _trigger()
    function = _function()
    table = Table(
        ref=trigger.table_ref,
        columns=(Column(name="value", position=1, data_type="integer"),),
        triggers=(trigger,),
    )
    drop_trigger = DropTrigger(target=trigger.ref, trigger=trigger)
    drop_column = DropColumn(target=_column_ref(trigger.table_ref), column=table.columns[0])
    drop_table = DropTable(target=table.ref, table=table)
    drop_function = DropFunctionDelta(target=function.ref, function=function)

    ordered = order_deltas(
        DeltaSet.from_iterable((drop_table, drop_function, drop_column, drop_trigger))
    ).deltas

    for later_drop in (drop_column, drop_table, drop_function):
        assert ordered.index(drop_trigger) < ordered.index(later_drop)


def test_trigger_replace_does_not_cycle_with_referenced_function_replace() -> None:
    old_function = _function()
    new_function = old_function.model_copy(update={"body": "RETURN OLD;"})
    replace_function = ReplaceFunction(
        target=old_function.ref,
        old_function=old_function,
        new_function=new_function,
    )
    old_trigger = _trigger()
    new_trigger = old_trigger.model_copy(
        update={"definition": "CREATE TRIGGER items_audit AFTER UPDATE ON public.items"}
    )
    replace_trigger = ReplaceTrigger(
        target=old_trigger.ref,
        old_trigger=old_trigger,
        new_trigger=new_trigger,
    )

    ordered = order_deltas(DeltaSet.from_iterable((replace_trigger, replace_function))).deltas

    assert ordered.index(replace_function) < ordered.index(replace_trigger)


def test_constraint_trigger_create_follows_referenced_table() -> None:
    referenced_table_ref = _ref(ObjectKind.TABLE, "z_parents")
    referenced_table = Table(ref=referenced_table_ref)
    trigger = _trigger(
        is_constraint=True,
        deferrable=True,
        referenced_table_ref=referenced_table_ref,
        definition=(
            "CREATE CONSTRAINT TRIGGER items_audit AFTER UPDATE ON public.items "
            "FROM public.z_parents DEFERRABLE FOR EACH ROW"
        ),
    )
    create_table = CreateTable(target=referenced_table_ref, table=referenced_table)
    create_trigger = CreateTrigger(target=trigger.ref, trigger=trigger)

    ordered = order_deltas(DeltaSet.from_iterable((create_trigger, create_table))).deltas

    assert ordered.index(create_table) < ordered.index(create_trigger)


def test_constraint_trigger_drop_precedes_referenced_table_drop() -> None:
    referenced_table_ref = _ref(ObjectKind.TABLE, "a_parents")
    referenced_table = Table(ref=referenced_table_ref)
    trigger = _trigger(
        is_constraint=True,
        deferrable=True,
        referenced_table_ref=referenced_table_ref,
        definition=(
            "CREATE CONSTRAINT TRIGGER items_audit AFTER UPDATE ON public.items "
            "FROM public.a_parents DEFERRABLE FOR EACH ROW"
        ),
    )
    drop_table = DropTable(target=referenced_table_ref, table=referenced_table)
    drop_trigger = DropTrigger(target=trigger.ref, trigger=trigger)

    ordered = order_deltas(DeltaSet.from_iterable((drop_table, drop_trigger))).deltas

    assert ordered.index(drop_trigger) < ordered.index(drop_table)


@pytest.mark.parametrize(
    ("old_columns", "old_when", "new_columns", "new_when"),
    [
        (("value",), None, ("sku",), None),
        ((), "NEW.value > 0", (), "NEW.sku > 0"),
    ],
    ids=("update-of", "when-expression"),
)
def test_trigger_replace_follows_referenced_column_rename(
    old_columns: tuple[str, ...],
    old_when: str | None,
    new_columns: tuple[str, ...],
    new_when: str | None,
) -> None:
    table_ref = _ref(ObjectKind.TABLE, "items")
    old_trigger = _trigger(columns=old_columns, when_expr=old_when)
    new_trigger = _trigger(
        columns=new_columns,
        when_expr=new_when,
        definition="CREATE TRIGGER items_audit AFTER UPDATE OF sku ON public.items",
    )
    replace_trigger = ReplaceTrigger(
        target=old_trigger.ref,
        old_trigger=old_trigger,
        new_trigger=new_trigger,
    )
    rename_column = RenameColumn(
        target=_column_ref(table_ref, "value"),
        old_name="value",
        new_name="sku",
    )

    ordered = order_deltas(DeltaSet.from_iterable((replace_trigger, rename_column))).deltas

    assert ordered.index(rename_column) < ordered.index(replace_trigger)


def test_trigger_drop_and_create_surround_parent_table_rename() -> None:
    old_table_ref = _ref(ObjectKind.TABLE, "items")
    new_table_ref = _ref(ObjectKind.TABLE, "archived_items")
    rename_table = RenameTable(
        target=old_table_ref,
        old_name=old_table_ref.qname,
        new_name=new_table_ref.qname,
    )
    old_trigger = _trigger(table_ref=old_table_ref, name="zzz_audit")
    new_trigger = _trigger(
        table_ref=new_table_ref,
        name="zzz_audit",
        definition="CREATE TRIGGER zzz_audit BEFORE UPDATE OF value ON public.archived_items",
    )
    drop_trigger = DropTrigger(target=old_trigger.ref, trigger=old_trigger)
    create_trigger = CreateTrigger(target=new_trigger.ref, trigger=new_trigger)

    ordered = order_deltas(
        DeltaSet.from_iterable((rename_table, create_trigger, drop_trigger))
    ).deltas

    assert ordered.index(drop_trigger) < ordered.index(rename_table) < ordered.index(create_trigger)
