"""Index-level delta subclasses (task P2-DOM-01d).

Defines concrete :class:`~pgschemadiff.domain.delta.base.DeltaBase` subclasses
for index-level DDL operations:

- :class:`CreateIndex` — ``CREATE [UNIQUE] INDEX``
- :class:`DropIndex` — ``DROP INDEX``
- :class:`ReplaceIndex` — Atomic DROP + CREATE (structural replacement)

Each subclass narrows ``op`` to ``Literal[DeltaOp.X]`` (the coarse semantic
operation) AND declares a globally-unique ``kind`` string field that acts as
the **union discriminator** for both the local :data:`IndexDelta` alias and
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
both ``CreateIndex`` and ``CreateTable`` map ``op`` to ``"create"``.  Using
``kind`` avoids that collision entirely.

``kind`` values chosen for this module:

+----------------------+---------------------+
| Class                | ``kind`` value      |
+======================+=====================+
| :class:`CreateIndex` | ``"create_index"``  |
+----------------------+---------------------+
| :class:`DropIndex`   | ``"drop_index"``    |
+----------------------+---------------------+
| :class:`ReplaceIndex`| ``"replace_index"`` |
+----------------------+---------------------+

Target / identity
-----------------
An index delta's ``target`` is always a **top-level**
:class:`~pgschemadiff.domain.identity.ObjectRef` of ``kind=ObjectKind.INDEX``.
``INDEX`` is **not** listed in :data:`~pgschemadiff.domain.identity.SUB_OBJECT_KINDS`
(which contains only COLUMN, CONSTRAINT, TRIGGER, POLICY), so ``target.parent``
must be ``None`` and the :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key`
takes the 3-tuple form::

    (namespace, index_name, op_value)

The owning table is captured inside the :class:`~pgschemadiff.domain.index.Index`
payload via ``index.table_ref``; the topo-sorter and emitter use that field to
order index deltas after the table they belong to.

Why ``ReplaceIndex`` instead of ``AlterIndex*``
-----------------------------------------------
PostgreSQL indexes are essentially **immutable** once created.  The only
structural attributes you can change in place are:

* ``ALTER INDEX … RENAME TO …`` (identity only)
* ``ALTER INDEX … SET TABLESPACE …`` (physical placement)
* ``ALTER INDEX … SET/RESET (storage_parameter …)`` (fillfactor etc.)

Any change to the **access method**, **key columns**, **operator classes**,
**sort order**, **INCLUDE columns**, **predicate** (partial index filter), or
the **uniqueness flag** requires a ``DROP INDEX`` + ``CREATE INDEX`` cycle.
Because these structural changes represent the common diff-engine output,
a single :class:`ReplaceIndex` delta carrying both ``old_index`` and
``new_index`` is more expressive and safer for the risk classifier
(``DANGEROUS`` / ``DESTRUCTIVE``) than a family of granular ``AlterIndex*``
variants that would ultimately map to the same DDL pair.

``ALTER INDEX … RENAME TO`` and ``ALTER INDEX … SET TABLESPACE`` are
deliberately **out of MVP-A scope** for this task (P2-DOM-01d).  If rename
support is required in a later task, a ``RenameIndex`` subclass following
the same pattern as :class:`~pgschemadiff.domain.delta.table.RenameTable`
would be the correct addition.

Design notes
------------
* Table / column / constraint deltas are **not** modelled here; those are
  P2-DOM-01b / P2-DOM-01c / P2-DOM-01e.
* Models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.index import Index

# ---------------------------------------------------------------------------
# CreateIndex
# ---------------------------------------------------------------------------


class CreateIndex(DeltaBase):
    """Delta for ``CREATE [UNIQUE] INDEX … ON table (…)``.

    Carries the full :class:`~pgschemadiff.domain.index.Index` aggregate so
    that the SQL emitter has all the information it needs to reconstruct the
    DDL without additional lookups (method, key columns, INCLUDE list,
    predicate, uniqueness flag, owning table reference).

    ``target`` (inherited from :class:`~pgschemadiff.domain.delta.base.DeltaBase`)
    must equal ``index.ref`` for identity consistency; the validator enforces
    this at construction time.

    ``target.kind`` must be ``ObjectKind.INDEX`` and ``target.parent`` must be
    ``None`` (index is a top-level PostgreSQL object, not a sub-object).
    ``index.ref`` itself is already validated by
    :class:`~pgschemadiff.domain.index.Index` to have ``kind=ObjectKind.INDEX``.

    The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` is therefore
    the 3-tuple ``(namespace, index_name, "create")``.

    ``kind`` is the globally-unique union discriminator for ``CreateIndex``.
    """

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_index"] = "create_index"

    index: Index
    """The new index to create.  Carries method, key columns, INCLUDE list,
    predicate, uniqueness flag, and the owning table reference."""

    @model_validator(mode="after")
    def _check_target_matches_index_ref(self) -> Self:
        if self.target != self.index.ref:
            raise ValueError(
                f"CreateIndex.target {self.target!r} must equal index.ref {self.index.ref!r}"
            )
        return self


# ---------------------------------------------------------------------------
# DropIndex
# ---------------------------------------------------------------------------


class DropIndex(DeltaBase):
    """Delta for ``DROP INDEX [CONCURRENTLY] index_name``.

    Carries the full :class:`~pgschemadiff.domain.index.Index` aggregate so
    the risk classifier and SQL emitter can inspect what is being dropped
    (e.g. whether the index is unique, whether it supports a constraint,
    which table it belongs to).

    ``target`` must equal ``index.ref``; the validator enforces this at
    construction time.

    ``kind`` is the globally-unique union discriminator for ``DropIndex``.
    """

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_index"] = "drop_index"

    index: Index
    """The index being dropped."""

    @model_validator(mode="after")
    def _check_target_matches_index_ref(self) -> Self:
        if self.target != self.index.ref:
            raise ValueError(
                f"DropIndex.target {self.target!r} must equal index.ref {self.index.ref!r}"
            )
        return self


# ---------------------------------------------------------------------------
# ReplaceIndex
# ---------------------------------------------------------------------------


class ReplaceIndex(DeltaBase):
    """Delta for an atomic ``DROP INDEX`` + ``CREATE INDEX`` replacement.

    Used when the comparator detects a structural change to an existing index
    that PostgreSQL cannot apply in place.  Any modification to the access
    method, key columns, operator classes, sort options, INCLUDE columns, or
    partial-index predicate requires a full DROP + CREATE cycle.  Rather than
    representing these as two separate deltas, :class:`ReplaceIndex` bundles
    them into a single unit so that:

    1. The **risk classifier** can assign a ``DANGEROUS`` / ``DESTRUCTIVE``
       risk level to the operation atomically.
    2. The **topo-sorter** can treat the replacement as a single node whose
       dependencies are the same as the new index.
    3. The **SQL emitter** can choose to emit ``CREATE INDEX CONCURRENTLY``
       (which requires a separate transaction from ``DROP INDEX``) or a plain
       sequential pair.

    Validators
    ----------
    * ``target`` must equal ``new_index.ref`` (the new index is the canonical
      identity after the replacement).
    * ``old_index.ref`` must equal ``new_index.ref`` — both sides must name the
      **same index** (same namespace and name).  A replacement that changes the
      index name is expressed as a ``DropIndex`` + ``CreateIndex`` pair, not a
      ``ReplaceIndex``.
    * ``old_index != new_index`` — a replacement where nothing changes is a
      no-op and is rejected at construction time to prevent silent bugs in
      comparators.

    ``kind`` is the globally-unique union discriminator for ``ReplaceIndex``.
    """

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_index"] = "replace_index"

    old_index: Index
    """The index as it exists in the source schema (before the replacement)."""

    new_index: Index
    """The index as it should exist in the target schema (after the replacement)."""

    @model_validator(mode="after")
    def _check_replace_consistency(self) -> Self:
        # target must identify the new index
        if self.target != self.new_index.ref:
            raise ValueError(
                f"ReplaceIndex.target {self.target!r} must equal "
                f"new_index.ref {self.new_index.ref!r}"
            )
        # old_index and new_index must share the same identity (same index, just changed)
        if self.old_index.ref != self.new_index.ref:
            raise ValueError(
                f"ReplaceIndex.old_index.ref {self.old_index.ref!r} must equal "
                f"new_index.ref {self.new_index.ref!r}; "
                "a rename is expressed as DropIndex + CreateIndex, not ReplaceIndex"
            )
        # reject a no-op replacement
        if self.old_index == self.new_index:
            raise ValueError(
                "ReplaceIndex.old_index and new_index are identical; "
                "a no-op replacement is not permitted"
            )
        return self


# ---------------------------------------------------------------------------
# Discriminated union alias
# ---------------------------------------------------------------------------

IndexDelta = Annotated[
    CreateIndex | DropIndex | ReplaceIndex,
    Field(discriminator="kind"),
]
"""Pydantic discriminated union over all three index-level delta variants.

The ``kind`` literal field drives Pydantic's discriminator logic::

    from pydantic import TypeAdapter
    from pgschemadiff.domain.delta.index import IndexDelta

    ta: TypeAdapter[IndexDelta] = TypeAdapter(IndexDelta)
    delta = ta.validate_python(
        {"kind": "create_index", "op": "create", "target": ..., "index": ...}
    )

This alias is designed to be included verbatim in the global ``Delta`` union
assembled in P2-DOM-01f.  Each ``kind`` value is globally unique across all
object categories, so there is no collision risk when the global union
discriminates on ``kind``.

Note: ``op`` (CREATE/DROP/REPLACE) is intentionally *shared* across object
categories.  Discriminating on ``op`` in the global union would raise
``TypeError`` because multiple concrete delta classes map to the same ``op``
value.  The ``kind`` field avoids this collision.
"""

__all__: list[str] = [
    "CreateIndex",
    "DropIndex",
    "IndexDelta",
    "ReplaceIndex",
]
