"""Immutable domain models for PostgreSQL composite types."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class CompositeAttribute(BaseModel):
    """One live attribute of a PostgreSQL composite type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    collation: str | None = None


class CompositeType(BaseModel):
    """A PostgreSQL composite type with attributes in ``attnum`` order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    attributes: tuple[CompositeAttribute, ...] = Field(default=())
    type_prerequisites: tuple[ObjectRef, ...] = Field(default=())
    owner: str | None = None

    @model_validator(mode="after")
    def _check_composite_type(self) -> Self:
        if self.ref.kind is not ObjectKind.COMPOSITE_TYPE:
            raise ValueError(
                f"CompositeType.ref must have kind COMPOSITE_TYPE, got {self.ref.kind!r}"
            )
        names = tuple(attribute.name for attribute in self.attributes)
        if len(set(names)) != len(names):
            raise ValueError("Attribute names must be unique")
        if len(set(self.type_prerequisites)) != len(self.type_prerequisites):
            raise ValueError(f"Duplicate type prerequisite in {self.ref.qname.fqn}")
        return self
