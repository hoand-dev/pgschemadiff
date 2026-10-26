"""Application use case for comparing two inspected database schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pgschemadiff.application.diff.comparators import (
    ColumnComparator,
    CompositeTypeComparator,
    ConstraintComparator,
    DomainTypeComparator,
    EnumComparator,
    ExtensionComparator,
    FunctionComparator,
    IndexComparator,
    MaterializedViewComparator,
    ProcedureComparator,
    SchemaComparator,
    SequenceComparator,
    TableComparator,
    TriggerComparator,
    ViewComparator,
)
from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.application.diff.engine import Comparator, DiffEngine

if TYPE_CHECKING:
    from pgschemadiff.application.diff.ignore import IgnoreRules
    from pgschemadiff.application.diff.renames import RenameAnnotations
    from pgschemadiff.domain.delta import DeltaSet
    from pgschemadiff.domain.ports import SchemaInspector


async def compare_schemas(
    source_inspector: SchemaInspector,
    target_inspector: SchemaInspector,
    *,
    renames: RenameAnnotations | None = None,
    ignore: IgnoreRules | None = None,
) -> DeltaSet:
    """Inspect both databases and return their ordered typed schema changes."""
    source = await source_inspector.inspect()
    target = await target_inspector.inspect()
    source_table_owners = {
        table.ref: table.owner for schema in source.schemas for table in schema.tables
    }
    target_table_owners = {
        table.ref: table.owner for schema in target.schemas for table in schema.tables
    }

    comparators: tuple[Comparator, ...] = (
        SchemaComparator(),
        ExtensionComparator(),
        EnumComparator(),
        CompositeTypeComparator(),
        DomainTypeComparator(),
        SequenceComparator(
            source_table_owners=source_table_owners,
            target_table_owners=target_table_owners,
        ),
        FunctionComparator(target_functions=target.all_functions()),
        ProcedureComparator(),
        TriggerComparator(),
        ViewComparator(),
        MaterializedViewComparator(),
        TableComparator(
            column_comparator=ColumnComparator(),
            constraint_comparator=ConstraintComparator(),
        ),
        # IndexComparator narrows Protocol's object parameters to Index; it
        # verifies structural compliance at runtime in its module.
        cast("Comparator", IndexComparator()),
    )
    engine = DiffEngine(comparators=comparators)
    return order_deltas(engine.diff(source, target, renames=renames, ignore=ignore))
