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
* The sortable key ``sort_key`` is a ``(namespace, object_name, op_value)``
  tuple exposed as a ``@property``.  Downstream topo-sort uses it as a stable
  tie-breaker after dependency ordering; deterministic output ordering also
  relies on it.
* ``DeltaSet`` stores items in a plain ``tuple[DeltaBase, ...]`` so it stays
  frozen and value-equal.  Helper methods mirror the style established in
  :class:`~pgschemadiff.domain.database.Database`.

All models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pgschemadiff.domain.identity import ObjectRef

# ---------------------------------------------------------------------------
# DeltaOp — discriminator enum
# ---------------------------------------------------------------------------


class DeltaOp(StrEnum):
    """Discriminator values for the delta operation kind.

    These six values cover every operation the MVP-A diff engine produces.
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
    | ``NO_CHANGE`` | Sentinel used in tests and as a safe default for         |
    |               | subclasses that represent a detected-but-skipped diff.   |
    +---------------+----------------------------------------------------------+
    """

    CREATE = "create"
    DROP = "drop"
    ALTER = "alter"
    RENAME = "rename"
    REPLACE = "replace"
    NO_CHANGE = "no_change"


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
    :attr:`sort_key` is a ``(namespace, object_name, op_value)`` triple used
    as a stable secondary sort key after topological dependency ordering.
    This matches the existing convention in the domain: objects are primarily
    identified by their :class:`~pgschemadiff.domain.identity.QualifiedName`
    (namespace, name) and secondarily by the operation kind string.

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
    def sort_key(self) -> tuple[str, str, str]:
        """Stable sort key: ``(namespace, object_name, op_value)``.

        Downstream topo-sort and deterministic output ordering use this as a
        secondary key after dependency resolution.  The triple matches the
        natural human reading of a delta: "in schema X, on object Y, do Z".
        """
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
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    deltas: tuple[DeltaBase, ...] = Field(default=())
    """The ordered sequence of deltas in this set."""

    # ------------------------------------------------------------------
    # Alternative constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_iterable(cls, deltas: Iterator[DeltaBase] | list[DeltaBase]) -> DeltaSet:
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
        return tuple(d for d in self.deltas if d.op is op)

    def by_target(self, ref: ObjectRef) -> tuple[DeltaBase, ...]:
        """Return all deltas whose ``target`` matches *ref*."""
        return tuple(d for d in self.deltas if d.target == ref)

    def is_empty(self) -> bool:
        """Return ``True`` when no deltas are present."""
        return len(self.deltas) == 0
