"""Immutable domain model for PostgreSQL enum types."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class EnumType(BaseModel):
    """A PostgreSQL enum type with labels in ``enumsortorder`` order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    labels: tuple[str, ...] = ()
    """Labels in sort order; PostgreSQL allows an enum with no labels."""
    owner: str | None = None

    @model_validator(mode="after")
    def _check_enum(self) -> Self:
        if self.ref.kind is not ObjectKind.ENUM:
            raise ValueError(f"EnumType.ref must have kind ENUM, got {self.ref.kind!r}")
        if any(not label for label in self.labels):
            raise ValueError("EnumType labels must be non-empty strings")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("EnumType labels must be unique")
        return self
