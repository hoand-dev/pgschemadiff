"""Shared foundation for all delta (diff-result) types (task P2-DOM-01a).

This module defines the three building blocks that every concrete delta
subclass and its consumers depend on:

- :class:`DeltaOp` — a :class:`~enum.StrEnum` discriminator that names the
  *kind of change* captured by a delta (CREATE, DROP, ALTER, RENAME, REPLACE).
- :class:`DeltaBase` — the frozen Pydantic v2 base model every concrete delta
  inherits from.  It carries the discriminator field ``op`` and the target
  object reference ``target``.  Concrete subclasses narrow ``op`` to
  ``Literal[DeltaOp.X]`` and add change-specific payload fields.
- :class:`DeltaSet` — an ordered, immutable container of deltas that the diff
  engine, topo-sorter, risk classifier, and SQL emitter all pass around.

Design notes
------------
* ``DeltaOp`` is intentionally minimal: CREATE / DROP / ALTER / RENAME /
  REPLACE cover every operation the MVP-A comparators need.  Subclass-specific
  discriminators (e.g. ``ADD_COLUMN``, ``DROP_COLUMN``) are expressed as
  concrete :class:`DeltaBase` subclasses whose ``Literal[DeltaOp.ALTER]`` ``op``
  combined with a ``kind`` field on the subclass narrows the type further —
  avoiding ``DeltaOp`` enum explosion while keeping the discriminated-union
  story clean.
* The sortable key ``sort_key`` is a collision-free tuple exposed as a
  ``@property``.  Downstream topo-sort uses it as a stable tie-breaker after
  dependency ordering; deterministic output ordering also relies on it.
  See :attr:`DeltaBase.sort_key` for the exact shape.
* ``DeltaSet`` stores items in a plain ``tuple[DeltaBase, ...]`` so it stays
  frozen and value-equal.  Helper methods mirror the style established in
  :class:`~pgschemadiff.domain.database.Database`.

All models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pgschemadiff.domain.identity import ObjectRef

# ---------------------------------------------------------------------------
# DeltaOp — discriminator enum
# ---------------------------------------------------------------------------


class DeltaOp(StrEnum):
    """Discriminator values for the delta operation kind.

    These five values cover every operation the MVP-A diff engine produces.
    Subclass payload fields (e.g. ``new_type``, ``new_name``) carry the
    operation-specific details; the ``op`` field tells consumers *which kind
    of change* they are looking at without inspecting those payload fields.

    +---------------+----------------------------------------------------------+
    | Member        | Typical DDL                                              |
    +===============+==========================================================+
    | ``CREATE``    | ``CREATE TABLE``, ``CREATE INDEX``, ``CREATE SCHEMA`` …  |
    +---------------+----------------------------------------------------------+
    | ``DROP``      | ``DROP TABLE``, ``DROP COLUMN`` …                        |
    +---------------+----------------------------------------------------------+
    | ``ALTER``     | Any structural modification that is not a rename or      |
    |               | full-object replacement (e.g. change column type,        |
    |               | add/drop NOT NULL, change default, …)                    |
    +---------------+----------------------------------------------------------+
    | ``RENAME``    | ``ALTER … RENAME TO …`` (requires explicit annotation    |
    |               | per ADR-0007; never inferred heuristically).             |
    +---------------+----------------------------------------------------------+
    | ``REPLACE``   | Full-object replacement — semantically equivalent to     |
    |               | DROP + CREATE but treated as a single delta so the risk  |
    |               | classifier can assign ``DESTRUCTIVE`` / ``BLOCKED``      |
    |               | atomically.                                              |
    +---------------+----------------------------------------------------------+
    """

    CREATE = "create"
    DROP = "drop"
    ALTER = "alter"
    RENAME = "rename"
    REPLACE = "replace"


# ---------------------------------------------------------------------------
# DeltaBase — common base for every concrete delta
# ---------------------------------------------------------------------------


class DeltaBase(BaseModel):
    """Common base for all concrete delta subclasses.

    Every delta produced by a comparator inherits from this class and
    narrows the ``op`` field to ``Literal[DeltaOp.X]`` so that the
    Pydantic discriminated union works correctly.

    Fields
    ------
    op:
        The operation kind.  Must match the ``Literal`` annotation in the
        concrete subclass so Pydantic can route deserialization correctly.
    target:
        The :class:`~pgschemadiff.domain.identity.ObjectRef` that identifies
        the PostgreSQL object being changed.  The ``target.qname`` carries the
        namespace + name pair; ``target.kind`` identifies the object category.

    Sortable key
    ------------
    :attr:`sort_key` is a collision-free, lexicographically comparable tuple of
    strings.  Its exact shape depends on whether the target is a top-level
    object or a sub-object (column, constraint, trigger, policy):

    * Top-level object::

        (namespace, object_name, op_value)

    * Sub-object (``target.parent`` is set)::

        (parent_namespace, parent_name, local_name, op_value)

    Folding the parent identity into the key ensures that two sub-object deltas
    on different parents — e.g. column ``public.users.id`` vs column
    ``public.orders.id`` — never collide (both would be ``("public", "id",
    "alter")`` without the parent components).  Downstream topo-sort tie-
    breaking (P2-DIFF-08) depends on this being a *total*, collision-free
    ordering key.

    Usage example::

        from typing import Literal
        from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
        from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName


        class CreateTableDelta(DeltaBase):
            op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE


        ref = ObjectRef(
            kind=ObjectKind.TABLE,
            qname=QualifiedName(namespace="public", name="users"),
        )
        delta = CreateTableDelta(op=DeltaOp.CREATE, target=ref)
        assert delta.sort_key == ("public", "users", "create")

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: DeltaOp
    """The operation kind.  Narrowed to ``Literal[DeltaOp.X]`` in subclasses."""

    target: ObjectRef
    """The object being changed."""

    @property
    def sort_key(self) -> tuple[str, ...]:
        """Stable, collision-free sort key for topo-sort tie-breaking.

        Shape:
        * Top-level object: ``(namespace, object_name, op_value)``
        * Sub-object (target.parent is set):
          ``(parent_namespace, parent_name, local_name, op_value)``

        The parent components are placed *before* the local name so that
        sub-objects of the same parent sort together, and so that two
        sub-objects with identical local names on different parents (e.g.
        ``public.users.id`` vs ``public.orders.id``) produce distinct keys.
        """
        if self.target.parent is not None:
            # Sub-object: fold parent identity in before the local name.
            return (
                self.target.parent.qname.namespace,
                self.target.parent.qname.name,
                self.target.qname.name,
                self.op.value,
            )
        return (
            self.target.qname.namespace,
            self.target.qname.name,
            self.op.value,
        )


# ---------------------------------------------------------------------------
# DeltaSet — ordered container of deltas
# ---------------------------------------------------------------------------


class DeltaSet(BaseModel):
    """Ordered, immutable container of :class:`DeltaBase` instances.

    :class:`DeltaSet` is the unit of exchange between the diff engine, the
    topo-sorter, the risk classifier, and the SQL emitter.  It wraps a
    ``tuple`` so it stays frozen and value-equal.

    Construction
    ------------
    Pass an iterable of deltas to the constructor::

        from pgschemadiff.domain.delta import DeltaSet

        ds = DeltaSet(deltas=(delta_a, delta_b))

    Or use the :meth:`from_iterable` convenience constructor::

        ds = DeltaSet.from_iterable([delta_a, delta_b])

    Helpers mirror the style established in
    :class:`~pgschemadiff.domain.database.Database`.

    Round-trip note
    ---------------
    .. TODO(P2-DOM-01f): Once the concrete delta subclasses (P2-DOM-01b..e)
       and the discriminated ``Delta`` union (P2-DOM-01f) land, ``deltas``
       will be retyped to ``tuple[Delta, ...]`` where ``Delta`` is an
       ``Annotated`` discriminated union alias keyed on ``op`` (and/or a
       secondary ``kind`` discriminator on subclasses).  Until then, a
       ``model_dump_json()`` → ``model_validate_json()`` round-trip only
       preserves the *base-level* fields (``op`` + ``target``); any
       subclass-specific payload fields are **not** preserved because Pydantic
       cannot know which concrete subclass to instantiate without the
       discriminator.  This limitation is intentional and documented by the
       round-trip unit tests in ``tests/unit/domain/delta/test_base.py``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # TODO(P2-DOM-01f): retype to tuple[Delta, ...] once the discriminated
    # Delta union is defined.  Until then DeltaSet round-trips items as
    # DeltaBase (subclass payload not preserved through JSON serialisation).
    deltas: tuple[DeltaBase, ...] = Field(default=())
    """The ordered sequence of deltas in this set."""

    # ------------------------------------------------------------------
    # Alternative constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_iterable(cls, deltas: Iterable[DeltaBase]) -> DeltaSet:
        """Construct a :class:`DeltaSet` from any iterable of deltas."""
        return cls(deltas=tuple(deltas))

    # ------------------------------------------------------------------
    # Container protocol
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.deltas)

    def __iter__(self) -> Iterator[DeltaBase]:  # type: ignore[override]
        # Pydantic's BaseModel.__iter__ yields (field_name, value) pairs for
        # model serialisation.  DeltaSet intentionally overrides that with
        # delta-item iteration, which is the only useful semantic here.
        return iter(self.deltas)

    def __contains__(self, item: object) -> bool:
        return item in self.deltas

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def by_op(self, op: DeltaOp) -> tuple[DeltaBase, ...]:
        """Return all deltas whose ``op`` matches *op*."""
        return tuple(d for d in self.deltas if d.op == op)

    def by_target(self, ref: ObjectRef) -> tuple[DeltaBase, ...]:
        """Return all deltas whose ``target`` matches *ref*."""
        return tuple(d for d in self.deltas if d.target == ref)

    def is_empty(self) -> bool:
        """Return ``True`` when no deltas are present."""
        return len(self.deltas) == 0
