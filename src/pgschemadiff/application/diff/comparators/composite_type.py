"""Comparator for PostgreSQL composite types."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.composite_type import (
    AlterCompositeAddAttribute,
    AlterCompositeAttributeType,
    AlterCompositeDropAttribute,
    AlterCompositeTypeAttrs,
    CompositeTypeDelta,
    CreateCompositeType,
    DropCompositeType,
    ReplaceCompositeType,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType


class CompositeTypeComparator:
    """Compare composite type existence, ordered attributes, and owner."""

    kind: ObjectKind = ObjectKind.COMPOSITE_TYPE

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[CompositeTypeDelta, ...]:
        """Emit create/drop, supported attribute changes, or blocked replacement."""
        src = cast("CompositeType | None", source)
        tgt = cast("CompositeType | None", target)

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateCompositeType(target=tgt.ref, composite=tgt),)
        if tgt is None:
            return (DropCompositeType(target=src.ref, composite=src),)

        result: list[CompositeTypeDelta] = []
        if _requires_replacement(src.attributes, tgt.attributes):
            result.append(
                ReplaceCompositeType(
                    target=src.ref,
                    old_attributes=src.attributes,
                    new_attributes=tgt.attributes,
                )
            )
        else:
            source_by_name = {attribute.name: attribute for attribute in src.attributes}
            target_by_name = {attribute.name: attribute for attribute in tgt.attributes}

            result.extend(
                AlterCompositeDropAttribute(
                    target=src.ref,
                    attribute_name=attribute.name,
                    type_prerequisites=src.type_prerequisites,
                )
                for attribute in src.attributes
                if attribute.name not in target_by_name
            )
            result.extend(
                AlterCompositeAttributeType(
                    target=src.ref,
                    attribute_name=attribute.name,
                    new_data_type=attribute.data_type,
                    new_collation=attribute.collation,
                    old_type_prerequisites=src.type_prerequisites,
                    new_type_prerequisites=tgt.type_prerequisites,
                )
                for attribute in tgt.attributes
                if attribute.name in source_by_name
                and (
                    source_by_name[attribute.name].data_type != attribute.data_type
                    or source_by_name[attribute.name].collation != attribute.collation
                )
            )
            result.extend(
                AlterCompositeAddAttribute(
                    target=src.ref,
                    attribute=attribute,
                    type_prerequisites=tgt.type_prerequisites,
                )
                for attribute in tgt.attributes
                if attribute.name not in source_by_name
            )

        if src.owner != tgt.owner:
            if tgt.owner is None:
                raise DiffError("Composite type owner cannot be changed to an unresolved owner.")
            result.append(AlterCompositeTypeAttrs(target=src.ref, new_owner=tgt.owner))
        return tuple(result)


def _requires_replacement(
    source: tuple[CompositeAttribute, ...],
    target: tuple[CompositeAttribute, ...],
) -> bool:
    source_names = tuple(attribute.name for attribute in source)
    target_names = tuple(attribute.name for attribute in target)
    source_survivors = tuple(name for name in source_names if name in target_names)
    target_survivors = tuple(name for name in target_names if name in source_names)
    if source_survivors != target_survivors:
        return True

    source_name_set = set(source_names)
    last_existing_position = max(
        (index for index, name in enumerate(target_names) if name in source_name_set),
        default=-1,
    )
    return any(
        index < last_existing_position and name not in source_name_set
        for index, name in enumerate(target_names)
    )


assert isinstance(CompositeTypeComparator(), Comparator)
