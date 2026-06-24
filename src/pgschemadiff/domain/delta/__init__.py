"""Delta package — shared foundation for the Phase 2 diff engine.

Public surface (the only names callers should import from this package)::

    from pgschemadiff.domain.delta import DeltaBase, DeltaOp, DeltaSet
    from pgschemadiff.domain.delta import CreateTable, DropTable, RenameTable, AlterTableAttrs
    from pgschemadiff.domain.delta import TableDelta

Concrete delta subclasses land progressively across tasks P2-DOM-01b..f;
each new module is re-exported here so callers always import from the package
root rather than from internal submodules.
"""

from __future__ import annotations

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp, DeltaSet
from pgschemadiff.domain.delta.table import (
    AlterTableAttrs,
    CreateTable,
    DropTable,
    RenameTable,
    TableDelta,
)

__all__ = [
    "AlterTableAttrs",
    "CreateTable",
    "DeltaBase",
    "DeltaOp",
    "DeltaSet",
    "DropTable",
    "RenameTable",
    "TableDelta",
]
