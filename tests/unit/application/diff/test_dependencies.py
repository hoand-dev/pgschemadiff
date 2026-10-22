from __future__ import annotations

import pytest

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import Constraint, ForeignKeyConstraint, PrimaryKeyConstraint
from pgschemadiff.domain.delta.base import DeltaSet
from pgschemadiff.domain.delta.column import AddColumn, DropColumn, RenameColumn
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.delta.index import CreateIndex, DropIndex, ReplaceIndex
from pgschemadiff.domain.delta.schema import (
    CreateExtension,
    CreateSchema,
    DropExtension,
    DropSchema,
)
from pgschemadiff.domain.delta.table import CreateTable, DropTable, RenameTable
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.shared.errors import CyclicDependencyError


def _ref(kind: ObjectKind, name: str, *, namespace: str = "public") -> ObjectRef:
    return ObjectRef(
        kind=kind,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _column_ref(table_ref: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
        parent=table_ref,
    )


def _table(
    name: str,
    *,
    columns: tuple[str, ...] = (),
    constraints: tuple[Constraint, ...] = (),
    namespace: str = "public",
) -> Table:
    ref = _ref(ObjectKind.TABLE, name, namespace=namespace)
    return Table(
        ref=ref,
        columns=tuple(
            Column(name=column, position=position, data_type="integer")
            for position, column in enumerate(columns, start=1)
        ),
        constraints=constraints,
    )


def _index(name: str, table_ref: ObjectRef, *columns: str) -> Index:
    return Index(
        ref=_ref(ObjectKind.INDEX, name, namespace=table_ref.qname.namespace),
        table_ref=table_ref,
        key_columns=tuple(IndexKeyColumn(column_name=column) for column in columns),
    )


def _assert_precedes(ordered: tuple[object, ...], *deltas: object) -> None:
    positions = {delta: index for index, delta in enumerate(ordered)}
    assert [positions[delta] for delta in deltas] == sorted(positions[delta] for delta in deltas)


def test_creation_prerequisites_order_schema_table_column_constraint_and_index() -> None:
    schema_ref = _ref(ObjectKind.SCHEMA, "public")
    schema = Schema(ref=schema_ref)
    create_schema = CreateSchema(target=schema_ref, pg_schema=schema)

    table = _table("items")
    create_table = CreateTable(target=table.ref, table=table)
    sku = Column(name="sku", position=1, data_type="text")
    add_column = AddColumn(target=_column_ref(table.ref, "sku"), column=sku)
    constraint = PrimaryKeyConstraint(name="items_sku_pk", columns=("sku",))
    add_constraint = AddConstraint(
        target=ObjectRef(
            kind=ObjectKind.CONSTRAINT,
            qname=QualifiedName(namespace="public", name=constraint.name),
            parent=table.ref,
        ),
        constraint=constraint,
    )
    index = _index("items_sku_idx", table.ref, "sku")
    create_index = CreateIndex(target=index.ref, index=index)

    ordered = order_deltas(
        DeltaSet.from_iterable(
            (create_index, add_constraint, add_column, create_table, create_schema)
        )
    ).deltas

    _assert_precedes(ordered, create_schema, create_table)
    _assert_precedes(ordered, create_table, add_column)
    _assert_precedes(ordered, add_column, add_constraint)
    _assert_precedes(ordered, add_column, create_index)


def test_fk_addition_waits_for_owning_and_referenced_tables_and_columns() -> None:
    local_table = _table("orders")
    remote_table = _table("customers")
    create_local = CreateTable(target=local_table.ref, table=local_table)
    create_remote = CreateTable(target=remote_table.ref, table=remote_table)

    local_column = Column(name="customer_id", position=1, data_type="integer")
    add_local_column = AddColumn(
        target=_column_ref(local_table.ref, "customer_id"), column=local_column
    )
    remote_column = Column(name="id", position=1, data_type="integer")
    add_remote_column = AddColumn(target=_column_ref(remote_table.ref, "id"), column=remote_column)

    fk = ForeignKeyConstraint(
        name="orders_customer_fk",
        columns=("customer_id",),
        ref_namespace="public",
        ref_table="customers",
        ref_columns=("id",),
    )
    add_fk = AddConstraint(
        target=ObjectRef(
            kind=ObjectKind.CONSTRAINT,
            qname=QualifiedName(namespace="public", name=fk.name),
            parent=local_table.ref,
        ),
        constraint=fk,
    )

    ordered = order_deltas(
        DeltaSet.from_iterable(
            (add_fk, add_remote_column, create_remote, add_local_column, create_local)
        )
    ).deltas

    _assert_precedes(ordered, create_local, add_local_column, add_fk)
    _assert_precedes(ordered, create_remote, add_remote_column, add_fk)


def test_fk_embedded_in_create_table_waits_for_referenced_table() -> None:
    parent = _table("parents", columns=("id",))
    fk = ForeignKeyConstraint(
        name="children_parent_fk",
        columns=("parent_id",),
        ref_namespace="public",
        ref_table="parents",
        ref_columns=("id",),
    )
    child = _table("children", columns=("parent_id",), constraints=(fk,))
    create_parent = CreateTable(target=parent.ref, table=parent)
    create_child = CreateTable(target=child.ref, table=child)

    ordered = order_deltas(DeltaSet.from_iterable((create_child, create_parent))).deltas

    _assert_precedes(ordered, create_parent, create_child)


def test_fk_embedded_in_drop_table_drops_dependent_before_referenced_table() -> None:
    parent = _table("parents", columns=("id",))
    fk = ForeignKeyConstraint(
        name="children_parent_fk",
        columns=("parent_id",),
        ref_namespace="public",
        ref_table="parents",
        ref_columns=("id",),
    )
    child = _table("children", columns=("parent_id",), constraints=(fk,))
    drop_parent = DropTable(target=parent.ref, table=parent)
    drop_child = DropTable(target=child.ref, table=child)
    drop_fk = DropConstraint(
        target=ObjectRef(
            kind=ObjectKind.CONSTRAINT,
            qname=QualifiedName(namespace="public", name=fk.name),
            parent=child.ref,
        ),
        constraint=fk,
    )

    ordered = order_deltas(DeltaSet.from_iterable((drop_parent, drop_child, drop_fk))).deltas

    _assert_precedes(ordered, drop_fk, drop_child)
    _assert_precedes(ordered, drop_fk, drop_parent)
    _assert_precedes(ordered, drop_child, drop_parent)


def test_self_referencing_table_delta_has_no_self_edge() -> None:
    fk = ForeignKeyConstraint(
        name="employees_manager_fk",
        columns=("manager_id",),
        ref_namespace="public",
        ref_table="employees",
        ref_columns=("id",),
    )
    table = _table("employees", columns=("id", "manager_id"), constraints=(fk,))
    create_table = CreateTable(target=table.ref, table=table)
    drop_table = DropTable(target=table.ref, table=table)

    assert order_deltas(DeltaSet.from_iterable((create_table,))).deltas == (create_table,)
    assert order_deltas(DeltaSet.from_iterable((drop_table,))).deltas == (drop_table,)


def test_index_drop_and_replacement_order_before_dropping_owned_columns() -> None:
    table_ref = _ref(ObjectKind.TABLE, "items")
    old_index = _index("items_value_idx", table_ref, "old_value")
    new_index = _index("items_value_idx", table_ref, "new_value")
    replace_index = ReplaceIndex(
        target=new_index.ref,
        old_index=old_index,
        new_index=new_index,
    )
    add_column = AddColumn(
        target=_column_ref(table_ref, "new_value"),
        column=Column(name="new_value", position=2, data_type="text"),
    )
    drop_column = DropColumn(
        target=_column_ref(table_ref, "old_value"),
        column=Column(name="old_value", position=1, data_type="text"),
    )

    ordered = order_deltas(DeltaSet.from_iterable((drop_column, replace_index, add_column))).deltas

    _assert_precedes(ordered, add_column, replace_index, drop_column)

    index = _index("items_id_idx", table_ref, "id")
    drop_index = DropIndex(target=index.ref, index=index)
    drop_table = DropTable(target=table_ref, table=_table("items", columns=("id",)))
    dropped = order_deltas(DeltaSet.from_iterable((drop_table, drop_index))).deltas
    _assert_precedes(dropped, drop_index, drop_table)


def test_renames_precede_deltas_using_new_table_and_column_identities() -> None:
    old_table_ref = _ref(ObjectKind.TABLE, "old_items")
    new_table_ref = _ref(ObjectKind.TABLE, "items")
    rename_table = RenameTable(
        target=old_table_ref,
        old_name=old_table_ref.qname,
        new_name=new_table_ref.qname,
    )
    rename_column = RenameColumn(
        target=_column_ref(old_table_ref, "old_sku"),
        old_name="old_sku",
        new_name="sku",
    )
    index = _index("items_sku_idx", new_table_ref, "sku")
    create_index = CreateIndex(target=index.ref, index=index)

    ordered = order_deltas(
        DeltaSet.from_iterable((create_index, rename_column, rename_table))
    ).deltas

    _assert_precedes(ordered, rename_table, create_index)
    _assert_precedes(ordered, rename_column, create_index)


def test_extension_membership_orders_create_and_drop_with_schema() -> None:
    schema_ref = _ref(ObjectKind.SCHEMA, "extensions")
    schema = Schema(ref=schema_ref)
    create_schema = CreateSchema(target=schema_ref, pg_schema=schema)
    drop_schema = DropSchema(target=schema_ref, pg_schema=schema)
    extension_ref = _ref(ObjectKind.EXTENSION, "hstore")
    extension = Extension(ref=extension_ref, version="1.8", installed_schema="extensions")
    create_extension = CreateExtension(target=extension_ref, extension=extension)
    drop_extension = DropExtension(target=extension_ref, extension=extension)

    created = order_deltas(DeltaSet.from_iterable((create_extension, create_schema))).deltas
    dropped = order_deltas(DeltaSet.from_iterable((drop_schema, drop_extension))).deltas

    _assert_precedes(created, create_schema, create_extension)
    _assert_precedes(dropped, drop_extension, drop_schema)


def test_unrelated_deltas_have_deterministic_sort_key_order() -> None:
    deltas = tuple(
        CreateTable(target=(table := _table(name)).ref, table=table)
        for name in ("zeta", "alpha", "mu")
    )

    ordered = order_deltas(DeltaSet.from_iterable(reversed(deltas))).deltas

    assert tuple(delta.target.qname.name for delta in ordered) == ("alpha", "mu", "zeta")


def test_mutually_referencing_table_cycle_propagates() -> None:
    a_fk = ForeignKeyConstraint(
        name="a_b_fk",
        columns=("b_id",),
        ref_namespace="public",
        ref_table="b",
        ref_columns=("id",),
    )
    b_fk = ForeignKeyConstraint(
        name="b_a_fk",
        columns=("a_id",),
        ref_namespace="public",
        ref_table="a",
        ref_columns=("id",),
    )
    a = _table("a", columns=("id", "b_id"), constraints=(a_fk,))
    b = _table("b", columns=("id", "a_id"), constraints=(b_fk,))

    with pytest.raises(CyclicDependencyError):
        order_deltas(
            DeltaSet.from_iterable(
                (CreateTable(target=a.ref, table=a), CreateTable(target=b.ref, table=b))
            )
        )
