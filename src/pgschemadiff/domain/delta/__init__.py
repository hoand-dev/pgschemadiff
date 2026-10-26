"""Delta package — shared foundation for the Phase 2 diff engine.

Public surface (the only names callers should import from this package)::

    from pgschemadiff.domain.delta import DeltaBase, DeltaOp, DeltaSet
    from pgschemadiff.domain.delta import Delta
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
    from pgschemadiff.domain.delta import CreateSchema, DropSchema
    from pgschemadiff.domain.delta import SchemaDelta
    from pgschemadiff.domain.delta import CreateExtension, DropExtension, AlterExtension
    from pgschemadiff.domain.delta import ExtensionDelta

Concrete delta subclasses landed progressively across tasks P2-DOM-01b..f;
all modules are re-exported here so callers always import from the package
root rather than from internal submodules.
"""

from __future__ import annotations

from pgschemadiff.domain.delta.base import Delta, DeltaBase, DeltaOp, DeltaSet
from pgschemadiff.domain.delta.column import (
    AddColumn,
    AlterColumnType,
    ColumnDelta,
    DropColumn,
    RenameColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.domain.delta.composite_type import (
    AlterCompositeAddAttribute,
    AlterCompositeAttributeType,
    AlterCompositeDropAttribute,
    AlterCompositeTypeAttrs,
    CompositeTypeDelta,
    CreateCompositeType,
    DropCompositeType,
    ReplaceCompositeType,
)
from pgschemadiff.domain.delta.constraint import (
    AddConstraint,
    ConstraintDelta,
    DropConstraint,
)
from pgschemadiff.domain.delta.domain_type import (
    AddDomainCheck,
    AlterDomainAttrs,
    AlterDomainDefault,
    AlterDomainNullability,
    CreateDomain,
    DomainTypeDelta,
    DropDomain,
    DropDomainCheck,
    ReplaceDomainType,
    ValidateDomainCheck,
)
from pgschemadiff.domain.delta.enum import (
    AddEnumValue,
    AlterEnumAttrs,
    CreateEnum,
    DropEnum,
    EnumDelta,
    ReplaceEnumLabels,
)
from pgschemadiff.domain.delta.function import (
    AlterFunctionOwner,
    CreateFunction,
    DropFunction,
    FunctionDelta,
    ReplaceFunction,
)
from pgschemadiff.domain.delta.index import (
    CreateIndex,
    DropIndex,
    IndexDelta,
    ReplaceIndex,
)
from pgschemadiff.domain.delta.materialized_view import (
    AlterMaterializedViewOwner,
    CreateMaterializedView,
    DropMaterializedView,
    MaterializedViewDelta,
    ReplaceMaterializedView,
)
from pgschemadiff.domain.delta.policy import (
    AlterPolicy,
    CreatePolicy,
    DropPolicy,
    PolicyDelta,
    ReplacePolicy,
)
from pgschemadiff.domain.delta.procedure import (
    AlterProcedureOwner,
    CreateProcedure,
    DropProcedure,
    ProcedureDelta,
    ReplaceProcedure,
)
from pgschemadiff.domain.delta.schema import (
    AlterExtension,
    CreateExtension,
    CreateSchema,
    DropExtension,
    DropSchema,
    ExtensionDelta,
    SchemaDelta,
)
from pgschemadiff.domain.delta.sequence import (
    AlterSequenceOptions,
    AlterSequenceOwnedBy,
    AlterSequenceOwner,
    CreateSequence,
    DropSequence,
    SequenceDelta,
)
from pgschemadiff.domain.delta.table import (
    AlterTableAttrs,
    CreateTable,
    DropTable,
    RenameTable,
    TableDelta,
)
from pgschemadiff.domain.delta.trigger import (
    AlterTriggerEnabled,
    CreateTrigger,
    DropTrigger,
    ReplaceTrigger,
    TriggerDelta,
)
from pgschemadiff.domain.delta.view import (
    AlterViewOwner,
    CreateView,
    DropView,
    ReplaceView,
    ViewDelta,
)

__all__ = [
    "AddColumn",
    "AddConstraint",
    "AddDomainCheck",
    "AddEnumValue",
    "AlterColumnType",
    "AlterCompositeAddAttribute",
    "AlterCompositeAttributeType",
    "AlterCompositeDropAttribute",
    "AlterCompositeTypeAttrs",
    "AlterDomainAttrs",
    "AlterDomainDefault",
    "AlterDomainNullability",
    "AlterEnumAttrs",
    "AlterExtension",
    "AlterFunctionOwner",
    "AlterMaterializedViewOwner",
    "AlterPolicy",
    "AlterProcedureOwner",
    "AlterSequenceOptions",
    "AlterSequenceOwnedBy",
    "AlterSequenceOwner",
    "AlterTableAttrs",
    "AlterTriggerEnabled",
    "AlterViewOwner",
    "ColumnDelta",
    "CompositeTypeDelta",
    "ConstraintDelta",
    "CreateCompositeType",
    "CreateDomain",
    "CreateEnum",
    "CreateExtension",
    "CreateFunction",
    "CreateIndex",
    "CreateMaterializedView",
    "CreatePolicy",
    "CreateProcedure",
    "CreateSchema",
    "CreateSequence",
    "CreateTable",
    "CreateTrigger",
    "CreateView",
    "Delta",
    "DeltaBase",
    "DeltaOp",
    "DeltaSet",
    "DomainTypeDelta",
    "DropColumn",
    "DropCompositeType",
    "DropConstraint",
    "DropDomain",
    "DropDomainCheck",
    "DropEnum",
    "DropExtension",
    "DropFunction",
    "DropIndex",
    "DropMaterializedView",
    "DropPolicy",
    "DropProcedure",
    "DropSchema",
    "DropSequence",
    "DropTable",
    "DropTrigger",
    "DropView",
    "EnumDelta",
    "ExtensionDelta",
    "FunctionDelta",
    "IndexDelta",
    "MaterializedViewDelta",
    "PolicyDelta",
    "ProcedureDelta",
    "RenameColumn",
    "RenameTable",
    "ReplaceCompositeType",
    "ReplaceDomainType",
    "ReplaceEnumLabels",
    "ReplaceFunction",
    "ReplaceIndex",
    "ReplaceMaterializedView",
    "ReplacePolicy",
    "ReplaceProcedure",
    "ReplaceTrigger",
    "ReplaceView",
    "SchemaDelta",
    "SequenceDelta",
    "SetColumnDefault",
    "SetColumnNullability",
    "TableDelta",
    "TriggerDelta",
    "ValidateDomainCheck",
    "ViewDelta",
]
