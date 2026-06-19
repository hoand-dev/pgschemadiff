"""Constraint domain models (task P1-DOM-03).

Provides a Pydantic v2 discriminated union over five PostgreSQL constraint kinds:

- :class:`PrimaryKeyConstraint` — ``PRIMARY KEY (col, ...)``
- :class:`UniqueConstraint` — ``UNIQUE (col, ...)``
- :class:`CheckConstraint` — ``CHECK (expr)``
- :class:`ForeignKeyConstraint` — ``FOREIGN KEY (...) REFERENCES ...``
- :class:`ExclusionConstraint` — ``EXCLUDE USING method (col WITH op, ...)``

Use :data:`Constraint` (the discriminated union alias) as the field type in
parent models.  The ``kind`` field acts as the Pydantic discriminator so
serialisation and deserialisation work without explicit tag logic.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FKAction(StrEnum):
    """``ON DELETE`` / ``ON UPDATE`` rule for a foreign key."""

    NO_ACTION = "no_action"
    RESTRICT = "restrict"
    CASCADE = "cascade"
    SET_NULL = "set_null"
    SET_DEFAULT = "set_default"


class FKMatch(StrEnum):
    """``MATCH`` clause for a foreign key (SQL standard)."""

    SIMPLE = "simple"
    PARTIAL = "partial"
    FULL = "full"


class ConstraintDeferrability(StrEnum):
    """Whether and when a constraint is checked within a transaction."""

    NOT_DEFERRABLE = "not_deferrable"
    DEFERRABLE_INITIALLY_IMMEDIATE = "deferrable_initially_immediate"
    DEFERRABLE_INITIALLY_DEFERRED = "deferrable_initially_deferred"


# ---------------------------------------------------------------------------
# Per-kind constraint models
# ---------------------------------------------------------------------------


class _ConstraintBase(BaseModel):
    """Shared fields for every constraint kind."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    """Constraint name (``pg_constraint.conname``)."""

    deferrability: ConstraintDeferrability = ConstraintDeferrability.NOT_DEFERRABLE
    """Deferral behaviour.  Most constraints are ``NOT DEFERRABLE`` (default)."""


class PrimaryKeyConstraint(_ConstraintBase):
    """``PRIMARY KEY (column, ...)`` constraint."""

    kind: Literal["primary_key"] = "primary_key"

    columns: tuple[str, ...] = Field(min_length=1)
    """Ordered column names forming the primary key.  At least one required."""

    index_method: str = "btree"
    """Index access method used to enforce the PK (almost always ``btree``)."""


class UniqueConstraint(_ConstraintBase):
    """``UNIQUE (column, ...)`` constraint."""

    kind: Literal["unique"] = "unique"

    columns: tuple[str, ...] = Field(min_length=1)
    """Ordered column names that must be unique together.  At least one required."""

    nulls_not_distinct: bool = False
    """Postgres 15+: ``NULLS NOT DISTINCT`` flag."""

    index_method: str = "btree"
    """Index access method (almost always ``btree``)."""


class CheckConstraint(_ConstraintBase):
    """``CHECK (expression)`` constraint."""

    kind: Literal["check"] = "check"

    expression: str = Field(min_length=1)
    """The boolean SQL expression, verbatim from ``pg_get_constraintdef``."""

    no_inherit: bool = False
    """``true`` when the check is not inherited by child tables."""


class ForeignKeyConstraint(_ConstraintBase):
    """``FOREIGN KEY (...) REFERENCES tgt_table (...) ...`` constraint."""

    kind: Literal["foreign_key"] = "foreign_key"

    columns: tuple[str, ...] = Field(min_length=1)
    """Local column names involved in the FK.  At least one required."""

    ref_namespace: str = Field(min_length=1)
    """Namespace (schema) of the referenced table."""

    ref_table: str = Field(min_length=1)
    """Name of the referenced table."""

    ref_columns: tuple[str, ...] = Field(min_length=1)
    """Column names in the referenced table.  Must match ``len(columns)``."""

    on_delete: FKAction = FKAction.NO_ACTION
    """Action when a referenced row is deleted."""

    on_update: FKAction = FKAction.NO_ACTION
    """Action when a referenced row is updated."""

    match_type: FKMatch = FKMatch.SIMPLE
    """``MATCH`` clause behaviour."""


class ExclusionElement(BaseModel):
    """One element of an ``EXCLUDE`` constraint: ``(column_or_expr WITH operator)``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    column_or_expr: str = Field(min_length=1)
    """The column name or expression to exclude on."""

    operator: str = Field(min_length=1)
    """The overlap operator, e.g. ``"&&"`` or ``"="``."""

    opclass: str | None = None
    """Optional operator class name (e.g. ``"gist_geometry_ops"``)."""


class ExclusionConstraint(_ConstraintBase):
    """``EXCLUDE USING method (elem WITH op, ...) WHERE predicate`` constraint."""

    kind: Literal["exclusion"] = "exclusion"

    index_method: str = Field(min_length=1)
    """Index access method, e.g. ``"gist"``, ``"btree"``."""

    elements: tuple[ExclusionElement, ...] = Field(min_length=1)
    """The ``(column WITH operator)`` elements.  At least one required."""

    predicate: str | None = None
    """Optional ``WHERE`` predicate (partial exclusion constraint)."""


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

Constraint = Annotated[
    PrimaryKeyConstraint
    | UniqueConstraint
    | CheckConstraint
    | ForeignKeyConstraint
    | ExclusionConstraint,
    Field(discriminator="kind"),
]
"""Pydantic discriminated union over all five constraint variants.

Use as a field type::

    constraints: tuple[Constraint, ...]

The ``kind`` literal field drives Pydantic's discriminator logic, so
``model_validate`` and ``model_dump`` / ``model_validate`` round-trips work
correctly without manual type routing.
"""
