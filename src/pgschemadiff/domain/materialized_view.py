"""Immutable domain model for PostgreSQL materialized views."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class MaterializedView(BaseModel):
    """A materialized view's query, physical options, owner, and prerequisites."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    columns: tuple[tuple[str, str], ...] = Field(min_length=1)
    definition: str = Field(min_length=1)
    access_method: str | None = None
    tablespace: str | None = None
    storage_parameters: tuple[str, ...] = Field(default=())
    owner: str | None = None
    prerequisites: tuple[ObjectRef, ...] = Field(default=())
    dependents: tuple[ObjectRef, ...] = Field(default=())
    has_indexes: bool = False

    @model_validator(mode="after")
    def _check_materialized_view(self) -> Self:
        if self.ref.kind is not ObjectKind.MATERIALIZED_VIEW:
            raise ValueError(
                f"MaterializedView.ref must have kind MATERIALIZED_VIEW, got {self.ref.kind!r}"
            )
        if not self.definition.strip():
            raise ValueError("Materialized view definition must not be blank")
        names = tuple(name for name, _ in self.columns)
        if any(not name for name in names) or len(set(names)) != len(names):
            raise ValueError("Materialized-view output column names must be non-empty and unique")
        if any(not data_type.strip() for _, data_type in self.columns):
            raise ValueError("Materialized-view output column types must not be blank")
        if len(set(self.prerequisites)) != len(self.prerequisites):
            raise ValueError("Duplicate prerequisite in materialized view")
        if len(set(self.dependents)) != len(self.dependents):
            raise ValueError("Duplicate dependent in materialized view")
        if self.ref in self.prerequisites:
            raise ValueError("Materialized view cannot depend on itself")
        if self.ref in self.dependents:
            raise ValueError("Materialized view cannot depend on itself")
        if self.owner is not None and not self.owner:
            raise ValueError("Materialized view owner must not be empty")
        if self.access_method is not None and not self.access_method:
            raise ValueError("Materialized-view access method must not be empty")
        if self.tablespace is not None and not self.tablespace:
            raise ValueError("Materialized-view tablespace must not be empty")
        if any(not parameter.strip() for parameter in self.storage_parameters):
            raise ValueError("Materialized-view storage parameters must not be empty")
        return self
