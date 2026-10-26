"""Row-level security policy domain model."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class PolicyCommand(StrEnum):
    """Commands to which a PostgreSQL row-security policy applies."""

    ALL = "ALL"
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class Policy(BaseModel):
    """One immutable, table-owned PostgreSQL RLS policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    table_ref: ObjectRef
    command: PolicyCommand
    permissive: bool
    roles: tuple[str, ...] = Field(min_length=1)
    using_expr: str | None = None
    with_check_expr: str | None = None

    @field_validator("roles")
    @classmethod
    def _check_roles(cls, roles: tuple[str, ...]) -> tuple[str, ...]:
        if any(not role.strip() for role in roles):
            raise ValueError("Policy roles must be non-empty names")
        if roles != tuple(sorted(roles)):
            raise ValueError("Policy roles must be sorted")
        if len(roles) != len(set(roles)):
            raise ValueError("Policy roles must be unique")
        return roles

    @field_validator("using_expr", "with_check_expr")
    @classmethod
    def _check_expression(cls, expression: str | None) -> str | None:
        if expression is not None and (not expression.strip() or expression.strip() == "?"):
            raise ValueError("Policy expression must be a usable catalog expression")
        return expression

    @model_validator(mode="after")
    def _check_identity(self) -> Self:
        if self.table_ref.kind is not ObjectKind.TABLE:
            raise ValueError("Policy.table_ref must have kind TABLE")
        if self.ref.kind is not ObjectKind.POLICY:
            raise ValueError("Policy.ref must have kind POLICY")
        if self.ref.parent != self.table_ref:
            raise ValueError("Policy.ref.parent must match table_ref")
        if self.ref.qname.namespace != self.table_ref.qname.namespace:
            raise ValueError("Policy and table_ref must use the same namespace")
        return self


__all__ = ["Policy", "PolicyCommand"]
