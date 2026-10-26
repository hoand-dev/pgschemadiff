"""Application use case for comparing two inspected database schemas."""

from __future__ import annotations

from dataclasses import dataclass
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
    PolicyComparator,
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
    from pgschemadiff.domain.database import Database
    from pgschemadiff.domain.delta import DeltaSet
    from pgschemadiff.domain.ports import SchemaInspector


@dataclass(frozen=True)
class SchemaComparisonResult:
    """Inspected database snapshots and their ordered schema differences."""

    source: Database
    target: Database
    deltas: DeltaSet


async def compare_schemas(
    source_inspector: SchemaInspector,
    target_inspector: SchemaInspector,
    *,
    renames: RenameAnnotations | None = None,
    ignore: IgnoreRules | None = None,
) -> DeltaSet:
    """Inspect and compare both databases, returning only their ordered changes."""
    result = await compare_schemas_with_snapshots(
        source_inspector,
        target_inspector,
        renames=renames,
        ignore=ignore,
    )
    return result.deltas


async def compare_schemas_with_snapshots(
    source_inspector: SchemaInspector,
    target_inspector: SchemaInspector,
    *,
    renames: RenameAnnotations | None = None,
    ignore: IgnoreRules | None = None,
) -> SchemaComparisonResult:
    """Inspect both databases and return snapshots with ordered typed changes."""
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
        PolicyComparator(),
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
    deltas = order_deltas(engine.diff(source, target, renames=renames, ignore=ignore))
    return SchemaComparisonResult(source=source, target=target, deltas=deltas)
