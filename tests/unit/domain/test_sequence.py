from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence


def _ref(kind: ObjectKind, name: str, namespace: str = "public") -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace=namespace, name=name))


def _sequence(
    *,
    ref: ObjectRef | None = None,
    data_type: Literal["smallint", "integer", "bigint"] = "bigint",
    start: int = 3,
    increment: int = 2,
    min_value: int = 1,
    max_value: int = 99,
    cache: int = 4,
    cycle: bool = True,
    owner: str | None = "app_owner",
    owned_by: ObjectRef | None = None,
) -> Sequence:
    return Sequence(
        ref=ref or _ref(ObjectKind.SEQUENCE, "ticket_seq"),
        data_type=data_type,
        start=start,
        increment=increment,
        min_value=min_value,
        max_value=max_value,
        cache=cache,
        cycle=cycle,
        owner=owner,
        owned_by=owned_by,
    )


@pytest.mark.unit
def test_sequence_preserves_options_owner_and_column_ownership() -> None:
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    column_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=table_ref,
    )

    sequence = _sequence(owned_by=column_ref)

    assert sequence.data_type == "bigint"
    assert sequence.start == 3
    assert sequence.increment == 2
    assert sequence.min_value == 1
    assert sequence.max_value == 99
    assert sequence.cache == 4
    assert sequence.cycle is True
    assert sequence.owner == "app_owner"
    assert sequence.owned_by == column_ref
    assert Sequence.model_validate_json(sequence.model_dump_json()) == sequence
    with pytest.raises(ValidationError):
        sequence.start = 4  # type: ignore[misc]


@pytest.mark.unit
def test_sequence_rejects_wrong_ref_kind_and_non_column_owner() -> None:
    with pytest.raises(ValidationError, match="must have kind SEQUENCE"):
        _sequence(ref=_ref(ObjectKind.TABLE, "tickets"))

    with pytest.raises(ValidationError, match="owned_by must have kind COLUMN"):
        _sequence(owned_by=_ref(ObjectKind.TABLE, "tickets"))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"increment": 0}, "increment must not be zero"),
        ({"min_value": 10, "max_value": 9}, "min_value must not exceed max_value"),
        ({"start": 100}, "start must be between min_value and max_value"),
        ({"cache": 0}, "cache must be at least 1"),
    ],
)
def test_sequence_rejects_invalid_options(changes: dict[str, int], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Sequence.model_validate({**_sequence().model_dump(), **changes})


@pytest.mark.unit
def test_column_carries_sequence_prerequisites_as_structured_refs() -> None:
    sequence_ref = _ref(ObjectKind.SEQUENCE, "ticket_seq")

    column = Column(
        name="id",
        position=1,
        data_type="bigint",
        sequence_prerequisites=(sequence_ref,),
    )

    assert column.sequence_prerequisites == (sequence_ref,)
    with pytest.raises(ValidationError, match="must have kind SEQUENCE"):
        Column(
            name="bad",
            position=1,
            data_type="bigint",
            sequence_prerequisites=(_ref(ObjectKind.TABLE, "tickets"),),
        )


@pytest.mark.unit
def test_schema_and_database_expose_sequences_and_reject_duplicate_refs() -> None:
    sequence = _sequence()
    schema_ref = _ref(ObjectKind.SCHEMA, "public")
    schema = Schema(ref=schema_ref, sequences=(sequence,))

    database = Database(name="source", schemas=(schema,))

    assert database.schemas[0].sequences == (sequence,)
    assert database.all_sequences() == (sequence,)
    with pytest.raises(ValidationError, match="Duplicate sequence ref"):
        Schema(ref=schema_ref, sequences=(sequence, sequence))
    with pytest.raises(ValidationError, match="belongs to namespace"):
        Schema(ref=schema_ref, sequences=(_sequence(ref=_ref(ObjectKind.SEQUENCE, "s", "other")),))
