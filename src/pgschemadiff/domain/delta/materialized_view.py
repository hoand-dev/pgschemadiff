"""Materialized-view delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef
from pgschemadiff.domain.materialized_view import MaterializedView


def _check_target(target: ObjectRef, payload_ref: ObjectRef | None = None) -> None:
    if target.kind is not ObjectKind.MATERIALIZED_VIEW:
        raise ValueError(
            f"Materialized-view delta target must have kind MATERIALIZED_VIEW, got {target.kind!r}"
        )
    if payload_ref is not None and target != payload_ref:
        raise ValueError(
            f"Materialized-view delta target {target!r} must equal materialized_view.ref "
            f"{payload_ref!r}"
        )


class CreateMaterializedView(DeltaBase):
    """Create one PostgreSQL materialized view."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_materialized_view"] = "create_materialized_view"

    materialized_view: MaterializedView

    @model_validator(mode="after")
    def _check_target_matches_view(self) -> Self:
        _check_target(self.target, self.materialized_view.ref)
        return self


class DropMaterializedView(DeltaBase):
    """Drop one PostgreSQL materialized view restrictively."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_materialized_view"] = "drop_materialized_view"

    materialized_view: MaterializedView

    @model_validator(mode="after")
    def _check_target_matches_view(self) -> Self:
        _check_target(self.target, self.materialized_view.ref)
        return self


class ReplaceMaterializedView(DeltaBase):
    """Drop and recreate a materialized view whose query or options changed."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_materialized_view"] = "replace_materialized_view"

    old_materialized_view: MaterializedView
    new_materialized_view: MaterializedView

    @model_validator(mode="after")
    def _check_replace_consistency(self) -> Self:
        _check_target(self.target, self.old_materialized_view.ref)
        if self.old_materialized_view.ref != self.new_materialized_view.ref:
            raise ValueError(
                "ReplaceMaterializedView requires identical materialized-view identities"
            )
        if self.old_materialized_view == self.new_materialized_view:
            raise ValueError(
                "ReplaceMaterializedView cannot represent an unchanged materialized view"
            )
        return self


class AlterMaterializedViewOwner(DeltaBase):
    """Change one materialized view's owner."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_materialized_view_owner"] = "alter_materialized_view_owner"

    materialized_view: MaterializedView
    new_owner: str

    @model_validator(mode="after")
    def _check_target_matches_view(self) -> Self:
        _check_target(self.target, self.materialized_view.ref)
        if not self.new_owner:
            raise ValueError("new_owner must not be empty")
        return self


MaterializedViewDelta = Annotated[
    CreateMaterializedView
    | DropMaterializedView
    | ReplaceMaterializedView
    | AlterMaterializedViewOwner,
    Field(discriminator="kind"),
]
