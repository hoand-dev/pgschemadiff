"""Per-object-kind comparators for the Phase 2 diff engine (ADR-0006).

Each comparator compares the source vs. target representation of one
:class:`~pgschemadiff.domain.identity.ObjectKind` and emits the concrete
delta subclasses that describe the change.  The central
:class:`~pgschemadiff.application.diff.engine.DiffEngine` dispatches paired
objects to the matching comparator.

Public surface::

    from pgschemadiff.application.diff.comparators import (
        TableComparator,
        IndexComparator,
        ConstraintComparator,
    )

``TableComparator`` delegates sub-object diffing to injected collaborators
that satisfy the :class:`ColumnComparing` / :class:`ConstraintComparing`
structural protocols (so the column/constraint comparators plug in without a
hard import dependency).
"""

from __future__ import annotations

from pgschemadiff.application.diff.comparators.constraint import ConstraintComparator
from pgschemadiff.application.diff.comparators.index import IndexComparator
from pgschemadiff.application.diff.comparators.table import (
    ColumnComparing,
    ConstraintComparing,
    TableComparator,
)

__all__ = [
    "ColumnComparing",
    "ConstraintComparator",
    "ConstraintComparing",
    "IndexComparator",
    "TableComparator",
]
