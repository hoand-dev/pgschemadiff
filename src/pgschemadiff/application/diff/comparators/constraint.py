"""Constraint comparator — sub-object diff for table constraints (task P2-DIFF-05).

This module provides :class:`ConstraintComparator`, a focused, independently-
testable unit that compares the constraint sets of two table snapshots and emits
:class:`~pgschemadiff.domain.delta.constraint.AddConstraint` /
:class:`~pgschemadiff.domain.delta.constraint.DropConstraint` deltas.

Design notes
------------
Constraints are **sub-objects of a table**; the :class:`DiffEngine` visitor
dispatches at the table level (SCHEMA / EXTENSION / TABLE / INDEX), not at
CONSTRAINT level.  There is therefore no engine-level ``Comparator`` registration
for ``ObjectKind.CONSTRAINT``.  Instead, :class:`ConstraintComparator` exposes:

* ``kind = ObjectKind.CONSTRAINT`` — for discoverability and consistent typing.
* ``compare_sets(table_ref, source, target)`` — the primary API, called by the
  table comparator (P2-DIFF-02) which holds both the source and target
  ``Table.constraints`` tuples.

Immutability semantics (Postgres constraints are structurally immutable)
------------------------------------------------------------------------
PostgreSQL provides no ``ALTER CONSTRAINT … SET COLUMNS`` or similar DDL for
structural changes.  Any change to a constraint's definition — its columns,
CHECK expression, referenced table, ON DELETE/ON UPDATE actions, match type,
exclusion elements, uniqueness semantics — requires a ``DROP CONSTRAINT`` +
``ADD CONSTRAINT`` cycle.

Accordingly, when a constraint with the same ``name`` exists on both sides but
its definition differs (any field other than ``name`` differs), this comparator
emits **two** deltas: a :class:`DropConstraint` for the old definition followed
by an :class:`AddConstraint` for the new definition (a "replace" expressed as
drop+add).  There is no ``ReplaceConstraint`` delta class — see the rationale in
:mod:`pgschemadiff.domain.delta.constraint` for why independent Drop + Add is
preferable to an atomic Replace for the risk-classification and topo-sort steps.

Delta ordering
--------------
Deltas are emitted in **constraint-name-sorted** order (lexicographic, ascending
on ``constraint.name``).  For a replaced constraint (same name, different
definition), the ``DropConstraint`` is emitted *before* the ``AddConstraint``
so that the SQL emitter / topo-sorter always sees a logically valid sequence:
you must DROP the old before ADDing the new.

ObjectRef construction
----------------------
Each delta's ``target`` is built as::

    ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=constraint.name),
        parent=table_ref,
    )

The ``namespace`` mirrors the owning table's namespace so that the CONSTRAINT
``ObjectRef`` is fully namespaced without additional parameters.

Layer contract
--------------
Pure application layer: domain + stdlib only.  No IO, no async, no psycopg, no
infrastructure or presentation imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

if TYPE_CHECKING:
    from pgschemadiff.application.diff.renames import RenameAnnotations
    from pgschemadiff.domain.constraint import Constraint
    from pgschemadiff.domain.delta.base import DeltaBase


class ConstraintComparator:
    """Compare the constraint sets of two table snapshots.

    This comparator is a **sub-object comparator**: it is not registered with
    the :class:`~pgschemadiff.application.diff.engine.DiffEngine` (which only
    handles top-level object kinds).  Instead it is delegated to by the table
    comparator (P2-DIFF-02).

    Attributes
    ----------
    kind:
        Always ``ObjectKind.CONSTRAINT``.  Present for discoverability and to
        allow the table comparator to confirm the comparator's coverage without
        hard-coding the string.

    Usage
    -----
    ::

        from pgschemadiff.application.diff.comparators.constraint import (
            ConstraintComparator,
        )

        cmp = ConstraintComparator()
        deltas = cmp.compare_sets(
            table_ref=table.ref,
            source=source_table.constraints,
            target=target_table.constraints,
        )
    """

    kind: ObjectKind = ObjectKind.CONSTRAINT

    def compare_sets(
        self,
        table_ref: ObjectRef,
        source: tuple[Constraint, ...],
        target: tuple[Constraint, ...],
    ) -> tuple[DeltaBase, ...]:
        """Compare constraint sets without rename normalization."""
        return self._compare_sets(table_ref, table_ref, source, target, None)

    def compare_with_renames(
        self,
        source_table_ref: ObjectRef,
        target_table_ref: ObjectRef,
        source: tuple[Constraint, ...],
        target: tuple[Constraint, ...],
        renames: RenameAnnotations,
    ) -> tuple[DeltaBase, ...]:
        """Compare sets using mapped structured column/table references."""
        return self._compare_sets(
            source_table_ref,
            target_table_ref,
            source,
            target,
            renames,
        )

    def _compare_sets(
        self,
        source_table_ref: ObjectRef,
        target_table_ref: ObjectRef,
        source: tuple[Constraint, ...],
        target: tuple[Constraint, ...],
        renames: RenameAnnotations | None,
    ) -> tuple[DeltaBase, ...]:
        """Compare two constraint sets and return the ordered delta tuple.

        Matching is performed by ``constraint.name`` (case-sensitive, as
        PostgreSQL constraint names are case-sensitive within a table).

        Rules
        -----
        * Name present in *target* only → emit :class:`AddConstraint`.
        * Name present in *source* only → emit :class:`DropConstraint`.
        * Same name on both sides, **identical** definition (value equality
          across all fields) → no delta emitted.
        * Same name on both sides, **different** definition (any field differs)
          → emit :class:`DropConstraint` (old) then :class:`AddConstraint`
          (new).  There is no ``ReplaceConstraint`` delta; the two independent
          deltas allow the topo-sorter and risk-classifier to handle DROP and
          ADD separately (see module docstring for rationale).

        Ordering
        --------
        Results are sorted by ``constraint.name`` (ascending, lexicographic).
        For a replaced constraint, the :class:`DropConstraint` always precedes
        the :class:`AddConstraint`.

        Parameters
        ----------
        table_ref:
            The :class:`~pgschemadiff.domain.identity.ObjectRef` of the owning
            ``TABLE``.  Used to construct CONSTRAINT ``ObjectRef`` targets with
            the correct ``parent`` and ``namespace``.
        source:
            Constraints from the *current* (source) table snapshot.
        target:
            Constraints from the *desired* (target) table snapshot.

        Returns
        -------
        tuple[DeltaBase, ...]
            Ordered tuple of :class:`AddConstraint` and/or
            :class:`DropConstraint` deltas.  Empty when the two sets are
            identical.
        """
        source_by_name: dict[str, Constraint] = {c.name: c for c in source}
        target_by_name: dict[str, Constraint] = {c.name: c for c in target}

        all_names = sorted(set(source_by_name) | set(target_by_name))

        deltas: list[DeltaBase] = []
        for name in all_names:
            src = source_by_name.get(name)
            tgt = target_by_name.get(name)

            if src is None and tgt is not None:
                # Constraint exists only in the target — ADD it.
                deltas.append(
                    AddConstraint(
                        target=self._make_ref(target_table_ref, name),
                        constraint=tgt,
                    )
                )
            elif tgt is None and src is not None:
                # Constraint exists only in the source — DROP it.
                deltas.append(
                    DropConstraint(
                        target=self._make_ref(target_table_ref, name),
                        constraint=src,
                    )
                )
            elif (
                src is not None
                and tgt is not None
                and _normalize_constraint(src, source_table_ref, target_table_ref, renames)
                != _normalize_constraint(tgt, target_table_ref, target_table_ref, None)
            ):
                # Same name, different definition — replace (DROP old, ADD new).
                # Drop first so the topo-sorter / SQL emitter see a valid sequence.
                deltas.append(
                    DropConstraint(
                        target=self._make_ref(target_table_ref, name),
                        constraint=src,
                    )
                )
                deltas.append(
                    AddConstraint(
                        target=self._make_ref(target_table_ref, name),
                        constraint=tgt,
                    )
                )
            # else: both present and identical → no delta.

        return tuple(deltas)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_ref(table_ref: ObjectRef, constraint_name: str) -> ObjectRef:
        """Build a CONSTRAINT :class:`ObjectRef` for *constraint_name*.

        The ``namespace`` mirrors the owning table's namespace; ``parent`` is
        set to *table_ref* (which :class:`ObjectRef` validates must be of kind
        ``TABLE``).
        """
        return ObjectRef(
            kind=ObjectKind.CONSTRAINT,
            qname=QualifiedName(
                namespace=table_ref.qname.namespace,
                name=constraint_name,
            ),
            parent=table_ref,
        )


def _normalize_constraint(
    constraint: Constraint,
    source_table_ref: ObjectRef,
    target_table_ref: ObjectRef,
    renames: RenameAnnotations | None,
) -> Constraint:
    """Return comparison-only copy with explicit structured references mapped."""
    # Inherited/local ownership does not alter the constraint's semantic definition.
    updates: dict[str, object] = {"definition": None, "inherited": False}
    if renames is not None:
        local_columns = renames.column_targets(source_table_ref.qname, target_table_ref.qname)
        if hasattr(constraint, "columns"):
            updates["columns"] = tuple(local_columns.get(name, name) for name in constraint.columns)

        if constraint.kind == "foreign_key":
            source_ref = QualifiedName(
                namespace=constraint.ref_namespace, name=constraint.ref_table
            )
            target_ref = renames.map_table(source_ref)
            updates["ref_namespace"] = target_ref.namespace
            updates["ref_table"] = target_ref.name
            referenced_columns = renames.column_targets(source_ref, target_ref)
            updates["ref_columns"] = tuple(
                referenced_columns.get(name, name) for name in constraint.ref_columns
            )
    return constraint.model_copy(update=updates)


__all__: list[str] = ["ConstraintComparator"]
