"""Immutable domain models for PostgreSQL domains."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class DomainCheck(BaseModel):
    """One named domain check and its PostgreSQL validation state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    validated: bool = True


class DomainType(BaseModel):
    """A PostgreSQL domain's base semantics, checks, and type dependencies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    base_type: str = Field(min_length=1)
    collation: str | None = None
    default_expr: str | None = None
    not_null: bool = False
    checks: tuple[DomainCheck, ...] = Field(default=())
    type_prerequisites: tuple[ObjectRef, ...] = Field(default=())
    used_in_container: bool = False
    owner: str | None = None

    @model_validator(mode="after")
    def _check_domain_type(self) -> Self:
        if self.ref.kind is not ObjectKind.DOMAIN_TYPE:
            raise ValueError(f"DomainType.ref must have kind DOMAIN_TYPE, got {self.ref.kind!r}")
        check_names = tuple(check.name for check in self.checks)
        if len(set(check_names)) != len(check_names):
            raise ValueError("Check names must be unique")
        if check_names != tuple(sorted(check_names)):
            raise ValueError("Domain checks must be ordered by name")
        if len(set(self.type_prerequisites)) != len(self.type_prerequisites):
            raise ValueError(f"Duplicate type prerequisite in {self.ref.qname.fqn}")
        return self
