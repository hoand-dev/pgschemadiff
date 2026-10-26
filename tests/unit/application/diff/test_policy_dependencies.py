from __future__ import annotations

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.composite_type import CompositeAttribute
from pgschemadiff.domain.delta import (
    AddColumn,
    AddEnumValue,
    AlterCompositeAddAttribute,
    AlterCompositeDropAttribute,
    AlterPolicy,
    AlterTableAttrs,
    CreateEnum,
    CreateFunction,
    CreatePolicy,
    CreateTable,
    DeltaSet,
    DropColumn,
    DropEnum,
    DropPolicy,
    DropTable,
    RenameColumn,
    RenameTable,
    ReplacePolicy,
)
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.policy import Policy, PolicyCommand
from pgschemadiff.domain.table import Table


def _ref(kind: ObjectKind, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace="public", name=name))


def _column_ref(table_ref: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
        parent=table_ref,
    )


def _policy(name: str = "items_policy") -> Policy:
    table_ref = _ref(ObjectKind.TABLE, "items")
    return Policy(
        ref=ObjectRef(
            kind=ObjectKind.POLICY,
            qname=QualifiedName(namespace="public", name=name),
            parent=table_ref,
        ),
        table_ref=table_ref,
        command=PolicyCommand.SELECT,
        permissive=True,
        roles=("public",),
        using_expr="id > 0",
    )


def _function() -> Function:
    return Function(
        ref=ObjectRef(
            kind=ObjectKind.FUNCTION,
            qname=QualifiedName(namespace="public", name="policy_check"),
            arg_signature=("integer",),
        ),
        arguments=(FunctionArgument(data_type="integer"),),
        return_type="boolean",
        language="sql",
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        body="SELECT true",
        definition="CREATE OR REPLACE FUNCTION public.policy_check(integer)",
    )


def test_policy_create_follows_table_new_column_and_function_creation() -> None:
    policy = _policy()
    table = Table(ref=policy.table_ref, columns=(Column(name="id", position=1, data_type="int"),))
    create_table = CreateTable(target=table.ref, table=table)
    column = Column(name="scope_id", position=2, data_type="int")
    add_column = AddColumn(target=_column_ref(table.ref, column.name), column=column)
    function = _function()
    create_function = CreateFunction(target=function.ref, function=function)
    create_policy = CreatePolicy(target=policy.ref, policy=policy)

    ordered = order_deltas(
        DeltaSet.from_iterable((create_policy, add_column, create_table, create_function))
    ).deltas

    assert ordered.index(create_table) < ordered.index(create_policy)
    assert ordered.index(add_column) < ordered.index(create_policy)
    assert ordered.index(create_function) < ordered.index(create_policy)


def test_policy_changes_follow_table_columns_and_precede_column_drop() -> None:
    policy = _policy()
    renamed_column = RenameColumn(
        target=_column_ref(policy.table_ref, "old_id"), old_name="old_id", new_name="id"
    )
    drop_column = DropColumn(
        target=_column_ref(policy.table_ref, "obsolete"),
        column=Column(name="obsolete", position=2, data_type="int"),
    )
    changed_policy = AlterPolicy(
        target=policy.ref,
        policy=policy,
        new_using_expr="id >= 0",
    )

    ordered = order_deltas(
        DeltaSet.from_iterable((changed_policy, drop_column, renamed_column))
    ).deltas

    assert ordered.index(renamed_column) < ordered.index(changed_policy)
    assert ordered.index(changed_policy) < ordered.index(drop_column)


def test_table_rename_drops_old_policy_before_rename_and_creates_new_policy_after() -> None:
    old_policy = _policy("zzz_policy")
    old_table_ref = old_policy.table_ref
    new_table_ref = _ref(ObjectKind.TABLE, "renamed_items")
    new_policy_ref = ObjectRef(
        kind=ObjectKind.POLICY,
        qname=old_policy.ref.qname,
        parent=new_table_ref,
    )
    new_policy = old_policy.model_copy(update={"ref": new_policy_ref, "table_ref": new_table_ref})
    table_rename = RenameTable(
        target=old_table_ref,
        old_name=old_table_ref.qname,
        new_name=new_table_ref.qname,
    )
    policy_drop = DropPolicy(target=old_policy.ref, policy=old_policy)
    policy_create = CreatePolicy(target=new_policy.ref, policy=new_policy)

    ordered = order_deltas(
        DeltaSet.from_iterable((table_rename, policy_create, policy_drop))
    ).deltas

    assert ordered.index(policy_drop) < ordered.index(table_rename)
    assert ordered.index(table_rename) < ordered.index(policy_create)


def test_policy_expression_types_are_created_before_and_dropped_after_policies() -> None:
    create_type_ref = _ref(ObjectKind.ENUM, "zzz_status")
    create_type = EnumType(ref=create_type_ref, labels=("active",))
    create_type_delta = CreateEnum(target=create_type_ref, enum=create_type)
    label_type_ref = _ref(ObjectKind.ENUM, "yyy_status")
    label_addition = AddEnumValue(target=label_type_ref, label="active")
    drop_type_ref = _ref(ObjectKind.ENUM, "aaa_status")
    drop_type = EnumType(ref=drop_type_ref, labels=("inactive",))
    drop_type_delta = DropEnum(target=drop_type_ref, enum=drop_type)
    new_policy = _policy("new_policy").model_copy(
        update={"using_expr": "status::public.zzz_status IS NOT NULL"}
    )
    label_policy = _policy("label_policy").model_copy(
        update={"using_expr": "status::public.yyy_status = 'active'"}
    )
    old_policy = _policy("old_policy").model_copy(
        update={"using_expr": "status::public.aaa_status IS NOT NULL"}
    )
    policy_create = CreatePolicy(target=new_policy.ref, policy=new_policy)
    label_policy_create = CreatePolicy(target=label_policy.ref, policy=label_policy)
    policy_drop = DropPolicy(target=old_policy.ref, policy=old_policy)

    ordered = order_deltas(
        DeltaSet.from_iterable(
            (
                policy_create,
                drop_type_delta,
                policy_drop,
                create_type_delta,
                label_policy_create,
                label_addition,
            )
        )
    ).deltas

    assert ordered.index(create_type_delta) < ordered.index(policy_create)
    assert ordered.index(label_addition) < ordered.index(label_policy_create)
    assert ordered.index(policy_drop) < ordered.index(drop_type_delta)


def test_composite_attribute_addition_precedes_policy_using_new_attribute() -> None:
    composite_ref = _ref(ObjectKind.COMPOSITE_TYPE, "payload")
    add_attribute = AlterCompositeAddAttribute(
        target=composite_ref,
        attribute=CompositeAttribute(name="status", data_type="text"),
    )
    policy = _policy("payload_policy").model_copy(
        update={"using_expr": "(payload).status = 'active'"}
    )
    create_policy = CreatePolicy(target=policy.ref, policy=policy)

    ordered = order_deltas(DeltaSet.from_iterable((create_policy, add_attribute))).deltas

    assert ordered.index(add_attribute) < ordered.index(create_policy)


def test_policy_change_precedes_composite_attribute_drop() -> None:
    composite_ref = _ref(ObjectKind.COMPOSITE_TYPE, "accounts")
    drop_attribute = AlterCompositeDropAttribute(
        target=composite_ref,
        attribute_name="status",
    )
    old_policy = _policy("payload_policy").model_copy(
        update={"using_expr": "(payload).status = 'active'"}
    )
    policy_change = AlterPolicy(
        target=old_policy.ref,
        policy=old_policy,
        new_using_expr="true",
    )

    ordered = order_deltas(DeltaSet.from_iterable((drop_attribute, policy_change))).deltas

    assert ordered.index(policy_change) < ordered.index(drop_attribute)


def test_policy_create_precedes_rls_enable_and_drop_precedes_disable() -> None:
    policy = _policy()
    create_policy = CreatePolicy(target=policy.ref, policy=policy)
    enable = AlterTableAttrs(target=policy.table_ref, new_row_security=True)
    drop_policy = DropPolicy(target=policy.ref, policy=policy)
    disable = AlterTableAttrs(target=policy.table_ref, new_row_security=False)

    enabled_order = order_deltas(DeltaSet.from_iterable((enable, create_policy))).deltas
    disabled_order = order_deltas(DeltaSet.from_iterable((disable, drop_policy))).deltas

    assert enabled_order.index(create_policy) < enabled_order.index(enable)
    assert disabled_order.index(drop_policy) < disabled_order.index(disable)


def test_policy_drop_precedes_table_drop() -> None:
    policy = _policy()
    table = Table(ref=policy.table_ref, policies=(policy,))
    drop_policy = DropPolicy(target=policy.ref, policy=policy)
    drop_table = DropTable(target=table.ref, table=table)

    ordered = order_deltas(DeltaSet.from_iterable((drop_table, drop_policy))).deltas

    assert ordered.index(drop_policy) < ordered.index(drop_table)


def test_policy_replacement_stays_before_rls_enable() -> None:
    old = _policy()
    new = old.model_copy(update={"command": "UPDATE"})
    replace_policy = ReplacePolicy(target=old.ref, old_policy=old, new_policy=new)
    enable = AlterTableAttrs(target=old.table_ref, new_row_security=True)

    ordered = order_deltas(DeltaSet.from_iterable((enable, replace_policy))).deltas

    assert ordered.index(replace_policy) < ordered.index(enable)
