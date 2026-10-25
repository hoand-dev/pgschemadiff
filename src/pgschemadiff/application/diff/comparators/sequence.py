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
from pgschemadiff.domain.identity import ObjectKind, ObjectRef
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.sequence import Sequence


class SequenceComparator:
    """Compare sequence options, owner role, and owned column."""

    kind: ObjectKind = ObjectKind.SEQUENCE

    def __init__(
        self,
        *,
        source_table_owners: Mapping[ObjectRef, str | None] | None = None,
        target_table_owners: Mapping[ObjectRef, str | None] | None = None,
    ) -> None:
        """Accept table-owner snapshots for ownership-following sequences."""
        self._source_table_owners = source_table_owners or {}
        self._target_table_owners = target_table_owners or {}

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
            if src.owned_by is not None and src.owned_by == tgt.owned_by:
                table_ref = src.owned_by.parent
                source_table_owner = (
                    self._source_table_owners.get(table_ref) if table_ref is not None else None
                )
                target_table_owner = (
                    self._target_table_owners.get(table_ref) if table_ref is not None else None
                )
                if (
                    table_ref is None
                    or source_table_owner is None
                    or target_table_owner is None
                    or src.owner != source_table_owner
                    or tgt.owner != target_table_owner
                    or source_table_owner == target_table_owner
                ):
                    raise DiffError(
                        "Sequence and owning table owners have inconsistent catalog state: "
                        f"sequence {src.ref.qname.fqn} owner {src.owner!r} -> {tgt.owner!r}, "
                        f"table owner {source_table_owner!r} -> {target_table_owner!r}."
                    )
            else:
                result.append(
                    AlterSequenceOwner(
                        target=src.ref,
                        new_owner=tgt.owner,
                        old_owned_by=src.owned_by,
                    )
                )
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
