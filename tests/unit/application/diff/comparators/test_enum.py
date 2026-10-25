import pytest

from pgschemadiff.application.diff.comparators.enum import EnumComparator
from pgschemadiff.application.diff.engine import DiffEngine
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import (
    AddEnumValue,
    AlterEnumAttrs,
    CreateEnum,
    DeltaSet,
    DropEnum,
    ReplaceEnumLabels,
)
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.shared.errors import DiffError, RiskGateError


def _enum(
    labels: tuple[str, ...] = (),
    *,
    owner: str | None = "app_owner",
    name: str = "state",
    namespace: str = "public",
) -> EnumType:
    ref = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace=namespace, name=name),
    )
    return EnumType(ref=ref, labels=labels, owner=owner)


def test_enum_create_and_drop() -> None:
    enum = _enum(("ready", "done"))
    comparator = EnumComparator()

    assert comparator.compare(None, enum) == (CreateEnum(target=enum.ref, enum=enum),)
    assert comparator.compare(enum, None) == (DropEnum(target=enum.ref, enum=enum),)
    assert comparator.compare(enum, enum) == ()


def test_enum_additions_follow_target_order_and_nearest_existing_anchor() -> None:
    source = _enum(("a", "c"))
    target = _enum(("a", "b", "d", "c", "e", "f"))

    deltas = EnumComparator().compare(source, target)

    assert deltas == (
        AddEnumValue(target=source.ref, label="b", before="c"),
        AddEnumValue(target=source.ref, label="d", before="c"),
        AddEnumValue(target=source.ref, label="e", after="c"),
        AddEnumValue(target=source.ref, label="f", after="e"),
    )


@pytest.mark.parametrize(
    ("source_labels", "target_labels", "expected"),
    [
        (("old",), ("new",), ReplaceEnumLabels),
        (("a", "b", "c"), ("a", "c"), ReplaceEnumLabels),
        (("a", "b"), ("b", "a"), ReplaceEnumLabels),
        (("a",), ("a", "b"), AddEnumValue),
    ],
    ids=("rename", "remove", "reorder", "append"),
)
def test_enum_label_change_uses_safe_additions_or_blocked_replacement(
    source_labels: tuple[str, ...],
    target_labels: tuple[str, ...],
    expected: type[AddEnumValue] | type[ReplaceEnumLabels],
) -> None:
    result = EnumComparator().compare(_enum(source_labels), _enum(target_labels))

    assert len(result) == 1
    assert isinstance(result[0], expected)


def test_empty_enum_can_be_created_and_existing_empty_enum_can_gain_labels() -> None:
    empty = _enum(())
    comparator = EnumComparator()

    assert comparator.compare(None, empty) == (CreateEnum(target=empty.ref, enum=empty),)
    assert comparator.compare(empty, _enum(("first", "second"))) == (
        AddEnumValue(target=empty.ref, label="first"),
        AddEnumValue(target=empty.ref, label="second", after="first"),
    )


def test_enum_owner_change_is_a_separate_delta() -> None:
    source = _enum(("ready",), owner="app_owner")
    target = _enum(("ready",), owner="other_owner")

    assert EnumComparator().compare(source, target) == (
        AlterEnumAttrs(target=source.ref, new_owner="other_owner"),
    )


def test_enum_fetcher_and_comparator_are_registered_with_engine() -> None:
    source_enum = _enum(("ready",))
    target_enum = _enum(("ready", "done"))
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    source = Database(name="source", schemas=(Schema(ref=schema_ref, enums=(source_enum,)),))
    target = Database(name="target", schemas=(Schema(ref=schema_ref, enums=(target_enum,)),))

    result = DiffEngine((EnumComparator(),)).diff(source, target)

    assert result.deltas == (AddEnumValue(target=source_enum.ref, label="done", after="ready"),)


def test_removed_enum_label_is_rejected_by_risk_gate_before_emission() -> None:
    delta = EnumComparator().compare(_enum(("ready", "done")), _enum(("ready",)))[0]

    assert isinstance(delta, ReplaceEnumLabels)
    with pytest.raises(RiskGateError, match=r"level=blocked.*no safe in-place DDL"):
        generate_migration(DeltaSet.from_iterable((delta,)))


def test_enum_comparator_rejects_unrepresentable_owner_removal() -> None:
    with pytest.raises(DiffError, match="owner"):
        EnumComparator().compare(
            _enum(("ready",), owner="app_owner"), _enum(("ready",), owner=None)
        )
