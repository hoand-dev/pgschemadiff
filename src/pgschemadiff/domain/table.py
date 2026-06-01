"""Table aggregate domain model (task P1-DOM-04).

:class:`Table` is the central aggregate in the domain.  It combines:

- An :class:`~pgschemadiff.domain.identity.ObjectRef` for stable identity.
- An ordered tuple of :class:`~pgschemadiff.domain.column.Column` objects.
- A tuple of :class:`~pgschemadiff.domain.constraint.Constraint` objects.
- Optional partitioning metadata (:class:`PartitionInfo` / :class:`PartitionOf`).

Validation rules enforced by ``@model_validator``:

1. All column names in the table are unique.
2. Every column referenced by a constraint must exist in the table's column
   list.  (Applies to ``primary_key``, ``unique``, and ``foreign_key``.)
3. Columns are ordered by their ``position`` field (1-based, matching
   ``pg_attribute.attnum``).

This model is pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import (
    Constraint,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

# ---------------------------------------------------------------------------
# Partition support models
# ---------------------------------------------------------------------------


class PartitionStrategy(StrEnum):
    """PostgreSQL table partitioning strategies."""

    RANGE = "range"
    LIST = "list"
    HASH = "hash"


class PartitionInfo(BaseModel):
    """Metadata for a *partitioned* (parent) table.

    A table that is itself the partition root carries ``PartitionInfo`` to
    describe how it is partitioned.  Partition children instead carry a
    :class:`PartitionOf` reference pointing at the parent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: PartitionStrategy
    """How rows are routed to child partitions."""

    partition_key: str = Field(min_length=1)
    """The partition key expression (e.g. ``"created_at"`` or ``"(id % 4)"``).
    Stored verbatim as returned by ``pg_get_partkeydef``."""


class PartitionOf(BaseModel):
    """Reference from a partition child back to its parent table.

    Captured when a table was created with ``PARTITION OF parent_table``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_namespace: str = Field(min_length=1)
    """Namespace (schema) of the parent (partitioned) table."""

    parent_name: str = Field(min_length=1)
    """Name of the parent (partitioned) table."""

    partition_bound: str | None = None
    """The ``FOR VALUES`` clause as a string (``pg_get_expr`` output), or
    ``None`` for the default partition."""


# ---------------------------------------------------------------------------
# Table aggregate
# ---------------------------------------------------------------------------


class Table(BaseModel):
    """Aggregate root representing a PostgreSQL table.

    Usage example::

        from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
        from pgschemadiff.domain.column import Column
        from pgschemadiff.domain.constraint import PrimaryKeyConstraint
        from pgschemadiff.domain.table import Table

        ref = ObjectRef(
            kind=ObjectKind.TABLE,
            qname=QualifiedName(namespace="public", name="users"),
        )
        col_id = Column(name="id", position=1, data_type="integer", nullable=False)
        col_email = Column(name="email", position=2, data_type="text", nullable=False)
        pk = PrimaryKeyConstraint(name="users_pkey", columns=("id",))
        table = Table(ref=ref, columns=(col_id, col_email), constraints=(pk,))

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    """Stable identity reference.  Must be of kind ``TABLE``."""

    columns: tuple[Column, ...] = Field(default=())
    """Ordered tuple of columns, sorted by ``column.position``."""

    constraints: tuple[Constraint, ...] = Field(default=())
    """Table-level constraints (PK, unique, check, FK, exclusion)."""

    owner: str | None = None
    """Database role that owns the table (``pg_tables.tableowner``)."""

    tablespace: str | None = None
    """Tablespace name.  ``None`` → default tablespace."""

    partition_info: PartitionInfo | None = None
    """Present when this table is itself a partitioned table (the root)."""

    partition_of: PartitionOf | None = None
    """Present when this table is a partition of another table."""

    comment: str | None = None
    """Optional ``COMMENT ON TABLE`` value."""

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _check_ref_kind(self) -> Self:
        if self.ref.kind is not ObjectKind.TABLE:
            raise ValueError(f"Table.ref must have kind TABLE, got {self.ref.kind!r}")
        return self

    @model_validator(mode="after")
    def _check_column_name_uniqueness(self) -> Self:
        seen: set[str] = set()
        for col in self.columns:
            if col.name in seen:
                raise ValueError(
                    f"Duplicate column name {col.name!r} in table {self.ref.qname.fqn}"
                )
            seen.add(col.name)
        return self

    @model_validator(mode="after")
    def _check_constraint_columns_exist(self) -> Self:
        col_names: frozenset[str] = frozenset(c.name for c in self.columns)
        for ct in self.constraints:
            if isinstance(ct, (PrimaryKeyConstraint, UniqueConstraint, ForeignKeyConstraint)):
                columns_to_check = ct.columns
            else:
                continue

            for col_name in columns_to_check:
                if col_name not in col_names:
                    raise ValueError(
                        f"Constraint {ct.name!r} references column {col_name!r} "
                        f"which does not exist in table {self.ref.qname.fqn}"
                    )
        return self

    @model_validator(mode="after")
    def _check_not_both_partition_variants(self) -> Self:
        if self.partition_info is not None and self.partition_of is not None:
            raise ValueError(
                "A table cannot simultaneously be a partition root (partition_info) "
                "and a partition child (partition_of)"
            )
        return self

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def qname(self) -> QualifiedName:
        """Shortcut to ``self.ref.qname``."""
        return self.ref.qname

    def column_by_name(self, name: str) -> Column | None:
        """Return the column with the given name, or ``None``."""
        for col in self.columns:
            if col.name == name:
                return col
        return None
