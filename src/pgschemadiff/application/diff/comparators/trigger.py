"""Comparator for PostgreSQL table triggers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.trigger import (
    AlterTriggerEnabled,
    CreateTrigger,
    DropTrigger,
    ReplaceTrigger,
    TriggerDelta,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.trigger import Trigger


class TriggerComparator:
    """Compare catalog-deparsed trigger definitions and structured behavior."""

    kind: ObjectKind = ObjectKind.TRIGGER

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[TriggerDelta, ...]:
        src: Trigger | None = source  # type: ignore[assignment]
        tgt: Trigger | None = target  # type: ignore[assignment]

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateTrigger(target=tgt.ref, trigger=tgt),)
        if tgt is None:
            return (DropTrigger(target=src.ref, trigger=src),)
        if src.ref != tgt.ref:
            raise DiffError(
                f"Cannot compare distinct trigger identities: {src.ref!r} != {tgt.ref!r}"
            )

        if src.model_dump(exclude={"enabled"}) != tgt.model_dump(exclude={"enabled"}):
            return (ReplaceTrigger(target=src.ref, old_trigger=src, new_trigger=tgt),)
        if src.enabled != tgt.enabled:
            return (AlterTriggerEnabled(target=src.ref, trigger=src, new_enabled=tgt.enabled),)
        return ()


assert isinstance(TriggerComparator(), Comparator)
