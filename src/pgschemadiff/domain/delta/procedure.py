"""Procedure-level delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef
from pgschemadiff.domain.procedure import Procedure


def _check_procedure_target(target: ObjectRef, payload_ref: ObjectRef | None = None) -> None:
    if target.kind is not ObjectKind.PROCEDURE:
        raise ValueError(f"Procedure delta target must have kind PROCEDURE, got {target.kind!r}")
    if payload_ref is not None and target != payload_ref:
        raise ValueError(
            f"Procedure delta target {target!r} must equal procedure.ref {payload_ref!r}"
        )


class CreateProcedure(DeltaBase):
    """Create one exact procedure overload."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_procedure"] = "create_procedure"

    procedure: Procedure

    @model_validator(mode="after")
    def _check_target_matches_procedure(self) -> Self:
        _check_procedure_target(self.target, self.procedure.ref)
        return self


class DropProcedure(DeltaBase):
    """Drop one exact procedure overload."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_procedure"] = "drop_procedure"

    procedure: Procedure

    @model_validator(mode="after")
    def _check_target_matches_procedure(self) -> Self:
        _check_procedure_target(self.target, self.procedure.ref)
        return self


class ReplaceProcedure(DeltaBase):
    """Replace supported semantics for one existing overload."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_procedure"] = "replace_procedure"

    old_procedure: Procedure
    new_procedure: Procedure
    incompatible: bool = False

    @model_validator(mode="after")
    def _check_replace_consistency(self) -> Self:
        _check_procedure_target(self.target, self.old_procedure.ref)
        if self.old_procedure.ref != self.new_procedure.ref:
            raise ValueError("ReplaceProcedure requires identical procedure identities")
        if self.old_procedure == self.new_procedure:
            raise ValueError("ReplaceProcedure cannot represent an unchanged procedure")
        return self


class AlterProcedureOwner(DeltaBase):
    """Change one procedure overload's owner."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_procedure_owner"] = "alter_procedure_owner"

    procedure: Procedure
    new_owner: str

    @model_validator(mode="after")
    def _check_target_matches_procedure(self) -> Self:
        _check_procedure_target(self.target, self.procedure.ref)
        if not self.new_owner:
            raise ValueError("new_owner must not be empty")
        return self


ProcedureDelta = Annotated[
    CreateProcedure | DropProcedure | ReplaceProcedure | AlterProcedureOwner,
    Field(discriminator="kind"),
]
