"""Tests for delta ignore rules."""

from __future__ import annotations

import pytest

from pgschemadiff.application.diff import IgnoreRules
from pgschemadiff.domain.delta import (
    AlterColumnType,
    AlterExtension,
    AlterTableAttrs,
    DeltaSet,
    RenameColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName


def _table_ref(name: str = "users") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name=name),
    )


def _column_ref(table: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table.qname.namespace, name=name),
        parent=table,
    )


def test_object_rule_filters_exact_target_and_preserves_other_deltas() -> None:
    table = _table_ref()
    table_delta = AlterTableAttrs(target=table, new_owner="app_owner")
    first_column_delta = SetColumnDefault(
        target=_column_ref(table, "status"), new_default="'active'"
    )
    second_column_delta = SetColumnDefault(
        target=_column_ref(table, "created_at"), new_default="now()"
    )
    deltas = DeltaSet.from_iterable((table_delta, first_column_delta, second_column_delta))

    filtered = IgnoreRules(objects=frozenset({table})).apply(deltas)

    assert tuple(filtered) == (first_column_delta, second_column_delta)
    assert tuple(deltas) == (table_delta, first_column_delta, second_column_delta)


def test_attribute_rule_removes_only_named_bundled_table_attribute() -> None:
    table = _table_ref()
    delta = AlterTableAttrs(target=table, new_owner="app_owner", new_comment="users")
    deltas = DeltaSet.from_iterable((delta,))

    filtered = IgnoreRules(attributes=frozenset({(table, "owner")})).apply(deltas)

    assert len(filtered) == 1
    filtered_delta = filtered.deltas[0]
    assert isinstance(filtered_delta, AlterTableAttrs)
    assert filtered_delta.new_owner is None
    assert filtered_delta.new_comment == "users"
    assert delta.new_owner == "app_owner"


def test_attribute_rule_filters_atomic_column_delta_only() -> None:
    table = _table_ref()
    column = _column_ref(table, "status")
    default_delta = SetColumnDefault(target=column, new_default="'active'")
    nullability_delta = SetColumnNullability(target=column, nullable=False)
    deltas = DeltaSet.from_iterable((default_delta, nullability_delta))

    filtered = IgnoreRules(attributes=frozenset({(column, "default")})).apply(deltas)

    assert tuple(filtered) == (nullability_delta,)


def test_attribute_rule_filters_column_type_and_name_changes() -> None:
    table = _table_ref()
    column = _column_ref(table, "status")
    type_delta = AlterColumnType(target=column, new_data_type="text")
    rename_delta = RenameColumn(target=column, old_name="status", new_name="state")

    filtered = IgnoreRules(attributes=frozenset({(column, "type"), (column, "name")})).apply(
        DeltaSet.from_iterable((type_delta, rename_delta))
    )

    assert filtered.is_empty()


def test_attribute_rule_strips_extension_field_and_preserves_remaining_change() -> None:
    extension = ObjectRef(
        kind=ObjectKind.EXTENSION,
        qname=QualifiedName(namespace="public", name="postgis"),
    )
    delta = AlterExtension(target=extension, new_version="2.0", new_schema="extensions")

    filtered = IgnoreRules(attributes=frozenset({(extension, "version")})).apply(
        DeltaSet.from_iterable((delta,))
    )

    assert len(filtered) == 1
    filtered_delta = filtered.deltas[0]
    assert isinstance(filtered_delta, AlterExtension)
    assert filtered_delta.new_version is None
    assert filtered_delta.new_schema == "extensions"


def test_attribute_rule_removes_delta_when_all_bundled_changes_are_ignored() -> None:
    table = _table_ref()
    delta = AlterTableAttrs(target=table, new_owner="app_owner")

    filtered = IgnoreRules(attributes=frozenset({(table, "owner")})).apply(
        DeltaSet.from_iterable((delta,))
    )

    assert filtered.is_empty()


def test_unknown_attribute_rule_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported ignored attribute"):
        IgnoreRules(attributes=frozenset({(_table_ref(), "typo")}))


def test_unmatched_rules_leave_delta_order_unchanged() -> None:
    table = _table_ref()
    delta = AlterTableAttrs(target=table, new_comment="users")
    deltas = DeltaSet.from_iterable((delta,))

    filtered = IgnoreRules(attributes=frozenset({(_table_ref("orders"), "comment")})).apply(deltas)

    assert tuple(filtered) == (delta,)
