"""View-level delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef
from pgschemadiff.domain.view import View


def _check_view_target(target: ObjectRef, payload_ref: ObjectRef | None = None) -> None:
    if target.kind is not ObjectKind.VIEW:
        raise ValueError(f"View delta target must have kind VIEW, got {target.kind!r}")
    if payload_ref is not None and target != payload_ref:
        raise ValueError(f"View delta target {target!r} must equal view.ref {payload_ref!r}")


class CreateView(DeltaBase):
    """Create one PostgreSQL view."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_view"] = "create_view"

    view: View

    @model_validator(mode="after")
    def _check_target_matches_view(self) -> Self:
        _check_view_target(self.target, self.view.ref)
        return self


class DropView(DeltaBase):
    """Drop one PostgreSQL view restrictively."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_view"] = "drop_view"

    view: View

    @model_validator(mode="after")
    def _check_target_matches_view(self) -> Self:
        _check_view_target(self.target, self.view.ref)
        return self


class ReplaceView(DeltaBase):
    """Replace view query/options when PostgreSQL output compatibility permits."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_view"] = "replace_view"

    old_view: View
    new_view: View
    incompatible: bool = False

    @model_validator(mode="after")
    def _check_replace_consistency(self) -> Self:
        _check_view_target(self.target, self.old_view.ref)
        if self.old_view.ref != self.new_view.ref:
            raise ValueError("ReplaceView requires identical view identities")
        if self.old_view == self.new_view:
            raise ValueError("ReplaceView cannot represent an unchanged view")
        return self


class AlterViewOwner(DeltaBase):
    """Change one view's owner."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_view_owner"] = "alter_view_owner"

    view: View
    new_owner: str

    @model_validator(mode="after")
    def _check_target_matches_view(self) -> Self:
        _check_view_target(self.target, self.view.ref)
        if not self.new_owner:
            raise ValueError("new_owner must not be empty")
        return self


ViewDelta = Annotated[
    CreateView | DropView | ReplaceView | AlterViewOwner,
    Field(discriminator="kind"),
]
