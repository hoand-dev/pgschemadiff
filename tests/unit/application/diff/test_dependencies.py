from __future__ import annotations

import pytest

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    Constraint,
    ExclusionConstraint,
    ExclusionElement,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.delta.base import DeltaSet
from pgschemadiff.domain.delta.column import (
    AddColumn,
    AlterColumnType,
    DropColumn,
    RenameColumn,
    SetColumnDefault,
)
from pgschemadiff.domain.delta.composite_type import (
    AlterCompositeAddAttribute,
    AlterCompositeAttributeType,
    AlterCompositeDropAttribute,
    CreateCompositeType,
    DropCompositeType,
)
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.delta.domain_type import CreateDomain, DropDomain
from pgschemadiff.domain.delta.enum import AddEnumValue, CreateEnum, DropEnum
from pgschemadiff.domain.delta.function import CreateFunction, DropFunction
from pgschemadiff.domain.delta.index import CreateIndex, DropIndex, ReplaceIndex
from pgschemadiff.domain.delta.procedure import CreateProcedure, DropProcedure
from pgschemadiff.domain.delta.schema import (
    AlterExtension,
    CreateExtension,
    CreateSchema,
    DropExtension,
    DropSchema,
)
from pgschemadiff.domain.delta.table import CreateTable, DropTable, RenameTable
from pgschemadiff.domain.domain_type import DomainType
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.procedure import Procedure, ProcedureArgument
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import PartitionOf, Table


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


def _sequence(name: str, *, owned_by: ObjectRef | None = None) -> Sequence:
    return Sequence(
        ref=_ref(ObjectKind.SEQUENCE, name),
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=9223372036854775807,
        cache=1,
        cycle=False,
        owner="app_owner",
        owned_by=owned_by,
    )


def _index(name: str, table_ref: ObjectRef, *columns: str) -> Index:
    return Index(
        ref=_ref(ObjectKind.INDEX, name, namespace=table_ref.qname.namespace),
        table_ref=table_ref,
        key_columns=tuple(IndexKeyColumn(column_name=column) for column in columns),
    )


def _add_constraint(table: Table, constraint: Constraint) -> AddConstraint:
    return AddConstraint(
        target=ObjectRef(
            kind=ObjectKind.CONSTRAINT,
            qname=QualifiedName(
                namespace=table.ref.qname.namespace,
                name=constraint.name,
            ),
            parent=table.ref,
        ),
        constraint=constraint,
    )


def _drop_constraint(table: Table, constraint: Constraint) -> DropConstraint:
    return DropConstraint(
        target=ObjectRef(
            kind=ObjectKind.CONSTRAINT,
            qname=QualifiedName(
                namespace=table.ref.qname.namespace,
                name=constraint.name,
            ),
            parent=table.ref,
        ),
        constraint=constraint,
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


def test_enum_creation_and_additions_precede_table_and_index_changes() -> None:
    enum_ref = _ref(ObjectKind.ENUM, "state")
    enum = EnumType(ref=enum_ref, labels=("ready",))
    create_enum = CreateEnum(target=enum_ref, enum=enum)
    add_review = AddEnumValue(target=enum_ref, label="review", after="ready")
    add_done = AddEnumValue(target=enum_ref, label="done", after="review")

    table = _table("items", columns=("id",))
    create_table = CreateTable(target=table.ref, table=table)
    state_column = Column(name="state", position=2, data_type="public.state")
    add_column = AddColumn(target=_column_ref(table.ref, "state"), column=state_column)
    alter_type = AlterColumnType(target=_column_ref(table.ref, "id"), new_data_type="bigint")
    set_default = SetColumnDefault(
        target=_column_ref(table.ref, "id"), new_default="'done'::public.state"
    )
    add_constraint = _add_constraint(table, CheckConstraint(name="items_check", expression="true"))
    index = _index("items_id_idx", table.ref, "id")
    create_index = CreateIndex(target=index.ref, index=index)
    old_index = _index("items_replaced_idx", table.ref, "id")
    new_index = _index("items_replaced_idx", table.ref, "state")
    replace_index = ReplaceIndex(target=new_index.ref, old_index=old_index, new_index=new_index)
    dependents = (
        create_table,
        add_column,
        alter_type,
        set_default,
        add_constraint,
        create_index,
        replace_index,
    )

    ordered = order_deltas(
        DeltaSet.from_iterable((*reversed(dependents), add_review, add_done, create_enum))
    ).deltas

    _assert_precedes(ordered, create_enum, add_review, add_done)
    for dependent in dependents:
        _assert_precedes(ordered, add_done, dependent)


def test_type_prerequisites_order_enum_nested_composite_table_creates_and_reverse_drops() -> None:
    enum_ref = _ref(ObjectKind.ENUM, "state")
    enum = EnumType(ref=enum_ref, labels=("ready",))
    create_enum = CreateEnum(target=enum_ref, enum=enum)
    drop_enum = DropEnum(target=enum_ref, enum=enum)

    inner_ref = _ref(ObjectKind.COMPOSITE_TYPE, "inner")
    inner = CompositeType(
        ref=inner_ref,
        attributes=(CompositeAttribute(name="state", data_type="public.state"),),
        type_prerequisites=(enum_ref,),
    )
    create_inner = CreateCompositeType(target=inner_ref, composite=inner)
    drop_inner = DropCompositeType(target=inner_ref, composite=inner)

    outer_ref = _ref(ObjectKind.COMPOSITE_TYPE, "outer")
    outer = CompositeType(
        ref=outer_ref,
        attributes=(CompositeAttribute(name="inner", data_type="public.inner"),),
        type_prerequisites=(inner_ref,),
    )
    create_outer = CreateCompositeType(target=outer_ref, composite=outer)
    drop_outer = DropCompositeType(target=outer_ref, composite=outer)

    table = _table("events").model_copy(update={"type_prerequisites": (outer_ref,)})
    create_table = CreateTable(target=table.ref, table=table)
    drop_table = DropTable(target=table.ref, table=table)

    created = order_deltas(
        DeltaSet.from_iterable((create_table, create_outer, create_inner, create_enum))
    ).deltas
    dropped = order_deltas(
        DeltaSet.from_iterable((drop_enum, drop_inner, drop_outer, drop_table))
    ).deltas

    _assert_precedes(created, create_enum, create_inner, create_outer, create_table)
    _assert_precedes(dropped, drop_table, drop_outer, drop_inner, drop_enum)


def test_domain_base_type_and_domain_users_order_create_and_drop() -> None:
    enum_ref = _ref(ObjectKind.ENUM, "state")
    enum = EnumType(ref=enum_ref, labels=("ready",))
    create_enum = CreateEnum(target=enum_ref, enum=enum)
    drop_enum = DropEnum(target=enum_ref, enum=enum)

    domain_ref = _ref(ObjectKind.DOMAIN_TYPE, "state_domain")
    domain = DomainType(
        ref=domain_ref,
        base_type="public.state",
        type_prerequisites=(enum_ref,),
    )
    create_domain = CreateDomain(target=domain_ref, domain=domain)
    drop_domain = DropDomain(target=domain_ref, domain=domain)

    table = _table("events").model_copy(update={"type_prerequisites": (domain_ref,)})
    create_table = CreateTable(target=table.ref, table=table)
    drop_table = DropTable(target=table.ref, table=table)

    created = order_deltas(
        DeltaSet.from_iterable((create_table, create_domain, create_enum))
    ).deltas
    dropped = order_deltas(DeltaSet.from_iterable((drop_enum, drop_domain, drop_table))).deltas

    _assert_precedes(created, create_enum, create_domain, create_table)
    _assert_precedes(dropped, drop_table, drop_domain, drop_enum)


def test_function_signature_types_order_before_create_and_after_drop() -> None:
    enum_ref = _ref(ObjectKind.ENUM, "state", namespace="types")
    enum = EnumType(ref=enum_ref, labels=("ready",))
    create_enum = CreateEnum(target=enum_ref, enum=enum)
    drop_enum = DropEnum(target=enum_ref, enum=enum)
    function_ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="public", name="use_state"),
        arg_signature=("types.state",),
    )
    function = Function(
        ref=function_ref,
        arguments=(FunctionArgument(name="state", data_type="types.state"),),
        return_type="integer",
        language="sql",
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        body="SELECT 1",
        definition="CREATE OR REPLACE FUNCTION public.use_state(types.state) ...",
        type_prerequisites=(enum_ref,),
    )
    create_function = CreateFunction(target=function_ref, function=function)
    drop_function = DropFunction(target=function_ref, function=function)

    created = order_deltas(DeltaSet.from_iterable((create_function, create_enum))).deltas
    dropped = order_deltas(DeltaSet.from_iterable((drop_enum, drop_function))).deltas

    _assert_precedes(created, create_enum, create_function)
    _assert_precedes(dropped, drop_function, drop_enum)


def test_procedure_type_prerequisites_and_table_work_are_ordered() -> None:
    enum_ref = _ref(ObjectKind.ENUM, "state", namespace="types")
    enum = EnumType(ref=enum_ref, labels=("ready",))
    create_enum = CreateEnum(target=enum_ref, enum=enum)
    drop_enum = DropEnum(target=enum_ref, enum=enum)
    procedure_ref = ObjectRef(
        kind=ObjectKind.PROCEDURE,
        qname=QualifiedName(namespace="public", name="z_routine"),
        arg_signature=("types.state",),
    )
    procedure = Procedure(
        ref=procedure_ref,
        arguments=(ProcedureArgument(name="state", data_type="types.state"),),
        language="sql",
        security_definer=False,
        body="SELECT 1",
        definition="CREATE OR REPLACE PROCEDURE public.z_routine(types.state) ...",
        type_prerequisites=(enum_ref,),
    )
    create_procedure = CreateProcedure(target=procedure_ref, procedure=procedure)
    drop_procedure = DropProcedure(target=procedure_ref, procedure=procedure)
    table = _table("a_events")
    create_table = CreateTable(target=table.ref, table=table)
    drop_table = DropTable(target=table.ref, table=table)

    created = order_deltas(
        DeltaSet.from_iterable((create_table, create_procedure, create_enum))
    ).deltas
    dropped = order_deltas(DeltaSet.from_iterable((drop_enum, drop_procedure, drop_table))).deltas

    _assert_precedes(created, create_enum, create_procedure, create_table)
    _assert_precedes(dropped, drop_table, drop_procedure, drop_enum)


def test_domain_ordering_covers_column_add_type_change_and_removal() -> None:
    new_domain_ref = _ref(ObjectKind.DOMAIN_TYPE, "z_new_domain")
    new_domain = DomainType(ref=new_domain_ref, base_type="integer")
    create_domain = CreateDomain(target=new_domain_ref, domain=new_domain)

    table_ref = _ref(ObjectKind.TABLE, "a_events")
    column = Column(name="state", position=1, data_type="public.z_new_domain")
    column_ref = _column_ref(table_ref, column.name)
    add_column = AddColumn(target=column_ref, column=column)
    alter_to_domain = AlterColumnType(target=column_ref, new_data_type="public.z_new_domain")

    old_domain_ref = _ref(ObjectKind.DOMAIN_TYPE, "a_old_domain")
    old_domain = DomainType(ref=old_domain_ref, base_type="integer")
    drop_domain = DropDomain(target=old_domain_ref, domain=old_domain)
    drop_column = DropColumn(target=column_ref, column=column)
    alter_from_domain = AlterColumnType(target=column_ref, new_data_type="integer")

    created = order_deltas(DeltaSet.from_iterable((add_column, create_domain))).deltas
    altered_to = order_deltas(DeltaSet.from_iterable((alter_to_domain, create_domain))).deltas
    dropped = order_deltas(DeltaSet.from_iterable((drop_domain, drop_column))).deltas
    altered_from = order_deltas(DeltaSet.from_iterable((drop_domain, alter_from_domain))).deltas

    _assert_precedes(created, create_domain, add_column)
    _assert_precedes(altered_to, create_domain, alter_to_domain)
    _assert_precedes(dropped, drop_column, drop_domain)
    _assert_precedes(altered_from, alter_from_domain, drop_domain)


def test_composite_attribute_changes_order_new_and_old_type_prerequisites() -> None:
    old_ref = _ref(ObjectKind.ENUM, "old_state")
    old_enum = EnumType(ref=old_ref, labels=("ready",))
    drop_old_enum = DropEnum(target=old_ref, enum=old_enum)

    new_ref = _ref(ObjectKind.COMPOSITE_TYPE, "new_state")
    new_type = CompositeType(ref=new_ref)
    create_new_type = CreateCompositeType(target=new_ref, composite=new_type)

    composite_ref = _ref(ObjectKind.COMPOSITE_TYPE, "record")
    add_attribute = AlterCompositeAddAttribute(
        target=composite_ref,
        attribute=CompositeAttribute(name="state", data_type="public.new_state"),
        type_prerequisites=(new_ref,),
    )
    change_attribute_type = AlterCompositeAttributeType(
        target=composite_ref,
        attribute_name="state",
        new_data_type="public.new_state",
        old_type_prerequisites=(old_ref,),
        new_type_prerequisites=(new_ref,),
    )
    drop_attribute = AlterCompositeDropAttribute(
        target=composite_ref,
        attribute_name="state",
        type_prerequisites=(old_ref,),
    )

    added = order_deltas(DeltaSet.from_iterable((add_attribute, create_new_type))).deltas
    changed = order_deltas(
        DeltaSet.from_iterable((drop_old_enum, change_attribute_type, create_new_type))
    ).deltas
    dropped = order_deltas(DeltaSet.from_iterable((drop_old_enum, drop_attribute))).deltas

    _assert_precedes(added, create_new_type, add_attribute)
    _assert_precedes(changed, create_new_type, change_attribute_type, drop_old_enum)
    _assert_precedes(dropped, drop_attribute, drop_old_enum)


def test_enum_drop_waits_for_table_column_type_default_constraint_and_index_drops() -> None:
    enum_ref = _ref(ObjectKind.ENUM, "aaa_state")
    enum = EnumType(ref=enum_ref, labels=("ready",))
    drop_enum = DropEnum(target=enum_ref, enum=enum)
    table = _table("items", columns=("id",))
    column_ref = _column_ref(table.ref, "id")
    index = _index("items_id_idx", table.ref, "id")
    constraint = CheckConstraint(name="items_check", expression="true")
    dependents = (
        DropTable(target=table.ref, table=table),
        DropColumn(target=column_ref, column=Column(name="id", position=1, data_type="integer")),
        AlterColumnType(target=column_ref, new_data_type="text"),
        SetColumnDefault(target=column_ref, new_default=None),
        _drop_constraint(table, constraint),
        DropIndex(target=index.ref, index=index),
    )

    for dependent in dependents:
        ordered = order_deltas(DeltaSet.from_iterable((drop_enum, dependent))).deltas
        _assert_precedes(ordered, dependent, drop_enum)


def test_enum_create_and_drop_are_ordered_with_their_schema() -> None:
    schema_ref = _ref(ObjectKind.SCHEMA, "public")
    schema = Schema(ref=schema_ref)
    create_schema = CreateSchema(target=schema_ref, pg_schema=schema)
    drop_schema = DropSchema(target=schema_ref, pg_schema=schema)
    enum_ref = _ref(ObjectKind.ENUM, "state")
    enum = EnumType(ref=enum_ref, labels=("ready",))
    create_enum = CreateEnum(target=enum_ref, enum=enum)
    drop_enum = DropEnum(target=enum_ref, enum=enum)

    created = order_deltas(DeltaSet.from_iterable((create_enum, create_schema))).deltas
    dropped = order_deltas(DeltaSet.from_iterable((drop_schema, drop_enum))).deltas

    _assert_precedes(created, create_schema, create_enum)
    _assert_precedes(dropped, drop_enum, drop_schema)


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


def test_fk_in_create_table_payload_does_not_add_prerequisite_edges() -> None:
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

    assert ordered == (create_child, create_parent)


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
    add_fk = _add_constraint(table, fk)
    drop_table = DropTable(target=table.ref, table=table)

    created = order_deltas(DeltaSet.from_iterable((add_fk, create_table))).deltas
    assert created == (create_table, add_fk)
    assert order_deltas(DeltaSet.from_iterable((drop_table,))).deltas == (drop_table,)


def test_partition_child_waits_for_new_parent_table() -> None:
    parent = _table("z_parent")
    child_ref = _ref(ObjectKind.TABLE, "a_child")
    child = Table(
        ref=child_ref,
        partition_of=PartitionOf(parent_namespace="public", parent_name="z_parent"),
    )
    create_parent = CreateTable(target=parent.ref, table=parent)
    create_child = CreateTable(target=child.ref, table=child)

    ordered = order_deltas(DeltaSet.from_iterable((create_child, create_parent))).deltas

    _assert_precedes(ordered, create_parent, create_child)


def test_same_name_constraint_replacement_drops_before_add_even_when_sort_key_reverses() -> None:
    table = _table("items", columns=("id", "sku"))
    old_constraint = PrimaryKeyConstraint(name="items_key", columns=("id",))
    new_constraint = PrimaryKeyConstraint(name="items_key", columns=("sku",))
    drop_constraint = _drop_constraint(table, old_constraint)
    add_constraint = _add_constraint(table, new_constraint)

    assert add_constraint.sort_key < drop_constraint.sort_key
    ordered = order_deltas(DeltaSet.from_iterable((add_constraint, drop_constraint))).deltas

    assert ordered == (drop_constraint, add_constraint)


@pytest.mark.parametrize(
    "referenced_constraint",
    [
        PrimaryKeyConstraint(name="parent_pk", columns=("id", "tenant_id")),
        UniqueConstraint(name="parent_uq", columns=("id", "tenant_id")),
    ],
)
def test_fk_waits_for_referenced_pk_or_unique_added_in_same_migration(
    referenced_constraint: PrimaryKeyConstraint | UniqueConstraint,
) -> None:
    child = _table("a_child", columns=("tenant_id", "parent_id"))
    parent = _table("z_parent", columns=("id", "tenant_id"))
    fk = ForeignKeyConstraint(
        name="child_parent_fk",
        columns=("tenant_id", "parent_id"),
        ref_namespace="public",
        ref_table="z_parent",
        ref_columns=("tenant_id", "id"),
    )
    add_fk = _add_constraint(child, fk)
    add_referenced_constraint = _add_constraint(parent, referenced_constraint)

    ordered = order_deltas(DeltaSet.from_iterable((add_fk, add_referenced_constraint))).deltas

    _assert_precedes(ordered, add_referenced_constraint, add_fk)


def test_create_index_waits_for_drop_of_same_name_constraint_backing_index() -> None:
    table = _table("z_table", columns=("id",))
    primary_key = PrimaryKeyConstraint(name="a_index", columns=("id",))
    drop_constraint = _drop_constraint(table, primary_key)
    index = _index("a_index", table.ref, "id")
    create_index = CreateIndex(target=index.ref, index=index)

    ordered = order_deltas(DeltaSet.from_iterable((create_index, drop_constraint))).deltas

    _assert_precedes(ordered, drop_constraint, create_index)


def test_check_constraint_does_not_claim_same_name_standalone_index() -> None:
    table = _table("a_table", columns=("id",))
    check = CheckConstraint(name="z_index", expression="id > 0")
    add_check = _add_constraint(table, check)
    index = _index("z_index", table.ref, "id")
    drop_index = DropIndex(target=index.ref, index=index)

    ordered = order_deltas(DeltaSet.from_iterable((add_check, drop_index))).deltas

    assert ordered == (add_check, drop_index)


@pytest.mark.parametrize(
    "constraint",
    [
        PrimaryKeyConstraint(name="z_index", columns=("id",)),
        UniqueConstraint(name="z_index", columns=("id",)),
        ExclusionConstraint(
            name="z_index",
            index_method="gist",
            elements=(ExclusionElement(column_or_expr="id", operator="="),),
        ),
    ],
)
def test_add_index_backed_constraint_waits_for_drop_of_same_name_index(
    constraint: Constraint,
) -> None:
    table = _table("a_table", columns=("id",))
    add_constraint = _add_constraint(table, constraint)
    index = _index("z_index", table.ref, "id")
    drop_index = DropIndex(target=index.ref, index=index)

    ordered = order_deltas(DeltaSet.from_iterable((add_constraint, drop_index))).deltas

    _assert_precedes(ordered, drop_index, add_constraint)


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


def test_extension_schema_move_waits_for_new_schema_creation() -> None:
    schema_ref = _ref(ObjectKind.SCHEMA, "reporting")
    schema = Schema(ref=schema_ref)
    create_schema = CreateSchema(target=schema_ref, pg_schema=schema)
    extension_ref = _ref(ObjectKind.EXTENSION, "hstore")
    alter_extension = AlterExtension(target=extension_ref, new_schema="reporting")

    ordered = order_deltas(DeltaSet.from_iterable((alter_extension, create_schema))).deltas

    _assert_precedes(ordered, create_schema, alter_extension)


def test_unrelated_deltas_have_deterministic_sort_key_order() -> None:
    deltas = tuple(
        CreateTable(target=(table := _table(name)).ref, table=table)
        for name in ("zeta", "alpha", "mu")
    )

    ordered = order_deltas(DeltaSet.from_iterable(reversed(deltas))).deltas

    assert tuple(delta.target.qname.name for delta in ordered) == ("alpha", "mu", "zeta")


def test_mutually_referencing_new_tables_create_before_fk_constraints() -> None:
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
    create_a = CreateTable(target=a.ref, table=a)
    create_b = CreateTable(target=b.ref, table=b)
    add_a_fk = _add_constraint(a, a_fk)
    add_b_fk = _add_constraint(b, b_fk)

    ordered = order_deltas(DeltaSet.from_iterable((add_b_fk, create_b, add_a_fk, create_a))).deltas

    assert ordered == (create_a, create_b, add_a_fk, add_b_fk)
