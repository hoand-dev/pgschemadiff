"""Immutable domain model for PostgreSQL views."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class View(BaseModel):
    """A view's ordered output shape, query, options, owner, and prerequisites."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    columns: tuple[tuple[str, str], ...] = Field(min_length=1)
    definition: str = Field(min_length=1)
    check_option: Literal["none", "local", "cascaded"] = "none"
    security_barrier: bool = False
    security_invoker: bool = False
    owner: str | None = None
    prerequisites: tuple[ObjectRef, ...] = Field(default=())

    def can_be_replaced_by(self, target: View) -> bool:
        """Return whether PostgreSQL can replace this view with *target* in place."""
        return len(target.columns) >= len(self.columns) and target.columns[: len(self.columns)] == (
            self.columns
        )

    @model_validator(mode="after")
    def _check_view(self) -> Self:
        if self.ref.kind is not ObjectKind.VIEW:
            raise ValueError(f"View.ref must have kind VIEW, got {self.ref.kind!r}")
        if not self.definition.strip():
            raise ValueError("View definition must not be blank")
        names = tuple(name for name, _ in self.columns)
        if any(not name for name in names) or len(set(names)) != len(names):
            raise ValueError("View output column names must be non-empty and unique")
        if any(not data_type.strip() for _, data_type in self.columns):
            raise ValueError("View output column types must not be blank")
        if len(set(self.prerequisites)) != len(self.prerequisites):
            raise ValueError("Duplicate prerequisite in view")
        if self.ref in self.prerequisites:
            raise ValueError("View cannot depend on itself")
        if self.owner is not None and not self.owner:
            raise ValueError("View owner must not be empty")
        return self
