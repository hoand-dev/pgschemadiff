"""Exact object and attribute exclusions for a completed :class:`DeltaSet`."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from pgschemadiff.domain.delta import (
    AlterColumnType,
    AlterExtension,
    AlterTableAttrs,
    DeltaBase,
    DeltaSet,
    RenameColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef

_ATTRIBUTE_FIELDS: dict[ObjectKind, dict[str, str]] = {
    ObjectKind.TABLE: {
        "owner": "new_owner",
        "tablespace": "new_tablespace",
        "comment": "new_comment",
        "unlogged": "new_unlogged",
        "partition_info": "new_partition_info",
        "partition_of": "new_partition_of",
        "row_security": "new_row_security",
        "force_row_security": "new_force_row_security",
    },
    ObjectKind.EXTENSION: {"version": "new_version", "schema": "new_schema"},
    ObjectKind.COLUMN: {
        "type": "new_data_type",
        "default": "new_default",
        "nullability": "nullable",
        "name": "new_name",
    },
}


class IgnoreRules(BaseModel):
    """Immutable exact-match rules applied to a completed delta set.

    ``objects`` matches the full :class:`ObjectRef` and suppresses deltas whose
    target is that object. ``attributes`` contains ``(ObjectRef, attribute)``
    pairs. Attribute names are ``owner``, ``tablespace``, ``comment``,
    ``unlogged``, ``partition_info``, ``partition_of``, ``row_security``, and
    ``force_row_security`` for tables; ``version`` and
    ``schema`` for extensions; and ``type``, ``default``, ``nullability``, and
    ``name`` for columns. Rules do not use globs or cascade to dependent objects.

    Attribute rules remove only matching atomic column changes and can strip a
    single field from bundled table or extension alterations. Object lifecycle
    deltas (create/drop/replace) remain intact unless their object is ignored.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    objects: frozenset[ObjectRef] = frozenset()
    attributes: frozenset[tuple[ObjectRef, str]] = frozenset()

    @model_validator(mode="after")
    def _validate_attributes(self) -> Self:
        for object_ref, attribute in self.attributes:
            supported = _ATTRIBUTE_FIELDS.get(object_ref.kind, {})
            if attribute not in supported:
                raise ValueError(
                    f"Unsupported ignored attribute {attribute!r} for {object_ref.kind.value}"
                )
        return self

    def apply(self, deltas: DeltaSet) -> DeltaSet:
        """Return filtered deltas without mutating the input set or its items."""
        attributes_by_object: dict[ObjectRef, set[str]] = {}
        for object_ref, attribute in self.attributes:
            attributes_by_object.setdefault(object_ref, set()).add(attribute)

        filtered: list[DeltaBase] = []
        for delta in deltas:
            if delta.target in self.objects:
                continue

            kept = _filter_attributes(delta, attributes_by_object.get(delta.target, set()))
            if kept is not None:
                filtered.append(kept)

        return DeltaSet.from_iterable(filtered)


def _filter_attributes(delta: DeltaBase, ignored: set[str]) -> DeltaBase | None:
    if not ignored:
        return delta

    if isinstance(delta, AlterTableAttrs):
        return _strip_optional_fields(
            delta,
            ignored,
            _ATTRIBUTE_FIELDS[ObjectKind.TABLE],
        )

    if isinstance(delta, AlterExtension):
        return _strip_optional_fields(
            delta,
            ignored,
            _ATTRIBUTE_FIELDS[ObjectKind.EXTENSION],
        )

    if isinstance(delta, AlterColumnType) and "type" in ignored:
        return None
    if isinstance(delta, SetColumnDefault) and "default" in ignored:
        return None
    if isinstance(delta, SetColumnNullability) and "nullability" in ignored:
        return None
    if isinstance(delta, RenameColumn) and "name" in ignored:
        return None

    return delta


def _strip_optional_fields(
    delta: AlterTableAttrs | AlterExtension,
    ignored: set[str],
    attribute_fields: dict[str, str],
) -> DeltaBase | None:
    fields = tuple(attribute_fields.values())
    updates = {
        field: None
        for attribute, field in attribute_fields.items()
        if attribute in ignored and getattr(delta, field) is not None
    }
    if not updates:
        return delta
    if all(field in updates or getattr(delta, field) is None for field in fields):
        return None
    return delta.model_copy(update=updates)


__all__ = ["IgnoreRules"]
