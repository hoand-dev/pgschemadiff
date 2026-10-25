"""Comparator for PostgreSQL enum types."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.enum import (
    AddEnumValue,
    AlterEnumAttrs,
    CreateEnum,
    DropEnum,
    ReplaceEnumLabels,
)
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.enum_type import EnumType


class EnumComparator:
    """Compare enum existence, ordered labels, and owner."""

    kind: ObjectKind = ObjectKind.ENUM

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[CreateEnum | DropEnum | AddEnumValue | AlterEnumAttrs | ReplaceEnumLabels, ...]:
        """Emit create/drop, ordered additions, or a blocked replacement delta."""
        src = cast("EnumType | None", source)
        tgt = cast("EnumType | None", target)

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateEnum(target=tgt.ref, enum=tgt),)
        if tgt is None:
            return (DropEnum(target=src.ref, enum=src),)

        result: list[AddEnumValue | AlterEnumAttrs | ReplaceEnumLabels] = []
        if src.labels != tgt.labels:
            if _is_ordered_subsequence(src.labels, tgt.labels):
                result.extend(_additions(src, tgt))
            else:
                result.append(
                    ReplaceEnumLabels(
                        target=src.ref,
                        old_labels=src.labels,
                        new_labels=tgt.labels,
                    )
                )

        if src.owner != tgt.owner:
            if tgt.owner is None:
                raise DiffError("Enum owner cannot be changed to an unresolved owner.")
            result.append(AlterEnumAttrs(target=src.ref, new_owner=tgt.owner))
        return tuple(result)


def _is_ordered_subsequence(source: tuple[str, ...], target: tuple[str, ...]) -> bool:
    source_index = 0
    for label in target:
        if source_index < len(source) and label == source[source_index]:
            source_index += 1
    return source_index == len(source)


def _additions(source: EnumType, target: EnumType) -> tuple[AddEnumValue, ...]:
    existing = set(source.labels)
    result: list[AddEnumValue] = []
    for index, label in enumerate(target.labels):
        if label in existing:
            continue
        next_existing = next(
            (candidate for candidate in target.labels[index + 1 :] if candidate in existing),
            None,
        )
        if next_existing is not None:
            result.append(AddEnumValue(target=source.ref, label=label, before=next_existing))
        elif index:
            result.append(
                AddEnumValue(target=source.ref, label=label, after=target.labels[index - 1])
            )
        else:
            result.append(AddEnumValue(target=source.ref, label=label))
    return tuple(result)


assert isinstance(EnumComparator(), Comparator), "EnumComparator must satisfy Comparator"
