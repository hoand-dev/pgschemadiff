import pytest
from pydantic import ValidationError

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


def _enum(labels: tuple[str, ...] = ()) -> EnumType:
    ref = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace="public", name="state"),
    )
    return EnumType(ref=ref, labels=labels, owner="app_owner")


@pytest.mark.parametrize(
    ("before", "after"),
    [(None, None), ("done", None), (None, "ready")],
)
def test_add_enum_value_accepts_zero_or_one_anchor(
    before: str | None,
    after: str | None,
) -> None:
    enum = _enum()

    delta = AddEnumValue(target=enum.ref, label="review", before=before, after=after)

    assert (delta.before, delta.after) == (before, after)


def test_add_enum_value_rejects_two_anchors() -> None:
    enum = _enum()

    with pytest.raises(ValidationError, match="not both"):
        AddEnumValue(target=enum.ref, label="review", before="done", after="ready")


def test_enum_deltas_round_trip_through_deltas_json_union() -> None:
    enum = _enum(("ready", "done"))
    deltas = (
        CreateEnum(target=enum.ref, enum=enum),
        DropEnum(target=enum.ref, enum=enum),
        AddEnumValue(target=enum.ref, label="review", before="done"),
        AlterEnumAttrs(target=enum.ref, new_owner="other_owner"),
        ReplaceEnumLabels(
            target=enum.ref,
            old_labels=("ready", "done"),
            new_labels=("ready", "finished"),
        ),
    )

    restored = DeltaSet.model_validate_json(DeltaSet(deltas=deltas).model_dump_json())

    assert restored.deltas == deltas
    assert tuple(type(delta) for delta in restored) == tuple(type(delta) for delta in deltas)
