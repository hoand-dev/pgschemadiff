"""Domain layer — pure Pydantic models. No IO, no async, no third-party drivers."""

from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
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
from pgschemadiff.domain.extension import Extension
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
from pgschemadiff.domain.ports import MigrationWriter, SchemaInspector
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import (
    PartitionInfo,
    PartitionOf,
    PartitionStrategy,
    Table,
)

__all__ = [
    "SUB_OBJECT_KINDS",
    "CheckConstraint",
    "Column",
    "Constraint",
    "ConstraintDeferrability",
    "Database",
    "ExclusionConstraint",
    "ExclusionElement",
    "Extension",
    "FKAction",
    "FKMatch",
    "ForeignKeyConstraint",
    "GeneratedTiming",
    "IdentitySpec",
    "Index",
    "IndexKeyColumn",
    "IndexMethod",
    "MigrationWriter",
    "NullsOrder",
    "ObjectKind",
    "ObjectRef",
    "PartitionInfo",
    "PartitionOf",
    "PartitionStrategy",
    "PrimaryKeyConstraint",
    "QualifiedName",
    "Schema",
    "SchemaInspector",
    "SortOrder",
    "Table",
    "UniqueConstraint",
]
