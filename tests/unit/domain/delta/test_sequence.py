from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.delta import DeltaSet
from pgschemadiff.domain.delta.sequence import (
    AlterSequenceOptions,
    AlterSequenceOwnedBy,
    CreateSequence,
    DropSequence,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.sequence import Sequence


def _ref(kind: ObjectKind, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace="public", name=name))


def _sequence() -> Sequence:
    return Sequence(
        ref=_ref(ObjectKind.SEQUENCE, "ticket_seq"),
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=999,
        cache=1,
        cycle=False,
        owner="app_owner",
    )


@pytest.mark.unit
def test_sequence_create_and_drop_deltas_validate_payload_identity() -> None:
    sequence = _sequence()

    create = CreateSequence(target=sequence.ref, sequence=sequence)
    drop = DropSequence(target=sequence.ref, sequence=sequence)

    assert create.sequence == sequence
    assert drop.sequence == sequence
    with pytest.raises(ValidationError, match=r"must equal sequence\.ref"):
        CreateSequence(target=_ref(ObjectKind.SEQUENCE, "other_seq"), sequence=sequence)


@pytest.mark.unit
def test_sequence_alter_deltas_validate_kind_and_nonempty_options() -> None:
    sequence_ref = _ref(ObjectKind.SEQUENCE, "ticket_seq")

    change = AlterSequenceOptions(target=sequence_ref, new_increment=2)
    assert change.new_increment == 2
    with pytest.raises(ValidationError, match="at least one option"):
        AlterSequenceOptions(target=sequence_ref)
    with pytest.raises(ValidationError, match="must not be zero"):
        AlterSequenceOptions(target=sequence_ref, new_increment=0)
    with pytest.raises(ValidationError, match="must have kind SEQUENCE"):
        AlterSequenceOptions(target=_ref(ObjectKind.TABLE, "tickets"), new_increment=2)


@pytest.mark.unit
def test_owned_by_delta_accepts_column_or_none_and_round_trips_union() -> None:
    sequence = _sequence()
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    column_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=table_ref,
    )
    create = CreateSequence(target=sequence.ref, sequence=sequence)
    owned_by = AlterSequenceOwnedBy(target=sequence.ref, new_owned_by=column_ref)

    assert AlterSequenceOwnedBy(target=sequence.ref, new_owned_by=None).new_owned_by is None
    with pytest.raises(ValidationError, match="must have kind COLUMN"):
        AlterSequenceOwnedBy(target=sequence.ref, new_owned_by=table_ref)
    assert DeltaSet.model_validate_json(
        DeltaSet(deltas=(create, owned_by)).model_dump_json()
    ) == DeltaSet(deltas=(create, owned_by))
