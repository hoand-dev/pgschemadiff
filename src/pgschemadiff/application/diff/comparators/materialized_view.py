"""Comparator for PostgreSQL materialized views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.materialized_view import (
    AlterMaterializedViewOwner,
    CreateMaterializedView,
    DropMaterializedView,
    MaterializedViewDelta,
    ReplaceMaterializedView,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.materialized_view import MaterializedView


class MaterializedViewComparator:
    """Compare materialized-view definitions, physical options, and owner."""

    kind: ObjectKind = ObjectKind.MATERIALIZED_VIEW

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[MaterializedViewDelta, ...]:
        src: MaterializedView | None = source  # type: ignore[assignment]
        tgt: MaterializedView | None = target  # type: ignore[assignment]

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateMaterializedView(target=tgt.ref, materialized_view=tgt),)
        if tgt is None:
            return (DropMaterializedView(target=src.ref, materialized_view=src),)
        if src.ref != tgt.ref:
            raise DiffError(
                f"Cannot compare distinct materialized-view identities: {src.ref!r} != {tgt.ref!r}"
            )

        result: list[MaterializedViewDelta] = []
        if src.model_dump(exclude={"owner", "dependents", "has_indexes"}) != tgt.model_dump(
            exclude={"owner", "dependents", "has_indexes"}
        ):
            result.append(
                ReplaceMaterializedView(
                    target=src.ref,
                    old_materialized_view=src,
                    new_materialized_view=tgt,
                )
            )

        if src.owner != tgt.owner:
            if tgt.owner is None:
                raise DiffError("Materialized-view owner cannot be changed to an unresolved owner.")
            result.append(
                AlterMaterializedViewOwner(
                    target=src.ref,
                    materialized_view=src,
                    new_owner=tgt.owner,
                )
            )
        return tuple(result)


assert isinstance(MaterializedViewComparator(), Comparator)
