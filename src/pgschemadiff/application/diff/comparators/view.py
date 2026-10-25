"""Comparator for PostgreSQL views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.view import (
    AlterViewOwner,
    CreateView,
    DropView,
    ReplaceView,
    ViewDelta,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.view import View


class ViewComparator:
    """Compare view definitions, options, output compatibility, and owner."""

    kind: ObjectKind = ObjectKind.VIEW

    def compare(self, source: object | None, target: object | None) -> tuple[ViewDelta, ...]:
        src: View | None = source  # type: ignore[assignment]
        tgt: View | None = target  # type: ignore[assignment]

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateView(target=tgt.ref, view=tgt),)
        if tgt is None:
            return (DropView(target=src.ref, view=src),)
        if src.ref != tgt.ref:
            raise DiffError(f"Cannot compare distinct view identities: {src.ref!r} != {tgt.ref!r}")

        result: list[ViewDelta] = []
        if src.model_dump(exclude={"owner"}) != tgt.model_dump(exclude={"owner"}):
            result.append(
                ReplaceView(
                    target=src.ref,
                    old_view=src,
                    new_view=tgt,
                    incompatible=not src.can_be_replaced_by(tgt),
                )
            )

        if src.owner != tgt.owner:
            if tgt.owner is None:
                raise DiffError("View owner cannot be changed to an unresolved owner.")
            result.append(AlterViewOwner(target=src.ref, view=src, new_owner=tgt.owner))
        return tuple(result)


assert isinstance(ViewComparator(), Comparator)
