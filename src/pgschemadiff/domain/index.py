"""Index domain model (task P1-DOM-05).

:class:`Index` represents a PostgreSQL index as introspected from
``pg_index`` / ``pg_class``.  It captures:

- The access method (btree, hash, gist, gin, brin, spgist).
- An ordered tuple of :class:`IndexKeyColumn` entries, each with sort direction,
  ``NULLS FIRST/LAST`` preference, and operator class.
- An optional ``INCLUDE`` column list.
- An optional ``WHERE`` predicate for partial indexes.
- The uniqueness flag.

All models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class IndexMethod(StrEnum):
    """PostgreSQL index access methods."""

    BTREE = "btree"
    HASH = "hash"
    GIST = "gist"
    GIN = "gin"
    BRIN = "brin"
    SPGIST = "spgist"


class SortOrder(StrEnum):
    """Sort direction for a btree index key column."""

    ASC = "asc"
    DESC = "desc"


class NullsOrder(StrEnum):
    """``NULLS FIRST`` / ``NULLS LAST`` preference for a key column."""

    FIRST = "first"
    LAST = "last"


# ---------------------------------------------------------------------------
# Index key column
# ---------------------------------------------------------------------------


class IndexKeyColumn(BaseModel):
    """One key column (or expression) in an index.

    For expression indexes, ``column_name`` is ``None`` and ``expression`` holds
    the SQL expression.  For simple column indexes, ``column_name`` is set and
    ``expression`` is ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    column_name: str | None = None
    """Column name.  ``None`` for expression-based key entries."""

    expression: str | None = None
    """SQL expression for expression indexes.  ``None`` for plain column keys."""

    opclass: str | None = None
    """Operator class name (e.g. ``"text_pattern_ops"``).  ``None`` → default."""

    sort_order: SortOrder = SortOrder.ASC
    """Sort direction.  Only meaningful for btree indexes."""

    nulls_order: NullsOrder | None = None
    """``NULLS FIRST`` / ``NULLS LAST``.  ``None`` → Postgres default
    (``NULLS LAST`` for ``ASC``, ``NULLS FIRST`` for ``DESC``)."""

    @model_validator(mode="after")
    def _check_column_or_expression(self) -> Self:
        if self.column_name is None and self.expression is None:
            raise ValueError("An IndexKeyColumn must specify either column_name or expression")
        if self.column_name is not None and self.expression is not None:
            raise ValueError("An IndexKeyColumn must not specify both column_name and expression")
        return self


# ---------------------------------------------------------------------------
# Index aggregate
# ---------------------------------------------------------------------------


class Index(BaseModel):
    """A PostgreSQL index as captured from ``pg_index`` / ``pg_class``.

    Usage example::

        from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
        from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod

        ref = ObjectRef(
            kind=ObjectKind.INDEX,
            qname=QualifiedName(namespace="public", name="users_email_idx"),
        )
        key = IndexKeyColumn(column_name="email")
        idx = Index(ref=ref, method=IndexMethod.BTREE, key_columns=(key,), unique=True)

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    """Stable identity reference.  Must be of kind ``INDEX``."""

    table_ref: ObjectRef
    """Reference to the table that owns this index.  Must be of kind ``TABLE``."""

    method: IndexMethod = IndexMethod.BTREE
    """Index access method."""

    key_columns: tuple[IndexKeyColumn, ...] = Field(min_length=1)
    """Ordered key columns (at least one required)."""

    include_columns: tuple[str, ...] = Field(default=())
    """``INCLUDE`` columns (covering index).  Empty → no ``INCLUDE`` clause."""

    unique: bool = False
    """``True`` if the index carries a uniqueness constraint."""

    predicate: str | None = None
    """``WHERE`` predicate for partial indexes, or ``None``."""

    comment: str | None = None
    """Optional ``COMMENT ON INDEX`` value."""

    @model_validator(mode="after")
    def _check_ref_kind(self) -> Self:
        if self.ref.kind is not ObjectKind.INDEX:
            raise ValueError(f"Index.ref must have kind INDEX, got {self.ref.kind!r}")
        return self

    @model_validator(mode="after")
    def _check_table_ref_kind(self) -> Self:
        if self.table_ref.kind is not ObjectKind.TABLE:
            raise ValueError(f"Index.table_ref must have kind TABLE, got {self.table_ref.kind!r}")
        return self

    @property
    def qname(self) -> QualifiedName:
        """Shortcut to ``self.ref.qname``."""
        return self.ref.qname
