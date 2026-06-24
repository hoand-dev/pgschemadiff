"""Table-level delta subclasses (task P2-DOM-01b).

Defines concrete :class:`~pgschemadiff.domain.delta.base.DeltaBase` subclasses
for table-level DDL operations:

- :class:`CreateTable` — ``CREATE TABLE``
- :class:`DropTable` — ``DROP TABLE``
- :class:`RenameTable` — ``ALTER TABLE … RENAME TO``
- :class:`AlterTableAttrs` — ``ALTER TABLE … OWNER TO`` / tablespace / comment

Each subclass narrows ``op`` to ``Literal[DeltaOp.X]`` so that:

1. Pydantic's discriminated-union routing works on the ``op`` field.
2. Type-checkers narrow the type correctly in ``isinstance`` / match branches.

The local union alias :data:`TableDelta` composes all four into a single
annotated union ready for use as a field type::

    from pgschemadiff.domain.delta.table import TableDelta

This alias will be included in the global ``Delta`` union assembled in
P2-DOM-01f.  No changes to this module are needed then — P2-DOM-01f simply
imports ``TableDelta`` and includes it in the union.

Design notes
------------
* Column / index / constraint deltas are **not** modelled here; those are
  P2-DOM-01c / P2-DOM-01d / P2-DOM-01e.
* ``AlterTableAttrs`` carries only the specific table-level attributes that
  can change independently of the table's structure (owner, tablespace,
  comment, partition_info, partition_of).  All fields are ``| None``-optional
  so a caller only populates the attrs that actually changed; the comparator
  sets a field to ``None`` when that attribute has not changed.
* Models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import QualifiedName
from pgschemadiff.domain.table import PartitionInfo, PartitionOf, Table

# ---------------------------------------------------------------------------
# CreateTable
# ---------------------------------------------------------------------------


class CreateTable(DeltaBase):
    """Delta for ``CREATE TABLE`` (or ``CREATE TABLE … PARTITION OF …``).

    Carries the full :class:`~pgschemadiff.domain.table.Table` aggregate so
    that the SQL emitter has all the information it needs to reconstruct the
    DDL without additional lookups.

    The ``target`` field (inherited from :class:`~pgschemadiff.domain.delta.base.DeltaBase`)
    mirrors ``table.ref`` for lookup/filtering purposes; callers must ensure
    they are consistent.
    """

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE

    table: Table
    """The new table to create.  Carries columns, constraints, partition info, etc."""


# ---------------------------------------------------------------------------
# DropTable
# ---------------------------------------------------------------------------


class DropTable(DeltaBase):
    """Delta for ``DROP TABLE``.

    Carries the full :class:`~pgschemadiff.domain.table.Table` aggregate so
    the risk classifier and SQL emitter can inspect what is being dropped
    (e.g. whether it has dependents, whether it is a partition).
    """

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP

    table: Table
    """The table being dropped."""


# ---------------------------------------------------------------------------
# RenameTable
# ---------------------------------------------------------------------------


class RenameTable(DeltaBase):
    """Delta for ``ALTER TABLE old_name RENAME TO new_name``.

    Renames are never inferred heuristically (ADR-0007): this delta is only
    produced when an explicit rename annotation is present in the migration
    source.

    ``target`` (on the base) must reference the table by its *old* qualified
    name so that the topo-sorter can order this delta before any deltas that
    reference the new name.
    """

    op: Literal[DeltaOp.RENAME] = DeltaOp.RENAME

    old_name: QualifiedName
    """The qualified name before the rename."""

    new_name: QualifiedName
    """The qualified name after the rename."""


# ---------------------------------------------------------------------------
# AlterTableAttrs
# ---------------------------------------------------------------------------


class AlterTableAttrs(DeltaBase):
    """Delta for table-level attribute changes that do not alter structure.

    Covers attributes that PostgreSQL exposes as separate ``ALTER TABLE``
    sub-commands rather than structural column/constraint changes:

    * ``ALTER TABLE … OWNER TO new_owner``
    * ``ALTER TABLE … SET TABLESPACE new_tablespace``
    * ``COMMENT ON TABLE … IS '…'``
    * Partition metadata (strategy / partition_of) changes are expressed
      here at the table-level; column/constraint payload is handled in
      P2-DOM-01c/d/e.

    Each optional field is ``None`` when that attribute has *not* changed.
    The comparator populates only the fields that differ; the emitter skips
    ``None`` fields.
    """

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER

    new_owner: str | None = None
    """New owner role name, or ``None`` if ownership has not changed."""

    new_tablespace: str | None = None
    """New tablespace name, or ``None`` if tablespace has not changed."""

    new_comment: str | None = None
    """New table comment, or ``None`` if the comment has not changed.

    Note: ``None`` here means "not changed", not "set to NULL".  An emitter
    that needs to *clear* a comment should use an empty string ``""`` and
    interpret that as ``COMMENT ON TABLE … IS NULL``.
    """

    new_partition_info: PartitionInfo | None = None
    """New partition root metadata, or ``None`` if not changed."""

    new_partition_of: PartitionOf | None = None
    """New partition-child reference, or ``None`` if not changed."""


# ---------------------------------------------------------------------------
# Discriminated union alias
# ---------------------------------------------------------------------------

TableDelta = Annotated[
    CreateTable | DropTable | RenameTable | AlterTableAttrs,
    Field(discriminator="op"),
]
"""Pydantic discriminated union over all four table-level delta variants.

The ``op`` literal field drives Pydantic's discriminator logic::

    from pydantic import TypeAdapter
    from pgschemadiff.domain.delta.table import TableDelta

    ta: TypeAdapter[TableDelta] = TypeAdapter(TableDelta)
    delta = ta.validate_python({"op": "create", "target": ..., "table": ...})

This alias is designed to be included verbatim in the global ``Delta`` union
assembled in P2-DOM-01f without modification.  The four ``op`` literals
(``"create"``, ``"drop"``, ``"rename"``, ``"alter"``) are distinct from any
other object-kind deltas, so there is no collision risk in the global union.
"""

__all__ = [
    "AlterTableAttrs",
    "CreateTable",
    "DropTable",
    "RenameTable",
    "TableDelta",
]
