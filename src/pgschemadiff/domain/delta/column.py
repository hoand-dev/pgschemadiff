"""Column-level delta subclasses (task P2-DOM-01c).

Defines concrete :class:`~pgschemadiff.domain.delta.base.DeltaBase` subclasses
for column-level DDL operations:

- :class:`AddColumn` — ``ALTER TABLE … ADD COLUMN``
- :class:`DropColumn` — ``ALTER TABLE … DROP COLUMN``
- :class:`AlterColumnType` — ``ALTER TABLE … ALTER COLUMN … TYPE …``
- :class:`SetColumnDefault` — ``ALTER TABLE … ALTER COLUMN … SET DEFAULT …``
  (or ``DROP DEFAULT`` when ``new_default`` is ``None``)
- :class:`SetColumnNullability` — ``ALTER TABLE … ALTER COLUMN … SET/DROP NOT NULL``
- :class:`RenameColumn` — ``ALTER TABLE … RENAME COLUMN … TO …``

Each subclass narrows ``op`` to ``Literal[DeltaOp.X]`` (the coarse semantic
operation) AND declares a globally-unique ``kind`` string field that acts as
the **union discriminator** for both the local :data:`ColumnDelta` alias and
the global ``Delta`` union assembled in P2-DOM-01f.

``kind`` convention
-------------------
Every concrete delta class across *all* object categories carries a ``kind``
field whose value is globally unique — no two concrete classes in any category
(table / column / index / constraint / schema / extension / …) share the same
``kind`` string.  This guarantees that the global ``Delta`` union::

    Delta = Annotated[
        TableDelta | ColumnDelta | IndexDelta | ...,
        Field(discriminator="kind"),
    ]

can discriminate on a single field without ambiguity.

``op`` (CREATE/DROP/ALTER/RENAME/…) is deliberately kept as a *coarse*
semantic filter — it is intentionally shared across categories.  Discriminating
a global union on ``op`` alone would raise ``TypeError`` because, for example,
both ``AddColumn`` and ``CreateTable`` map ``op`` to ``"create"``.  Using
``kind`` avoids that collision entirely.

``kind`` values chosen for this module:

+---------------------------+---------------------------+
| Class                     | ``kind`` value            |
+===========================+===========================+
| :class:`AddColumn`        | ``"add_column"``          |
+---------------------------+---------------------------+
| :class:`DropColumn`       | ``"drop_column"``         |
+---------------------------+---------------------------+
| :class:`AlterColumnType`  | ``"alter_column_type"``   |
+---------------------------+---------------------------+
| :class:`SetColumnDefault` | ``"set_column_default"``  |
+---------------------------+---------------------------+
| :class:`SetColumnNullability` | ``"set_column_nullability"`` |
+---------------------------+---------------------------+
| :class:`RenameColumn`     | ``"rename_column"``       |
+---------------------------+---------------------------+

Target / identity
-----------------
A column delta's ``target`` is always an :class:`~pgschemadiff.domain.identity.ObjectRef`
of ``kind=ObjectKind.COLUMN``.  Because ``COLUMN`` is a sub-object kind,
``ObjectRef``'s own validator already enforces that ``target.parent`` is set
and that ``target.parent.kind == ObjectKind.TABLE``.

The ``sort_key`` shape for sub-objects is therefore::

    (parent_namespace, parent_name, local_name, op_value)

This ensures that column deltas on different tables but with the same column
name (e.g. ``public.users.id`` vs ``public.orders.id``) produce distinct keys.

``SetColumnDefault`` semantics
------------------------------
A single class covers both ``SET DEFAULT`` and ``DROP DEFAULT`` to avoid a
proliferation of near-identical classes.  The ``new_default`` field carries the
new SQL default expression as a string, or ``None`` to signal *drop the default*
(i.e. emit ``ALTER COLUMN … DROP DEFAULT``).  The docstring of :class:`SetColumnDefault`
documents this contract explicitly.

Design notes
------------
* Table / index / constraint deltas are **not** modelled here; those are
  P2-DOM-01b / P2-DOM-01d / P2-DOM-01e.
* Models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind

# ---------------------------------------------------------------------------
# AddColumn
# ---------------------------------------------------------------------------


class AddColumn(DeltaBase):
    """Delta for ``ALTER TABLE … ADD COLUMN …``.

    Carries the full :class:`~pgschemadiff.domain.column.Column` to add so
    that the SQL emitter has all the information it needs to reconstruct the
    DDL without additional lookups.

    ``target`` (inherited from :class:`~pgschemadiff.domain.delta.base.DeltaBase`)
    must reference the column being added:

    * ``target.kind`` must be ``ObjectKind.COLUMN`` (the ``ObjectRef`` validator
      already enforces that ``target.parent`` is set to the owning table).
    * ``target.qname.name`` must equal ``column.name`` for identity consistency;
      the validator enforces this at construction time.

    ``kind`` is the globally-unique union discriminator for ``AddColumn``.
    """

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["add_column"] = "add_column"

    column: Column
    """The new column to add.  Carries data_type, nullable, default, etc."""

    @model_validator(mode="after")
    def _check_target_kind_and_name(self) -> Self:
        if self.target.kind is not ObjectKind.COLUMN:
            raise ValueError(
                f"AddColumn.target.kind must be ObjectKind.COLUMN, got {self.target.kind!r}"
            )
        if self.target.qname.name != self.column.name:
            raise ValueError(
                f"AddColumn.target.qname.name {self.target.qname.name!r} must equal "
                f"column.name {self.column.name!r}"
            )
        return self


# ---------------------------------------------------------------------------
# DropColumn
# ---------------------------------------------------------------------------


class DropColumn(DeltaBase):
    """Delta for ``ALTER TABLE … DROP COLUMN …``.

    Carries the full :class:`~pgschemadiff.domain.column.Column` being dropped
    so the risk classifier and SQL emitter can inspect what is being removed
    (e.g. type, nullability, whether it has a default).

    ``target`` must satisfy:

    * ``target.kind == ObjectKind.COLUMN``
    * ``target.qname.name == column.name``

    The validator enforces both constraints at construction time.

    ``kind`` is the globally-unique union discriminator for ``DropColumn``.
    """

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_column"] = "drop_column"

    column: Column
    """The column being dropped."""

    @model_validator(mode="after")
    def _check_target_kind_and_name(self) -> Self:
        if self.target.kind is not ObjectKind.COLUMN:
            raise ValueError(
                f"DropColumn.target.kind must be ObjectKind.COLUMN, got {self.target.kind!r}"
            )
        if self.target.qname.name != self.column.name:
            raise ValueError(
                f"DropColumn.target.qname.name {self.target.qname.name!r} must equal "
                f"column.name {self.column.name!r}"
            )
        return self


# ---------------------------------------------------------------------------
# AlterColumnType
# ---------------------------------------------------------------------------


class AlterColumnType(DeltaBase):
    """Delta for ``ALTER TABLE … ALTER COLUMN … TYPE …``.

    Carries the new data type and, optionally, a ``USING`` expression and a
    new collation.

    ``target.kind`` must be ``ObjectKind.COLUMN``; the validator enforces this.

    Semantics of optional payload fields:

    * ``new_data_type`` — required; the canonical SQL type string (same format
      as :attr:`~pgschemadiff.domain.column.Column.data_type`).
    * ``using_expression`` — optional SQL expression for ``ALTER COLUMN … TYPE
      new_type USING <expr>``.  ``None`` means no ``USING`` clause is emitted;
      the cast is implicit (valid when Postgres can infer the conversion
      automatically).
    * ``new_collation`` — optional new collation name.  ``None`` means the
      collation does not change.

    ``kind`` is the globally-unique union discriminator for ``AlterColumnType``.
    """

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_column_type"] = "alter_column_type"

    new_data_type: str = Field(min_length=1)
    """New canonical SQL type string, e.g. ``"bigint"``, ``"character varying(255)"``."""

    using_expression: str | None = None
    """Optional ``USING`` cast expression.

    When ``None``, no ``USING`` clause is emitted.  When set, the emitter
    appends ``USING <expr>`` to the ``ALTER COLUMN … TYPE …`` statement.
    """

    new_collation: str | None = None
    """Optional new collation name.

    When ``None``, the column collation does not change.
    """

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        if self.target.kind is not ObjectKind.COLUMN:
            raise ValueError(
                f"AlterColumnType.target.kind must be ObjectKind.COLUMN, got {self.target.kind!r}"
            )
        return self


# ---------------------------------------------------------------------------
# SetColumnDefault
# ---------------------------------------------------------------------------


class SetColumnDefault(DeltaBase):
    """Delta for ``ALTER TABLE … ALTER COLUMN … SET DEFAULT …`` or ``DROP DEFAULT``.

    A single class covers both ``SET DEFAULT`` and ``DROP DEFAULT`` operations
    to avoid a proliferation of near-identical delta classes.

    Semantics of ``new_default``
    ----------------------------
    * ``new_default: str`` — emit ``ALTER COLUMN <col> SET DEFAULT <expr>``.
      The value is the verbatim SQL default expression (same format as
      :attr:`~pgschemadiff.domain.column.Column.default_expr`).
    * ``new_default: None`` — emit ``ALTER COLUMN <col> DROP DEFAULT``.

    This means ``None`` in this context means *"no default should exist on the
    target column"*, not *"the default has not changed"*.  Callers that only
    want to represent an absence-of-change should not produce this delta at all.

    ``target.kind`` must be ``ObjectKind.COLUMN``; the validator enforces this.

    ``kind`` is the globally-unique union discriminator for ``SetColumnDefault``.
    """

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["set_column_default"] = "set_column_default"

    new_default: str | None
    """New default expression (``SET DEFAULT <expr>``), or ``None`` to drop it
    (``DROP DEFAULT``).  There is no sentinel for "unchanged" — do not produce
    this delta unless the default is actually changing.
    """

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        if self.target.kind is not ObjectKind.COLUMN:
            raise ValueError(
                f"SetColumnDefault.target.kind must be ObjectKind.COLUMN, got {self.target.kind!r}"
            )
        return self


# ---------------------------------------------------------------------------
# SetColumnNullability
# ---------------------------------------------------------------------------


class SetColumnNullability(DeltaBase):
    """Delta for ``ALTER TABLE … ALTER COLUMN … SET NOT NULL`` or ``DROP NOT NULL``.

    The ``nullable`` field captures the *desired* nullability of the column
    after the change:

    * ``nullable=False`` → emit ``ALTER COLUMN <col> SET NOT NULL``
    * ``nullable=True``  → emit ``ALTER COLUMN <col> DROP NOT NULL``

    ``target.kind`` must be ``ObjectKind.COLUMN``; the validator enforces this.

    ``kind`` is the globally-unique union discriminator for ``SetColumnNullability``.
    """

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["set_column_nullability"] = "set_column_nullability"

    nullable: bool
    """Desired nullability after the change.

    ``False`` → ``SET NOT NULL``; ``True`` → ``DROP NOT NULL``.
    """

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        if self.target.kind is not ObjectKind.COLUMN:
            raise ValueError(
                f"SetColumnNullability.target.kind must be ObjectKind.COLUMN, "
                f"got {self.target.kind!r}"
            )
        return self


# ---------------------------------------------------------------------------
# RenameColumn
# ---------------------------------------------------------------------------


class RenameColumn(DeltaBase):
    """Delta for ``ALTER TABLE … RENAME COLUMN old_name TO new_name``.

    Renames are never inferred heuristically (ADR-0007): this delta is only
    produced when an explicit rename annotation is present in the migration
    source.

    ``target`` (on the base) must reference the column by its *old* local name
    so that the topo-sorter can order this delta before any deltas that
    reference the new name.  Specifically:

    * ``target.kind`` must be ``ObjectKind.COLUMN``
    * ``target.qname.name`` must equal ``old_name``
    * ``old_name != new_name`` (a no-op rename is rejected)

    The validator enforces all three constraints at construction time.

    ``kind`` is the globally-unique union discriminator for ``RenameColumn``.
    """

    op: Literal[DeltaOp.RENAME] = DeltaOp.RENAME
    kind: Literal["rename_column"] = "rename_column"

    old_name: str = Field(min_length=1)
    """The local column name before the rename."""

    new_name: str = Field(min_length=1)
    """The local column name after the rename."""

    @model_validator(mode="after")
    def _check_rename_consistency(self) -> Self:
        if self.target.kind is not ObjectKind.COLUMN:
            raise ValueError(
                f"RenameColumn.target.kind must be ObjectKind.COLUMN, got {self.target.kind!r}"
            )
        if self.target.qname.name != self.old_name:
            raise ValueError(
                f"RenameColumn.target.qname.name {self.target.qname.name!r} must equal "
                f"old_name {self.old_name!r}"
            )
        if self.old_name == self.new_name:
            raise ValueError(
                f"RenameColumn.old_name and new_name are identical ({self.old_name!r}); "
                "a no-op rename is not permitted"
            )
        return self


# ---------------------------------------------------------------------------
# Discriminated union alias
# ---------------------------------------------------------------------------

ColumnDelta = Annotated[
    AddColumn
    | DropColumn
    | AlterColumnType
    | SetColumnDefault
    | SetColumnNullability
    | RenameColumn,
    Field(discriminator="kind"),
]
"""Pydantic discriminated union over all six column-level delta variants.

The ``kind`` literal field drives Pydantic's discriminator logic::

    from pydantic import TypeAdapter
    from pgschemadiff.domain.delta.column import ColumnDelta

    ta: TypeAdapter[ColumnDelta] = TypeAdapter(ColumnDelta)
    delta = ta.validate_python(
        {"kind": "add_column", "op": "create", "target": ..., "column": ...}
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
    "AddColumn",
    "AlterColumnType",
    "ColumnDelta",
    "DropColumn",
    "RenameColumn",
    "SetColumnDefault",
    "SetColumnNullability",
]
