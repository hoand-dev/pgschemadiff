"""Unit tests for the immutable composite type domain model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName


def _composite_ref(name: str = "address", namespace: str = "public") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COMPOSITE_TYPE,
        qname=QualifiedName(namespace=namespace, name=name),
    )


@pytest.mark.unit
def test_composite_type_preserves_attribute_order_prerequisites_and_owner() -> None:
    prerequisite = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace="types", name="mood"),
    )
    composite = CompositeType(
        ref=_composite_ref(),
        attributes=(
            CompositeAttribute(name="street", data_type="text"),
            CompositeAttribute(name="state", data_type="types.mood", collation='"C"'),
        ),
        type_prerequisites=(prerequisite,),
        owner="app",
    )

    assert tuple(attribute.name for attribute in composite.attributes) == ("street", "state")
    assert composite.attributes[1].data_type == "types.mood"
    assert composite.attributes[1].collation == '"C"'
    assert composite.type_prerequisites == (prerequisite,)
    assert composite.owner == "app"


@pytest.mark.unit
def test_composite_type_rejects_non_composite_ref() -> None:
    ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="address"),
    )

    with pytest.raises(ValidationError, match="must have kind COMPOSITE_TYPE"):
        CompositeType(ref=ref)


@pytest.mark.unit
def test_composite_type_rejects_duplicate_attribute_names() -> None:
    with pytest.raises(ValidationError, match="Attribute names must be unique"):
        CompositeType(
            ref=_composite_ref(),
            attributes=(
                CompositeAttribute(name="value", data_type="integer"),
                CompositeAttribute(name="value", data_type="text"),
            ),
        )


@pytest.mark.unit
def test_composite_type_rejects_duplicate_type_prerequisites() -> None:
    prerequisite = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace="types", name="mood"),
    )

    with pytest.raises(ValidationError, match="Duplicate type prerequisite"):
        CompositeType(
            ref=_composite_ref(),
            type_prerequisites=(prerequisite, prerequisite),
        )


@pytest.mark.unit
def test_composite_type_is_frozen_and_json_round_trips() -> None:
    composite = CompositeType(
        ref=_composite_ref(),
        attributes=(CompositeAttribute(name="id", data_type="integer"),),
    )

    with pytest.raises(ValidationError):
        composite.owner = "other"  # type: ignore[misc]
    assert CompositeType.model_validate_json(composite.model_dump_json()) == composite
