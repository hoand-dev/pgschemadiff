"""Table-level delta subclasses (task P2-DOM-01b).

Defines concrete :class:`~pgschemadiff.domain.delta.base.DeltaBase` subclasses
for table-level DDL operations:

- :class:`CreateTable` — ``CREATE TABLE``
- :class:`DropTable` — ``DROP TABLE``
- :class:`RenameTable` — ``ALTER TABLE … RENAME TO``
- :class:`AlterTableAttrs` — ``ALTER TABLE … OWNER TO`` / tablespace / comment

Each subclass narrows ``op`` to ``Literal[DeltaOp.X]`` (the coarse semantic
operation) AND declares a globally-unique ``kind`` string field that acts as
the **union discriminator** for both the local :data:`TableDelta` alias and
the global ``Delta`` union assembled in P2-DOM-01f.

``kind`` convention
-------------------
Every concrete delta class across *all* object categories carries a ``kind``
field whose value is globally unique — no two concrete classes in any category
(table / column / index / constraint / schema / extension / …) share the same
``kind`` string.  This guarantees that the global ``Delta`` union::

    Delta = Annotated[
        TableDelta | IndexDelta | SchemaDelta | ...,
        Field(discriminator="kind"),
    ]

can discriminate on a single field without ambiguity.

``op`` (CREATE/DROP/ALTER/RENAME/…) is deliberately kept as a *coarse*
semantic filter — it is intentionally shared across categories.  Discriminating
a global union on ``op`` alone would raise ``TypeError`` because, for example,
both ``CreateTable`` and ``CreateIndex`` map ``op`` to ``"create"``.  Using
``kind`` avoids that collision entirely.

``kind`` values chosen for this module:

+---------------------+--------------------+
| Class               | ``kind`` value     |
+=====================+====================+
| :class:`CreateTable`| ``"create_table"`` |
+---------------------+--------------------+
| :class:`DropTable`  | ``"drop_table"``   |
+---------------------+--------------------+
| :class:`RenameTable`| ``"rename_table"`` |
+---------------------+--------------------+
| :class:`AlterTableAttrs` | ``"alter_table_attrs"`` |
+---------------------+--------------------+

The local union alias :data:`TableDelta` composes all four into a single
annotated union ready for use as a field type::

    from pgschemadiff.domain.delta.table import TableDelta

This alias is included in the global ``Delta`` union assembled in P2-DOM-01f.
P2-DOM-01f simply imports ``TableDelta`` and includes it in the outer union.

Design notes
------------
* Column / index / constraint deltas are **not** modelled here; those are
  P2-DOM-01c / P2-DOM-01d / P2-DOM-01e.
* ``AlterTableAttrs`` carries only the specific table-level attributes that
  can change independently of the table's structure (owner, tablespace,
  comment, partition_info, partition_of).  All fields are ``| None``-optional
  so a caller only populates the attrs that actually changed; the comparator
  sets a field to ``None`` when that attribute has not changed.  At least one
  must be non-``None`` (enforced by validator).
* Models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

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

    ``target`` (inherited from :class:`~pgschemadiff.domain.delta.base.DeltaBase`)
    must equal ``table.ref`` for identity consistency; the validator enforces
    this at construction time.

    ``kind`` is the globally-unique union discriminator for ``CreateTable``.
    """

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_table"] = "create_table"

    table: Table
    """The new table to create.  Carries columns, constraints, partition info, etc."""

    @model_validator(mode="after")
    def _check_target_matches_table_ref(self) -> Self:
        if self.target != self.table.ref:
            raise ValueError(
                f"CreateTable.target {self.target!r} must equal table.ref {self.table.ref!r}"
            )
        return self


# ---------------------------------------------------------------------------
# DropTable
# ---------------------------------------------------------------------------


class DropTable(DeltaBase):
    """Delta for ``DROP TABLE``.

    Carries the full :class:`~pgschemadiff.domain.table.Table` aggregate so
    the risk classifier and SQL emitter can inspect what is being dropped
    (e.g. whether it has dependents, whether it is a partition).

    ``target`` must equal ``table.ref``; the validator enforces this at
    construction time.

    ``kind`` is the globally-unique union discriminator for ``DropTable``.
    """

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_table"] = "drop_table"

    table: Table
    """The table being dropped."""

    @model_validator(mode="after")
    def _check_target_matches_table_ref(self) -> Self:
        if self.target != self.table.ref:
            raise ValueError(
                f"DropTable.target {self.target!r} must equal table.ref {self.table.ref!r}"
            )
        return self


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
    reference the new name.  The validator asserts ``target.qname == old_name``
    and that ``old_name != new_name`` (a no-op rename is rejected).

    ``kind`` is the globally-unique union discriminator for ``RenameTable``.
    """

    op: Literal[DeltaOp.RENAME] = DeltaOp.RENAME
    kind: Literal["rename_table"] = "rename_table"

    old_name: QualifiedName
    """The qualified name before the rename."""

    new_name: QualifiedName
    """The qualified name after the rename."""

    @model_validator(mode="after")
    def _check_rename_consistency(self) -> Self:
        if self.target.qname != self.old_name:
            raise ValueError(
                f"RenameTable.target.qname {self.target.qname!r} must equal "
                f"old_name {self.old_name!r}"
            )
        if self.old_name == self.new_name:
            raise ValueError(
                f"RenameTable.old_name and new_name are identical ({self.old_name!r}); "
                "a no-op rename is not permitted"
            )
        return self


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
    ``None`` fields.  At least one field must be non-``None`` (enforced by
    validator) — an all-``None`` ``AlterTableAttrs`` is semantically a no-op
    and is rejected at construction time.

    ``kind`` is the globally-unique union discriminator for ``AlterTableAttrs``.
    """

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_table_attrs"] = "alter_table_attrs"

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

    @model_validator(mode="after")
    def _check_at_least_one_change(self) -> Self:
        if (
            self.new_owner is None
            and self.new_tablespace is None
            and self.new_comment is None
            and self.new_partition_info is None
            and self.new_partition_of is None
        ):
            raise ValueError(
                "AlterTableAttrs must change at least one attribute; "
                "all five new_* fields are None (no-op)"
            )
        return self


# ---------------------------------------------------------------------------
# Discriminated union alias
# ---------------------------------------------------------------------------

TableDelta = Annotated[
    CreateTable | DropTable | RenameTable | AlterTableAttrs,
    Field(discriminator="kind"),
]
"""Pydantic discriminated union over all four table-level delta variants.

The ``kind`` literal field drives Pydantic's discriminator logic::

    from pydantic import TypeAdapter
    from pgschemadiff.domain.delta.table import TableDelta

    ta: TypeAdapter[TableDelta] = TypeAdapter(TableDelta)
    delta = ta.validate_python(
        {"kind": "create_table", "op": "create", "target": ..., "table": ...}
    )

This alias is designed to be included verbatim in the global ``Delta`` union
assembled in P2-DOM-01f.  Each ``kind`` value is globally unique across all
object categories, so there is no collision risk when the global union
discriminates on ``kind``.

Note: ``op`` (CREATE/DROP/RENAME/ALTER) is intentionally *shared* across
object categories.  Discriminating on ``op`` in the global union would raise
``TypeError`` because multiple concrete delta classes map to the same ``op``
value.  The ``kind`` field avoids this collision.
"""

__all__ = [
    "AlterTableAttrs",
    "CreateTable",
    "DropTable",
    "RenameTable",
    "TableDelta",
]
