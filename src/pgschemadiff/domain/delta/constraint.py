"""Constraint-level delta subclasses (task P2-DOM-01e).

Defines concrete :class:`~pgschemadiff.domain.delta.base.DeltaBase` subclasses
for constraint-level DDL operations:

- :class:`AddConstraint` — ``ALTER TABLE … ADD CONSTRAINT …``
- :class:`DropConstraint` — ``ALTER TABLE … DROP CONSTRAINT …``

Each subclass narrows ``op`` to ``Literal[DeltaOp.X]`` (the coarse semantic
operation) AND declares a globally-unique ``kind`` string field that acts as
the **union discriminator** for both the local :data:`ConstraintDelta` alias and
the global ``Delta`` union assembled in P2-DOM-01f.

``kind`` convention
-------------------
Every concrete delta class across *all* object categories carries a ``kind``
field whose value is globally unique — no two concrete classes in any category
(table / column / index / constraint / schema / extension / …) share the same
``kind`` string.  This guarantees that the global ``Delta`` union::

    Delta = Annotated[
        TableDelta | ColumnDelta | IndexDelta | ConstraintDelta | ...,
        Field(discriminator="kind"),
    ]

can discriminate on a single field without ambiguity.

``op`` (CREATE/DROP/ALTER/RENAME/…) is deliberately kept as a *coarse*
semantic filter — it is intentionally shared across categories.  Discriminating
a global union on ``op`` alone would raise ``TypeError`` because, for example,
both ``AddConstraint`` and ``CreateTable`` map ``op`` to ``"create"``.  Using
``kind`` avoids that collision entirely.

``kind`` values chosen for this module:

+--------------------------+------------------------+
| Class                    | ``kind`` value         |
+==========================+========================+
| :class:`AddConstraint`   | ``"add_constraint"``   |
+--------------------------+------------------------+
| :class:`DropConstraint`  | ``"drop_constraint"``  |
+--------------------------+------------------------+

Target / identity
-----------------
A constraint delta's ``target`` is always an
:class:`~pgschemadiff.domain.identity.ObjectRef` of
``kind=ObjectKind.CONSTRAINT``.  Because ``CONSTRAINT`` is listed in
:data:`~pgschemadiff.domain.identity.SUB_OBJECT_KINDS`, the
:class:`~pgschemadiff.domain.identity.ObjectRef` validator already enforces:

* ``target.parent`` is set (cannot be ``None``)
* ``target.parent.kind == ObjectKind.TABLE``

The ``sort_key`` shape for sub-objects is therefore the 4-tuple::

    (parent_namespace, parent_name, local_name, op_value)

This ensures that two constraint deltas on different tables but with the same
constraint name (e.g. ``public.users.chk_active`` vs
``public.orders.chk_active``) produce distinct sort keys.

Why Add/Drop instead of ``AlterConstraint*``
--------------------------------------------
PostgreSQL constraints are essentially **immutable** once created.  The only
in-place modifications available are:

* ``ALTER TABLE … ALTER CONSTRAINT … DEFERRABLE / NOT DEFERRABLE`` (FK and
  exclusion constraints only — changes deferral without DROP + ADD)
* ``VALIDATE CONSTRAINT`` (for NOT VALID constraints, which is an MVP-B feature)

Any change to the constraint **definition** — its columns, CHECK expression,
referenced table, ON DELETE / ON UPDATE action, match type, exclusion elements,
or uniqueness semantics — requires a ``DROP CONSTRAINT`` + ``ADD CONSTRAINT``
cycle.  Because structural constraint changes represent the common diff-engine
output, modelling them as a ``DropConstraint`` + ``AddConstraint`` pair at the
engine level is cleaner and more accurate than a family of granular
``AlterConstraint*`` variants that would ultimately map to the same DDL pair.

A ``ReplaceConstraint`` class (analogous to
:class:`~pgschemadiff.domain.delta.index.ReplaceIndex`) is deliberately
**omitted** for this task.  Unlike indexes, the diff engine produces
``DropConstraint`` + ``AddConstraint`` as separate deltas because:

1. Constraint ADD/DROP ordering relative to other deltas (e.g. column changes,
   FK references to other tables) must be handled independently by the
   topo-sorter.
2. Risk classification differs between DROP (``DESTRUCTIVE``) and ADD
   (``SAFE`` or ``WARNING`` for FKs with ``NOT VALID``).
3. The SQL emitter may choose to interleave ``NOT VALID`` + ``VALIDATE``
   across a transaction boundary for FKs; bundling old+new into one delta
   obscures that decision point.

If a future task requires atomic constraint replacement (e.g. for risk
classification), a ``ReplaceConstraint`` can be added following the
:class:`~pgschemadiff.domain.delta.index.ReplaceIndex` pattern.

Single class covers all five constraint kinds
---------------------------------------------
Rather than defining five separate ``Add*`` / ``Drop*`` classes (one per
constraint kind), a single :class:`AddConstraint` and :class:`DropConstraint`
each carry a ``constraint: Constraint`` payload — the existing
:data:`~pgschemadiff.domain.constraint.Constraint` discriminated union covers
all five variants (PK / Unique / Check / FK / Exclusion).  This keeps the delta
hierarchy flat while retaining full type information about the constraint being
added or dropped.

Design notes
------------
* Table / column / index deltas are **not** modelled here; those are
  P2-DOM-01b / P2-DOM-01c / P2-DOM-01d.
* Models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.constraint import Constraint
from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind

# ---------------------------------------------------------------------------
# AddConstraint
# ---------------------------------------------------------------------------


class AddConstraint(DeltaBase):
    """Delta for ``ALTER TABLE … ADD CONSTRAINT …``.

    Carries the full :data:`~pgschemadiff.domain.constraint.Constraint`
    (the discriminated union over PK / Unique / Check / FK / Exclusion) so
    that the SQL emitter has all the information it needs to reconstruct the
    DDL without additional lookups.

    A single :class:`AddConstraint` class covers all five constraint kinds via
    the nested ``constraint`` union.  The SQL emitter inspects
    ``constraint.kind`` to determine the exact DDL to emit.

    ``target`` (inherited from :class:`~pgschemadiff.domain.delta.base.DeltaBase`)
    must reference the constraint being added:

    * ``target.kind`` must be ``ObjectKind.CONSTRAINT`` (the
      :class:`~pgschemadiff.domain.identity.ObjectRef` validator already
      enforces that ``target.parent`` is set and that
      ``target.parent.kind == ObjectKind.TABLE``).
    * ``target.qname.name`` must equal ``constraint.name`` for identity
      consistency; the validator enforces this at construction time.

    The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` is the
    4-tuple ``(parent_namespace, parent_name, constraint_name, "create")``
    because ``CONSTRAINT`` is a sub-object kind.

    ``kind`` is the globally-unique union discriminator for ``AddConstraint``.
    """

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["add_constraint"] = "add_constraint"

    constraint: Constraint
    """The constraint to add.  One of PK / Unique / Check / FK / Exclusion."""

    @model_validator(mode="after")
    def _check_target_kind_and_name(self) -> Self:
        if self.target.kind is not ObjectKind.CONSTRAINT:
            raise ValueError(
                f"AddConstraint.target.kind must be ObjectKind.CONSTRAINT, got {self.target.kind!r}"
            )
        if self.target.qname.name != self.constraint.name:
            raise ValueError(
                f"AddConstraint.target.qname.name {self.target.qname.name!r} must equal "
                f"constraint.name {self.constraint.name!r}"
            )
        return self


# ---------------------------------------------------------------------------
# DropConstraint
# ---------------------------------------------------------------------------


class DropConstraint(DeltaBase):
    """Delta for ``ALTER TABLE … DROP CONSTRAINT …``.

    Carries the full :data:`~pgschemadiff.domain.constraint.Constraint` being
    dropped so the risk classifier and SQL emitter can inspect what is being
    removed (e.g. the constraint kind, referenced table for FKs, check
    expression for CHECK constraints).

    ``target`` must satisfy:

    * ``target.kind == ObjectKind.CONSTRAINT`` (the
      :class:`~pgschemadiff.domain.identity.ObjectRef` validator already
      enforces that ``target.parent`` is set and that
      ``target.parent.kind == ObjectKind.TABLE``).
    * ``target.qname.name == constraint.name`` for identity consistency.

    The validator enforces both constraints at construction time.

    The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` is the
    4-tuple ``(parent_namespace, parent_name, constraint_name, "drop")``.

    ``kind`` is the globally-unique union discriminator for ``DropConstraint``.
    """

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_constraint"] = "drop_constraint"

    constraint: Constraint
    """The constraint being dropped."""

    @model_validator(mode="after")
    def _check_target_kind_and_name(self) -> Self:
        if self.target.kind is not ObjectKind.CONSTRAINT:
            raise ValueError(
                f"DropConstraint.target.kind must be ObjectKind.CONSTRAINT, "
                f"got {self.target.kind!r}"
            )
        if self.target.qname.name != self.constraint.name:
            raise ValueError(
                f"DropConstraint.target.qname.name {self.target.qname.name!r} must equal "
                f"constraint.name {self.constraint.name!r}"
            )
        return self


# ---------------------------------------------------------------------------
# Discriminated union alias
# ---------------------------------------------------------------------------

ConstraintDelta = Annotated[
    AddConstraint | DropConstraint,
    Field(discriminator="kind"),
]
"""Pydantic discriminated union over both constraint-level delta variants.

The ``kind`` literal field drives Pydantic's discriminator logic::

    from pydantic import TypeAdapter
    from pgschemadiff.domain.delta.constraint import ConstraintDelta

    ta: TypeAdapter[ConstraintDelta] = TypeAdapter(ConstraintDelta)
    delta = ta.validate_python(
        {"kind": "add_constraint", "op": "create", "target": ..., "constraint": ...}
    )

This alias is designed to be included verbatim in the global ``Delta`` union
assembled in P2-DOM-01f.  Each ``kind`` value is globally unique across all
object categories, so there is no collision risk when the global union
discriminates on ``kind``.

Note: ``op`` (CREATE/DROP) is intentionally *shared* across object categories.
Discriminating on ``op`` in the global union would raise ``TypeError`` because
multiple concrete delta classes map to the same ``op`` value.  The ``kind``
field avoids this collision.
"""

__all__: list[str] = [
    "AddConstraint",
    "ConstraintDelta",
    "DropConstraint",
]
