"""Function-level delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.function import Function
from pgschemadiff.domain.identity import ObjectKind, ObjectRef


def _check_function_target(target: ObjectRef, payload_ref: ObjectRef | None = None) -> None:
    if target.kind is not ObjectKind.FUNCTION:
        raise ValueError(f"Function delta target must have kind FUNCTION, got {target.kind!r}")
    if payload_ref is not None and target != payload_ref:
        raise ValueError(
            f"Function delta target {target!r} must equal function.ref {payload_ref!r}"
        )


class CreateFunction(DeltaBase):
    """Create one exact function overload."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_function"] = "create_function"

    function: Function
    default_conflict: bool = False

    @model_validator(mode="after")
    def _check_target_matches_function(self) -> Self:
        _check_function_target(self.target, self.function.ref)
        return self


class DropFunction(DeltaBase):
    """Drop one exact function overload."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_function"] = "drop_function"

    function: Function

    @model_validator(mode="after")
    def _check_target_matches_function(self) -> Self:
        _check_function_target(self.target, self.function.ref)
        return self


class ReplaceFunction(DeltaBase):
    """Replace supported semantics for one existing overload."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_function"] = "replace_function"

    old_function: Function
    new_function: Function
    incompatible: bool = False
    default_conflict: bool = False

    @model_validator(mode="after")
    def _check_replace_consistency(self) -> Self:
        _check_function_target(self.target, self.old_function.ref)
        if self.old_function.ref != self.new_function.ref:
            raise ValueError("ReplaceFunction requires identical function identities")
        if self.old_function == self.new_function:
            raise ValueError("ReplaceFunction cannot represent an unchanged function")
        return self


class AlterFunctionOwner(DeltaBase):
    """Change one function overload's owner."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_function_owner"] = "alter_function_owner"

    function: Function
    new_owner: str

    @model_validator(mode="after")
    def _check_target_matches_function(self) -> Self:
        _check_function_target(self.target, self.function.ref)
        if not self.new_owner:
            raise ValueError("new_owner must not be empty")
        return self


FunctionDelta = Annotated[
    CreateFunction | DropFunction | ReplaceFunction | AlterFunctionOwner,
    Field(discriminator="kind"),
]
