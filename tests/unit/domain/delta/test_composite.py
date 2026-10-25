from __future__ import annotations

from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
from pgschemadiff.domain.delta import (
    AlterCompositeAddAttribute,
    AlterCompositeAttributeType,
    AlterCompositeDropAttribute,
    AlterCompositeTypeAttrs,
    CreateCompositeType,
    DeltaSet,
    DropCompositeType,
    ReplaceCompositeType,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName


def _composite() -> CompositeType:
    ref = ObjectRef(
        kind=ObjectKind.COMPOSITE_TYPE,
        qname=QualifiedName(namespace="public", name="address"),
    )
    return CompositeType(
        ref=ref,
        attributes=(CompositeAttribute(name="street", data_type="text"),),
        owner="app",
    )


def test_composite_deltas_round_trip_through_delta_set_json() -> None:
    composite = _composite()
    deltas = (
        CreateCompositeType(target=composite.ref, composite=composite),
        DropCompositeType(target=composite.ref, composite=composite),
        AlterCompositeAddAttribute(
            target=composite.ref,
            attribute=CompositeAttribute(name="city", data_type="text"),
        ),
        AlterCompositeDropAttribute(target=composite.ref, attribute_name="street"),
        AlterCompositeAttributeType(
            target=composite.ref,
            attribute_name="street",
            new_data_type="varchar",
            new_collation='"C"',
        ),
        AlterCompositeTypeAttrs(target=composite.ref, new_owner="other"),
        ReplaceCompositeType(
            target=composite.ref,
            old_attributes=composite.attributes,
            new_attributes=(CompositeAttribute(name="city", data_type="text"),),
        ),
    )

    restored = DeltaSet.model_validate_json(DeltaSet(deltas=deltas).model_dump_json())

    assert restored.deltas == deltas
    assert tuple(type(delta) for delta in restored) == tuple(type(delta) for delta in deltas)
