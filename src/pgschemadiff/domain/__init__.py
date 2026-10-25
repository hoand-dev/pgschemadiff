"""Domain layer — pure Pydantic models. No IO, no async, no third-party drivers."""

from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    Constraint,
    ConstraintDeferrability,
    ExclusionConstraint,
    ExclusionElement,
    FKAction,
    FKMatch,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.domain_type import DomainCheck, DomainType
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import (
    SUB_OBJECT_KINDS,
    ObjectKind,
    ObjectRef,
    QualifiedName,
)
from pgschemadiff.domain.index import (
    Index,
    IndexKeyColumn,
    IndexMethod,
    NullsOrder,
    SortOrder,
)
from pgschemadiff.domain.materialized_view import MaterializedView
from pgschemadiff.domain.ports import SchemaInspector
from pgschemadiff.domain.procedure import Procedure, ProcedureArgument
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import (
    PartitionInfo,
    PartitionOf,
    PartitionStrategy,
    Table,
)
from pgschemadiff.domain.view import View

__all__ = [
    "SUB_OBJECT_KINDS",
    "CheckConstraint",
    "Column",
    "CompositeAttribute",
    "CompositeType",
    "Constraint",
    "ConstraintDeferrability",
    "Database",
    "DomainCheck",
    "DomainType",
    "EnumType",
    "ExclusionConstraint",
    "ExclusionElement",
    "Extension",
    "FKAction",
    "FKMatch",
    "ForeignKeyConstraint",
    "Function",
    "FunctionArgument",
    "GeneratedTiming",
    "IdentitySpec",
    "Index",
    "IndexKeyColumn",
    "IndexMethod",
    "MaterializedView",
    "NullsOrder",
    "ObjectKind",
    "ObjectRef",
    "PartitionInfo",
    "PartitionOf",
    "PartitionStrategy",
    "PrimaryKeyConstraint",
    "Procedure",
    "ProcedureArgument",
    "QualifiedName",
    "Schema",
    "SchemaInspector",
    "Sequence",
    "SortOrder",
    "Table",
    "UniqueConstraint",
    "View",
]
