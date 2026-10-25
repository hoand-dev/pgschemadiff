from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.composite_type import CompositeTypeComparator
from pgschemadiff.application.diff.engine import DiffEngine
from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import (
    AlterCompositeAddAttribute,
    AlterCompositeAttributeType,
    AlterCompositeDropAttribute,
    AlterCompositeTypeAttrs,
    CreateCompositeType,
    DropCompositeType,
    ReplaceCompositeType,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.shared.errors import DiffError


def _type(
    attributes: tuple[CompositeAttribute, ...] = (),
    *,
    owner: str | None = "app_owner",
    prerequisites: tuple[ObjectRef, ...] = (),
    name: str = "address",
    namespace: str = "public",
) -> CompositeType:
    ref = ObjectRef(
        kind=ObjectKind.COMPOSITE_TYPE,
        qname=QualifiedName(namespace=namespace, name=name),
    )
    return CompositeType(
        ref=ref,
        attributes=attributes,
        type_prerequisites=prerequisites,
        owner=owner,
    )


def _attr(name: str, data_type: str = "text", collation: str | None = None) -> CompositeAttribute:
    return CompositeAttribute(name=name, data_type=data_type, collation=collation)


def test_composite_type_create_drop_and_noop() -> None:
    composite = _type((_attr("street"),))
    comparator = CompositeTypeComparator()

    assert comparator.compare(None, composite) == (
        CreateCompositeType(target=composite.ref, composite=composite),
    )
    assert comparator.compare(composite, None) == (
        DropCompositeType(target=composite.ref, composite=composite),
    )
    assert comparator.compare(composite, composite) == ()


def test_composite_type_appended_attributes_carry_type_prerequisites() -> None:
    enum_ref = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace="types", name="country"),
    )
    source = _type((_attr("street"),))
    target = _type((_attr("street"), _attr("country", "types.country")), prerequisites=(enum_ref,))

    assert CompositeTypeComparator().compare(source, target) == (
        AlterCompositeAddAttribute(
            target=source.ref,
            attribute=_attr("country", "types.country"),
            type_prerequisites=(enum_ref,),
        ),
    )


def test_composite_type_removed_attributes_carry_old_prerequisites() -> None:
    enum_ref = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace="types", name="country"),
    )
    source = _type((_attr("street"), _attr("country", "types.country")), prerequisites=(enum_ref,))
    target = _type((_attr("street"),))

    assert CompositeTypeComparator().compare(source, target) == (
        AlterCompositeDropAttribute(
            target=source.ref,
            attribute_name="country",
            type_prerequisites=(enum_ref,),
        ),
    )


@pytest.mark.parametrize(
    ("source_attribute", "target_attribute"),
    [
        (_attr("value", "integer"), _attr("value", "text")),
        (_attr("value", "text"), _attr("value", "text", '"C"')),
    ],
    ids=("type", "collation"),
)
def test_composite_type_attribute_type_or_collation_change(
    source_attribute: CompositeAttribute,
    target_attribute: CompositeAttribute,
) -> None:
    enum_ref = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace="types", name="label"),
    )
    source = _type((source_attribute,))
    target = _type((target_attribute,), prerequisites=(enum_ref,))

    assert CompositeTypeComparator().compare(source, target) == (
        AlterCompositeAttributeType(
            target=source.ref,
            attribute_name="value",
            new_data_type=target_attribute.data_type,
            new_collation=target_attribute.collation,
            old_type_prerequisites=(),
            new_type_prerequisites=(enum_ref,),
        ),
    )


@pytest.mark.parametrize(
    "target_attributes",
    [
        (_attr("first"), _attr("third"), _attr("second")),
        (_attr("first"), _attr("inserted"), _attr("second")),
    ],
    ids=("reorder", "middle-insertion"),
)
def test_composite_type_reorder_or_middle_insertion_is_blocked_replacement(
    target_attributes: tuple[CompositeAttribute, ...],
) -> None:
    source = _type((_attr("first"), _attr("second"), _attr("third")))
    if target_attributes[0].name == "first" and target_attributes[1].name == "inserted":
        source = _type((_attr("first"), _attr("second")))
    target = _type(target_attributes)

    assert CompositeTypeComparator().compare(source, target) == (
        ReplaceCompositeType(
            target=source.ref,
            old_attributes=source.attributes,
            new_attributes=target.attributes,
        ),
    )


def test_composite_attribute_rename_is_drop_and_append_not_inferred() -> None:
    source = _type((_attr("old_name"), _attr("kept")))
    target = _type((_attr("kept"), _attr("new_name")))

    assert CompositeTypeComparator().compare(source, target) == (
        AlterCompositeDropAttribute(target=source.ref, attribute_name="old_name"),
        AlterCompositeAddAttribute(target=source.ref, attribute=_attr("new_name")),
    )


def test_composite_owner_change_is_separate_and_requires_resolved_owner() -> None:
    source = _type((_attr("street"),))
    target = _type((_attr("street"),), owner="other_owner")

    assert CompositeTypeComparator().compare(source, target) == (
        AlterCompositeTypeAttrs(target=source.ref, new_owner="other_owner"),
    )
    with pytest.raises(DiffError, match="owner"):
        CompositeTypeComparator().compare(source, _type(source.attributes, owner=None))


def test_composite_type_comparator_is_registered_with_engine() -> None:
    source_type = _type((_attr("street"),))
    target_type = _type((_attr("street"), _attr("city")))
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    source = Database(
        name="source",
        schemas=(Schema(ref=schema_ref, composite_types=(source_type,)),),
    )
    target = Database(
        name="target",
        schemas=(Schema(ref=schema_ref, composite_types=(target_type,)),),
    )

    result = DiffEngine((CompositeTypeComparator(),)).diff(source, target)

    assert result.deltas == (
        AlterCompositeAddAttribute(target=source_type.ref, attribute=_attr("city")),
    )
