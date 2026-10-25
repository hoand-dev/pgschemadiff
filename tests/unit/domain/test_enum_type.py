"""Unit tests for the immutable enum type model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName


def _enum_ref(name: str = "mood", namespace: str = "public") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace=namespace, name=name),
    )


@pytest.mark.unit
def test_enum_type_preserves_postgres_label_order_and_owner() -> None:
    enum = EnumType(ref=_enum_ref(), labels=("sad", "ok", "happy"), owner="app")

    assert enum.labels == ("sad", "ok", "happy")
    assert enum.owner == "app"


@pytest.mark.unit
def test_enum_type_rejects_non_enum_ref() -> None:
    ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="mood"),
    )

    with pytest.raises(ValidationError, match="must have kind ENUM"):
        EnumType(ref=ref, labels=("sad",))


@pytest.mark.unit
@pytest.mark.parametrize("labels", [("",), ("sad", "sad")])
def test_enum_type_rejects_empty_or_duplicate_labels(labels: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        EnumType(ref=_enum_ref(), labels=labels)


@pytest.mark.unit
def test_enum_type_allows_no_labels() -> None:
    assert EnumType(ref=_enum_ref()).labels == ()


@pytest.mark.unit
def test_enum_type_is_frozen() -> None:
    enum = EnumType(ref=_enum_ref(), labels=("sad", "happy"))

    with pytest.raises(ValidationError):
        enum.labels = ("happy", "sad")  # type: ignore[misc]


@pytest.mark.unit
def test_enum_type_json_round_trip() -> None:
    enum = EnumType(ref=_enum_ref(), labels=("sad", "happy"), owner="app")

    assert EnumType.model_validate_json(enum.model_dump_json()) == enum
