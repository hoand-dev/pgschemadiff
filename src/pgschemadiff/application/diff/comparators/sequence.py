"""Comparator for PostgreSQL sequences."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.sequence import (
    AlterSequenceOptions,
    AlterSequenceOwnedBy,
    AlterSequenceOwner,
    CreateSequence,
    DropSequence,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.sequence import Sequence


class SequenceComparator:
    """Compare sequence options, owner role, and owned column."""

    kind: ObjectKind = ObjectKind.SEQUENCE

    def compare(self, source: object | None, target: object | None) -> tuple[DeltaBase, ...]:
        src = cast("Sequence | None", source)
        tgt = cast("Sequence | None", target)

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            if tgt.owner is None:
                raise DiffError("Sequence owner is unresolved.")
            result: list[DeltaBase] = [CreateSequence(target=tgt.ref, sequence=tgt)]
            if tgt.owned_by is not None:
                result.append(AlterSequenceOwnedBy(target=tgt.ref, new_owned_by=tgt.owned_by))
            return tuple(result)
        if tgt is None:
            return (DropSequence(target=src.ref, sequence=src),)

        result = []
        if any(
            (
                src.data_type != tgt.data_type,
                src.start != tgt.start,
                src.increment != tgt.increment,
                src.min_value != tgt.min_value,
                src.max_value != tgt.max_value,
                src.cache != tgt.cache,
                src.cycle != tgt.cycle,
            )
        ):
            result.append(
                AlterSequenceOptions(
                    target=src.ref,
                    new_data_type=tgt.data_type if src.data_type != tgt.data_type else None,
                    new_start=tgt.start if src.start != tgt.start else None,
                    new_increment=tgt.increment if src.increment != tgt.increment else None,
                    new_min_value=tgt.min_value if src.min_value != tgt.min_value else None,
                    new_max_value=tgt.max_value if src.max_value != tgt.max_value else None,
                    new_cache=tgt.cache if src.cache != tgt.cache else None,
                    new_cycle=tgt.cycle if src.cycle != tgt.cycle else None,
                )
            )

        if src.owner != tgt.owner:
            if tgt.owner is None:
                raise DiffError("Sequence owner cannot be changed to an unresolved owner.")
            result.append(AlterSequenceOwner(target=src.ref, new_owner=tgt.owner))
        if src.owned_by != tgt.owned_by:
            result.append(
                AlterSequenceOwnedBy(
                    target=src.ref,
                    old_owned_by=src.owned_by,
                    new_owned_by=tgt.owned_by,
                )
            )
        return tuple(result)


assert isinstance(SequenceComparator(), Comparator), "SequenceComparator must satisfy Comparator"
