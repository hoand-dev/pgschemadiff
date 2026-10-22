"""Comparator for PostgreSQL extensions."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.schema import AlterExtension, CreateExtension, DropExtension
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.extension import Extension


class ExtensionComparator:
    """Compare extension existence and supported extension-level metadata."""

    kind: ObjectKind = ObjectKind.EXTENSION

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[DeltaBase, ...]:
        """Compare extension version and installed schema."""
        src = cast("Extension | None", source)
        tgt = cast("Extension | None", target)

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateExtension(target=tgt.ref, extension=tgt),)
        if tgt is None:
            return (DropExtension(target=src.ref, extension=src),)

        if src.comment != tgt.comment:
            raise DiffError(
                f"Extension comment changes are not supported: {src.comment!r} -> {tgt.comment!r}"
            )
        if src.installed_schema != tgt.installed_schema and tgt.installed_schema is None:
            raise DiffError("Extension installed-schema changes to None are not supported")

        new_version = tgt.version if src.version != tgt.version else None
        new_schema = tgt.installed_schema if src.installed_schema != tgt.installed_schema else None
        if new_version is None and new_schema is None:
            return ()
        return (
            AlterExtension(
                target=tgt.ref,
                new_version=new_version,
                new_schema=new_schema,
            ),
        )


assert isinstance(ExtensionComparator(), Comparator), "ExtensionComparator must satisfy Comparator"
