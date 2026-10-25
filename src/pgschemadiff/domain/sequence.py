"""Immutable domain model for PostgreSQL sequences."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class Sequence(BaseModel):
    """A sequence's schema options and optional owned column, never runtime state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    data_type: Literal["smallint", "integer", "bigint"]
    start: int
    increment: int
    min_value: int
    max_value: int
    cache: int
    cycle: bool
    owner: str | None = None
    owned_by: ObjectRef | None = None

    @model_validator(mode="after")
    def _check_sequence(self) -> Self:
        if self.ref.kind is not ObjectKind.SEQUENCE:
            raise ValueError(f"Sequence.ref must have kind SEQUENCE, got {self.ref.kind!r}")
        if self.increment == 0:
            raise ValueError("increment must not be zero")
        if self.min_value > self.max_value:
            raise ValueError("min_value must not exceed max_value")
        if not self.min_value <= self.start <= self.max_value:
            raise ValueError("start must be between min_value and max_value")
        if self.cache < 1:
            raise ValueError("cache must be at least 1")
        if self.owner is not None and not self.owner:
            raise ValueError("owner must not be empty")
        if self.owned_by is not None and self.owned_by.kind is not ObjectKind.COLUMN:
            raise ValueError("owned_by must have kind COLUMN")
        return self
