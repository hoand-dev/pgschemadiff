"""Immutable domain model for PostgreSQL table triggers."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class Trigger(BaseModel):
    """A trigger's identity, behavior, enabled state, and owning dependencies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    table_ref: ObjectRef
    function_ref: ObjectRef
    definition: str
    timing: Literal["BEFORE", "AFTER", "INSTEAD OF"]
    events: tuple[Literal["INSERT", "UPDATE", "DELETE", "TRUNCATE"], ...]
    row_level: bool
    columns: tuple[str, ...] = ()
    when_expr: str | None = None
    is_constraint: bool
    deferrable: bool
    initially_deferred: bool
    enabled: Literal["O", "D", "R", "A"]
    referenced_table_ref: ObjectRef | None = None

    @model_validator(mode="after")
    def _check_identity_and_references(self) -> Self:
        if self.ref.kind is not ObjectKind.TRIGGER:
            raise ValueError(f"Trigger.ref must have kind TRIGGER, got {self.ref.kind!r}")
        if self.table_ref.kind is not ObjectKind.TABLE:
            raise ValueError("Trigger.table_ref must have kind TABLE")
        if (
            self.ref.parent != self.table_ref
            or self.ref.qname.namespace != self.table_ref.qname.namespace
        ):
            raise ValueError("Trigger.ref parent must match table_ref and namespace")
        if self.function_ref.kind is not ObjectKind.FUNCTION:
            raise ValueError("Trigger.function_ref must have kind FUNCTION")
        if self.referenced_table_ref is not None:
            if self.referenced_table_ref.kind is not ObjectKind.TABLE:
                raise ValueError("Trigger.referenced_table_ref must have kind TABLE")
            if not self.is_constraint:
                raise ValueError("Only constraint triggers can reference another table")

        return self

    @model_validator(mode="after")
    def _check_definition_and_shape(self) -> Self:
        if not self.definition.strip() or self.definition.strip() == "?":
            raise ValueError("Trigger definition must not be blank or a deparser sentinel")
        if not self.events:
            raise ValueError("Trigger must have at least one event")
        if len(set(self.events)) != len(self.events):
            raise ValueError("Trigger has a duplicate event")
        if any(not column for column in self.columns):
            raise ValueError("Trigger column names must not be empty")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Trigger has a duplicate column")
        if self.when_expr is not None and (
            not self.when_expr.strip() or self.when_expr.strip() == "?"
        ):
            raise ValueError("Trigger WHEN expression must not be blank or a deparser sentinel")

        return self

    @model_validator(mode="after")
    def _check_deferrability(self) -> Self:
        if not self.is_constraint and (self.deferrable or self.initially_deferred):
            raise ValueError("A non-constraint trigger cannot be deferrable")
        if self.initially_deferred and not self.deferrable:
            raise ValueError("Initially deferred trigger must be deferrable")
        return self
