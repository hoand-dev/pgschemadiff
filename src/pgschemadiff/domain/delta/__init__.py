"""Delta package — shared foundation for the Phase 2 diff engine.

Public surface (the only names callers should import from this package)::

    from pgschemadiff.domain.delta import DeltaBase, DeltaOp, DeltaSet
    from pgschemadiff.domain.delta import CreateTable, DropTable, RenameTable, AlterTableAttrs
    from pgschemadiff.domain.delta import TableDelta
    from pgschemadiff.domain.delta import (
        AddColumn,
        DropColumn,
        AlterColumnType,
        SetColumnDefault,
        SetColumnNullability,
        RenameColumn,
    )
    from pgschemadiff.domain.delta import ColumnDelta
    from pgschemadiff.domain.delta import CreateIndex, DropIndex, ReplaceIndex
    from pgschemadiff.domain.delta import IndexDelta
    from pgschemadiff.domain.delta import AddConstraint, DropConstraint
    from pgschemadiff.domain.delta import ConstraintDelta

Concrete delta subclasses land progressively across tasks P2-DOM-01b..f;
each new module is re-exported here so callers always import from the package
root rather than from internal submodules.
"""

from __future__ import annotations

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp, DeltaSet
from pgschemadiff.domain.delta.column import (
    AddColumn,
    AlterColumnType,
    ColumnDelta,
    DropColumn,
    RenameColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.domain.delta.constraint import (
    AddConstraint,
    ConstraintDelta,
    DropConstraint,
)
from pgschemadiff.domain.delta.index import (
    CreateIndex,
    DropIndex,
    IndexDelta,
    ReplaceIndex,
)
from pgschemadiff.domain.delta.table import (
    AlterTableAttrs,
    CreateTable,
    DropTable,
    RenameTable,
    TableDelta,
)

__all__ = [
    "AddColumn",
    "AddConstraint",
    "AlterColumnType",
    "AlterTableAttrs",
    "ColumnDelta",
    "ConstraintDelta",
    "CreateIndex",
    "CreateTable",
    "DeltaBase",
    "DeltaOp",
    "DeltaSet",
    "DropColumn",
    "DropConstraint",
    "DropIndex",
    "DropTable",
    "IndexDelta",
    "RenameColumn",
    "RenameTable",
    "ReplaceIndex",
    "SetColumnDefault",
    "SetColumnNullability",
    "TableDelta",
]
