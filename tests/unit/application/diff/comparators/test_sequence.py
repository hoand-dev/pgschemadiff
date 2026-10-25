from __future__ import annotations

from typing import Literal

import pytest

from pgschemadiff.application.diff import DiffEngine
from pgschemadiff.application.diff.comparators import SequenceComparator
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta.sequence import (
    AlterSequenceOptions,
    AlterSequenceOwnedBy,
    AlterSequenceOwner,
    CreateSequence,
    DropSequence,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.shared.errors import DiffError


def _ref(kind: ObjectKind, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace="public", name=name))


def _sequence(
    *,
    data_type: Literal["smallint", "integer", "bigint"] = "bigint",
    start: int = 1,
    increment: int = 1,
    min_value: int = 1,
    max_value: int = 999,
    cache: int = 1,
    cycle: bool = False,
    owner: str | None = "app_owner",
    owned_by: ObjectRef | None = None,
) -> Sequence:
    return Sequence(
        ref=_ref(ObjectKind.SEQUENCE, "ticket_seq"),
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
def test_sequence_comparator_emits_create_and_drop() -> None:
    sequence = _sequence()
    comparator = SequenceComparator()

    assert comparator.compare(None, None) == ()
    assert comparator.compare(None, sequence) == (
        CreateSequence(target=sequence.ref, sequence=sequence),
    )
    assert comparator.compare(sequence, None) == (
        DropSequence(target=sequence.ref, sequence=sequence),
    )


@pytest.mark.unit
def test_sequence_comparator_emits_only_changed_options() -> None:
    source = _sequence()
    target = _sequence(
        data_type="integer",
        start=3,
        increment=2,
        min_value=2,
        max_value=500,
        cache=4,
        cycle=True,
    )

    (delta,) = SequenceComparator().compare(source, target)

    assert isinstance(delta, AlterSequenceOptions)
    assert delta.model_dump(exclude={"op", "kind", "target"}, exclude_none=True) == {
        "new_data_type": "integer",
        "new_start": 3,
        "new_increment": 2,
        "new_min_value": 2,
        "new_max_value": 500,
        "new_cache": 4,
        "new_cycle": True,
    }


@pytest.mark.unit
def test_sequence_comparator_separates_owner_and_owned_by_changes() -> None:
    source = _sequence()
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    column_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=table_ref,
    )
    target = _sequence(owner="new_owner", owned_by=column_ref)

    deltas = SequenceComparator().compare(source, target)

    assert len(deltas) == 2
    assert isinstance(deltas[0], AlterSequenceOwner)
    assert deltas[0].new_owner == "new_owner"
    assert deltas[1] == AlterSequenceOwnedBy(target=source.ref, new_owned_by=column_ref)


@pytest.mark.unit
def test_column_owned_creation_emits_create_then_owned_by_and_rejects_unknown_owner() -> None:
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    column_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=table_ref,
    )
    target = _sequence(owned_by=column_ref)

    deltas = SequenceComparator().compare(None, target)

    assert isinstance(deltas[0], CreateSequence)
    assert isinstance(deltas[1], AlterSequenceOwnedBy)
    assert deltas[1].new_owned_by == column_ref
    with pytest.raises(DiffError, match=r"owner.*unresolved"):
        SequenceComparator().compare(_sequence(), _sequence(owner=None))


@pytest.mark.unit
def test_diff_engine_fetches_sequences_through_public_comparator_registry() -> None:
    sequence = _sequence()
    schema = Schema(
        ref=_ref(ObjectKind.SCHEMA, "public"),
        sequences=(sequence,),
    )
    target = Database(name="target", schemas=(schema,))
    source = Database(name="source")

    result = DiffEngine((SequenceComparator(),)).diff(source, target)

    assert len(result.deltas) == 1
    assert isinstance(result.deltas[0], CreateSequence)
