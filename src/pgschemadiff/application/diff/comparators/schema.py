"""Comparator for PostgreSQL schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.schema import CreateSchema, DropSchema
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.schema import Schema


class SchemaComparator:
    """Compare schema existence and supported schema-level metadata."""

    kind: ObjectKind = ObjectKind.SCHEMA

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[DeltaBase, ...]:
        """Compare schema metadata, leaving contained objects to their comparators."""
        src = cast("Schema | None", source)
        tgt = cast("Schema | None", target)

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateSchema(target=tgt.ref, pg_schema=tgt),)
        if tgt is None:
            return (DropSchema(target=src.ref, pg_schema=src),)

        if src.owner != tgt.owner:
            raise DiffError(
                f"Schema owner changes are not supported: {src.owner!r} -> {tgt.owner!r}"
            )
        if src.comment != tgt.comment:
            raise DiffError(
                f"Schema comment changes are not supported: {src.comment!r} -> {tgt.comment!r}"
            )
        return ()


assert isinstance(SchemaComparator(), Comparator), "SchemaComparator must satisfy Comparator"
