"""Per-object-kind comparators for the Phase 2 diff engine (ADR-0006).

Each comparator compares the source vs. target representation of one
:class:`~pgschemadiff.domain.identity.ObjectKind` and emits the concrete
delta subclasses that describe the change.  The central
:class:`~pgschemadiff.application.diff.engine.DiffEngine` dispatches paired
objects to the matching comparator.

Public surface::

    from pgschemadiff.application.diff.comparators import (
        ColumnComparator,
        TableComparator,
        IndexComparator,
        ConstraintComparator,
        SchemaComparator,
        ExtensionComparator,
    )

``TableComparator`` delegates sub-object diffing to injected collaborators
that satisfy the :class:`ColumnComparing` / :class:`ConstraintComparing`
structural protocols (so the column/constraint comparators plug in without a
hard import dependency).
"""

from __future__ import annotations

from pgschemadiff.application.diff.comparators.column import ColumnComparator
from pgschemadiff.application.diff.comparators.composite_type import CompositeTypeComparator
from pgschemadiff.application.diff.comparators.constraint import ConstraintComparator
from pgschemadiff.application.diff.comparators.domain_type import DomainTypeComparator
from pgschemadiff.application.diff.comparators.enum import EnumComparator
from pgschemadiff.application.diff.comparators.extension import ExtensionComparator
from pgschemadiff.application.diff.comparators.function import FunctionComparator
from pgschemadiff.application.diff.comparators.index import IndexComparator
from pgschemadiff.application.diff.comparators.materialized_view import MaterializedViewComparator
from pgschemadiff.application.diff.comparators.procedure import ProcedureComparator
from pgschemadiff.application.diff.comparators.schema import SchemaComparator
from pgschemadiff.application.diff.comparators.sequence import SequenceComparator
from pgschemadiff.application.diff.comparators.table import (
    ColumnComparing,
    ConstraintComparing,
    TableComparator,
)
from pgschemadiff.application.diff.comparators.view import ViewComparator

__all__ = [
    "ColumnComparator",
    "ColumnComparing",
    "CompositeTypeComparator",
    "ConstraintComparator",
    "ConstraintComparing",
    "DomainTypeComparator",
    "EnumComparator",
    "ExtensionComparator",
    "FunctionComparator",
    "IndexComparator",
    "MaterializedViewComparator",
    "ProcedureComparator",
    "SchemaComparator",
    "SequenceComparator",
    "TableComparator",
    "ViewComparator",
]
