"""Comparator for PostgreSQL procedure overloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.procedure import (
    AlterProcedureOwner,
    CreateProcedure,
    DropProcedure,
    ProcedureDelta,
    ReplaceProcedure,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.procedure import Procedure


def _parameter_shape(procedure: Procedure) -> tuple[tuple[str | None, str, str], ...]:
    return tuple(
        (argument.name, argument.mode, argument.data_type) for argument in procedure.arguments
    )


class ProcedureComparator:
    """Compare procedure existence, semantics, and ownership by overload identity."""

    kind: ObjectKind = ObjectKind.PROCEDURE

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[ProcedureDelta, ...]:
        src: Procedure | None = source  # type: ignore[assignment]
        tgt: Procedure | None = target  # type: ignore[assignment]

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateProcedure(target=tgt.ref, procedure=tgt),)
        if tgt is None:
            return (DropProcedure(target=src.ref, procedure=src),)
        if src.ref != tgt.ref:
            raise DiffError(
                f"Cannot compare distinct procedure identities: {src.ref!r} != {tgt.ref!r}"
            )

        result: list[ProcedureDelta] = []
        if src.model_dump(exclude={"owner"}) != tgt.model_dump(exclude={"owner"}):
            result.append(
                ReplaceProcedure(
                    target=src.ref,
                    old_procedure=src,
                    new_procedure=tgt,
                    incompatible=_parameter_shape(src) != _parameter_shape(tgt),
                )
            )

        if src.owner != tgt.owner:
            if tgt.owner is None:
                raise DiffError("Procedure owner cannot be changed to an unresolved owner.")
            result.append(AlterProcedureOwner(target=src.ref, procedure=src, new_owner=tgt.owner))
        return tuple(result)


assert isinstance(ProcedureComparator(), Comparator)
