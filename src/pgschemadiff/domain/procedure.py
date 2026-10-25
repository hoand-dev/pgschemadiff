"""Immutable domain models for PostgreSQL procedures."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class ProcedureArgument(BaseModel):
    """One declared procedure argument, including output-only arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    mode: Literal["IN", "OUT", "INOUT", "VARIADIC"] = "IN"
    data_type: str = Field(min_length=1)
    default_expr: str | None = None


class Procedure(BaseModel):
    """A procedure's identity, behavior, and catalog-deparsed creation DDL.

    PostgreSQL 18 ``pg_proc.proargtypes`` contains only IN, INOUT, and
    VARIADIC argument types. ``DROP PROCEDURE`` resolves identity from those
    inputs; OUT argument types remain modeled payload, not identity (see the
    PostgreSQL 18 ``pg_proc`` and ``DROP PROCEDURE`` documentation).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    arguments: tuple[ProcedureArgument, ...] = Field(default=())
    language: str = Field(min_length=1)
    security_definer: bool
    transforms: tuple[str, ...] = Field(default=())
    config: tuple[str, ...] = Field(default=())
    default_expressions: str | None = None
    default_count: int = Field(default=0, ge=0)
    body: str
    definition: str | None = None
    owner: str | None = None
    type_prerequisites: tuple[ObjectRef, ...] = Field(default=())

    @model_validator(mode="after")
    def _check_procedure(self) -> Self:
        if self.ref.kind is not ObjectKind.PROCEDURE:
            raise ValueError(f"Procedure.ref must have kind PROCEDURE, got {self.ref.kind!r}")
        input_types = tuple(
            argument.data_type
            for argument in self.arguments
            if argument.mode in {"IN", "INOUT", "VARIADIC"}
        )
        if input_types != self.ref.arg_signature:
            raise ValueError("Procedure arguments with input modes must match ref.arg_signature")
        if self.default_count > len(input_types):
            raise ValueError("Procedure default_count cannot exceed the number of input arguments")
        if len(set(self.type_prerequisites)) != len(self.type_prerequisites):
            raise ValueError(f"Duplicate type prerequisite in {self.ref.qname.fqn}")
        return self

    @property
    def effective_default_count(self) -> int:
        """Return catalog count or derive it from explicitly modeled defaults."""
        if self.default_count:
            return self.default_count
        return sum(argument.default_expr is not None for argument in self.arguments)

    @property
    def is_supported(self) -> bool:
        """Whether this language is reproducible by the MVP migration emitter."""
        return self.language.lower() in {"sql", "plpgsql"}
