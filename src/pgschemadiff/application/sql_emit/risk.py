"""Risk assessments and generation-limit checks for schema deltas."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from pgschemadiff.domain.constraint import ForeignKeyConstraint
from pgschemadiff.domain.delta import (
    AddColumn,
    AddConstraint,
    AddDomainCheck,
    AddEnumValue,
    AlterColumnType,
    AlterCompositeAddAttribute,
    AlterCompositeAttributeType,
    AlterCompositeDropAttribute,
    AlterCompositeTypeAttrs,
    AlterDomainAttrs,
    AlterDomainDefault,
    AlterDomainNullability,
    AlterEnumAttrs,
    AlterExtension,
    AlterTableAttrs,
    CreateCompositeType,
    CreateDomain,
    CreateEnum,
    CreateExtension,
    CreateIndex,
    CreateSchema,
    CreateTable,
    DeltaBase,
    DropColumn,
    DropCompositeType,
    DropConstraint,
    DropDomain,
    DropDomainCheck,
    DropEnum,
    DropExtension,
    DropIndex,
    DropSchema,
    DropTable,
    RenameColumn,
    RenameTable,
    ReplaceCompositeType,
    ReplaceDomainType,
    ReplaceEnumLabels,
    ReplaceIndex,
    SetColumnDefault,
    SetColumnNullability,
    ValidateDomainCheck,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName


class RiskLevel(StrEnum):
    """Ordered risk levels assigned to SQL-generating schema deltas."""

    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"
    DESTRUCTIVE = "destructive"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RiskAssessment:
    """Risk classification and rationale for one domain delta."""

    delta: DeltaBase
    level: RiskLevel
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.level, RiskLevel):
            raise TypeError("RiskAssessment.level must be a RiskLevel")
        if not self.reason.strip():
            raise ValueError("Risk assessment reason must not be blank")


_RISK_RANK = {
    RiskLevel.SAFE: 0,
    RiskLevel.WARNING: 1,
    RiskLevel.DANGEROUS: 2,
    RiskLevel.DESTRUCTIVE: 3,
    RiskLevel.BLOCKED: 4,
}

_SUPPORTED_DELTA_TYPES: tuple[type[DeltaBase], ...] = (
    CreateSchema,
    DropSchema,
    CreateExtension,
    DropExtension,
    AlterExtension,
    CreateTable,
    DropTable,
    RenameTable,
    AlterTableAttrs,
    AddColumn,
    DropColumn,
    AlterColumnType,
    SetColumnDefault,
    SetColumnNullability,
    RenameColumn,
    CreateIndex,
    DropIndex,
    ReplaceIndex,
    AddConstraint,
    DropConstraint,
    CreateEnum,
    DropEnum,
    AddEnumValue,
    AlterEnumAttrs,
    ReplaceEnumLabels,
    CreateCompositeType,
    DropCompositeType,
    AlterCompositeAddAttribute,
    AlterCompositeDropAttribute,
    AlterCompositeAttributeType,
    AlterCompositeTypeAttrs,
    ReplaceCompositeType,
    CreateDomain,
    DropDomain,
    AlterDomainDefault,
    AlterDomainNullability,
    AddDomainCheck,
    ValidateDomainCheck,
    DropDomainCheck,
    AlterDomainAttrs,
    ReplaceDomainType,
)


def passes_risk_limit(
    assessments: Iterable[RiskAssessment],
    *,
    max_risk: RiskLevel = RiskLevel.DANGEROUS,
) -> bool:
    """Return whether assessments stay within the limit and contain no BLOCKED risk."""
    return all(
        assessment.level is not RiskLevel.BLOCKED
        and _RISK_RANK[assessment.level] <= _RISK_RANK[max_risk]
        for assessment in assessments
    )


def classify_risk(  # noqa: PLR0912, PLR0915
    delta: DeltaBase,
    *,
    created_tables: frozenset[ObjectRef] = frozenset(),
) -> RiskAssessment:
    """Classify a schema delta using static risk policy and migration context."""
    if type(delta) not in _SUPPORTED_DELTA_TYPES:
        return RiskAssessment(
            delta=delta,
            level=RiskLevel.BLOCKED,
            reason="No risk policy exists for this delta type.",
        )

    if isinstance(delta, CreateSchema):
        level, reason = RiskLevel.SAFE, "Creates an empty schema."
    elif isinstance(delta, DropSchema):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes a schema and its objects."
    elif isinstance(delta, CreateExtension):
        level, reason = (
            RiskLevel.WARNING,
            "Extension installation may execute extension-provided scripts.",
        )
    elif isinstance(delta, DropExtension):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes extension-provided objects and behavior."
    elif isinstance(delta, AlterExtension):
        if delta.new_version is not None:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Extension version updates may run extension migrations.",
            )
        else:
            level, reason = (
                RiskLevel.WARNING,
                "Extension schema relocation is operationally sensitive.",
            )
    elif isinstance(delta, CreateTable):
        if delta.table.partition_of is not None:
            level, reason = (
                RiskLevel.WARNING,
                "Creating a partition child affects its parent table.",
            )
        else:
            level, reason = RiskLevel.SAFE, "Creates an empty table."
    elif isinstance(delta, DropTable):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes a table and its data."
    elif isinstance(delta, RenameTable):
        level, reason = (
            RiskLevel.WARNING,
            "Table rename requires a lock and can affect dependent application behavior.",
        )
    elif isinstance(delta, AlterTableAttrs):
        has_partition_change = (
            delta.new_partition_info is not None or delta.new_partition_of is not None
        )
        if delta.new_unlogged is not None:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Changing table persistence rewrites the table under an ACCESS EXCLUSIVE lock.",
            )
        elif has_partition_change and delta.new_tablespace is not None:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Changes partition metadata and tablespace; partition risk is highest.",
            )
        elif has_partition_change:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Changes partition metadata, which can move or validate data.",
            )
        elif delta.new_tablespace is not None:
            level, reason = (
                RiskLevel.WARNING,
                "Changes tablespace, which can move data or require stronger locks.",
            )
        else:
            level, reason = RiskLevel.SAFE, "Changes table owner or comment metadata only."
    elif isinstance(delta, AddColumn):
        conditions = []
        is_virtual_generated = (
            delta.column.generated_expression is not None
            and delta.column.generated_kind == "virtual"
        )
        if not delta.column.nullable:
            conditions.append("NOT NULL")
        if delta.column.default_expr is not None:
            conditions.append("a default")
        if delta.column.identity is not None:
            conditions.append("identity generation")
        if delta.column.generated_expression is not None and not is_virtual_generated:
            conditions.append("a generated expression")
        if is_virtual_generated and not conditions:
            level, reason = (
                RiskLevel.SAFE,
                "Adds a virtual generated column; existing row values are computed on read, "
                "not rewritten.",
            )
        elif conditions:
            level = RiskLevel.WARNING
            reason = (
                f"Adds a column with {', '.join(conditions)}; "
                "existing rows may require rewrite or validation."
            )
        else:
            level, reason = (
                RiskLevel.SAFE,
                "Adds a nullable column without a default, identity, or generated expression.",
            )
    elif isinstance(delta, DropColumn):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes column data."
    elif isinstance(delta, AlterColumnType):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Type conversion may rewrite the table and hold a long lock.",
        )
    elif isinstance(delta, SetColumnDefault):
        level, reason = (
            RiskLevel.SAFE,
            "Changes the default for future writes without rewriting existing values.",
        )
    elif isinstance(delta, SetColumnNullability):
        if delta.nullable:
            level, reason = RiskLevel.SAFE, "Allows NULL values without validating existing rows."
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Setting NOT NULL requires validation of existing rows and may block.",
            )
    elif isinstance(delta, RenameColumn):
        level, reason = (
            RiskLevel.WARNING,
            "Column rename requires a lock and can affect dependent application behavior.",
        )
    elif isinstance(delta, CreateIndex):
        if delta.index.table_ref in created_tables:
            level, reason = (
                RiskLevel.SAFE,
                "Creates an index on an empty table created in this migration.",
            )
        elif delta.index.partitioned:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Builds the index on every partition while blocking writes.",
            )
        else:
            level, reason = (
                RiskLevel.WARNING,
                "Index creation may block because execution mode is not specified.",
            )
    elif isinstance(delta, DropIndex):
        if delta.index.unique:
            level, reason = (
                RiskLevel.DESTRUCTIVE,
                "Dropping a unique index removes an enforced uniqueness guarantee.",
            )
        else:
            level, reason = RiskLevel.DANGEROUS, "Dropping an index removes an access path."
    elif isinstance(delta, ReplaceIndex):
        if (
            delta.old_index.partitioned or delta.new_index.partitioned
        ) and delta.new_index.table_ref in created_tables:
            level, reason = (
                RiskLevel.SAFE,
                "Replaces an index on an empty table created in this migration.",
            )
        elif delta.old_index.unique and not delta.new_index.unique:
            level, reason = (
                RiskLevel.DESTRUCTIVE,
                "Replacing a unique index with a non-unique index "
                "removes an enforced uniqueness guarantee.",
            )
        elif delta.old_index.partitioned or delta.new_index.partitioned:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Builds the index on every partition while blocking writes.",
            )
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Replacing an index requires a rebuild that may block.",
            )
    elif isinstance(delta, AddConstraint):
        if delta.target.parent not in created_tables:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Adding a constraint may scan or validate rows, block, or fail on existing data.",
            )
        else:
            level, reason = (
                RiskLevel.SAFE,
                "Adds a constraint to a table created in the same migration; "
                "it has no existing rows.",
            )
            if isinstance(delta.constraint, ForeignKeyConstraint):
                referenced_table = ObjectRef(
                    kind=ObjectKind.TABLE,
                    qname=QualifiedName(
                        namespace=delta.constraint.ref_namespace,
                        name=delta.constraint.ref_table,
                    ),
                )
                if referenced_table not in created_tables:
                    level, reason = (
                        RiskLevel.WARNING,
                        "Adds a foreign key from a table created in this migration; "
                        "the existing referenced table takes a SHARE ROW EXCLUSIVE lock, "
                        "bounded by lock_timeout.",
                    )
    elif isinstance(delta, DropConstraint):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes an enforced integrity rule."
    elif isinstance(delta, CreateEnum):
        level, reason = RiskLevel.SAFE, "Creates an enum type."
    elif isinstance(delta, AddEnumValue):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Adds an enum label; this is irreversible and changes accepted values.",
        )
    elif isinstance(delta, DropEnum):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes an enum type."
    elif isinstance(delta, AlterEnumAttrs):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Changes enum owner, which can change effective access.",
        )
    elif isinstance(delta, ReplaceEnumLabels):
        level, reason = (
            RiskLevel.BLOCKED,
            "Enum label removal, rename, or reorder has no safe in-place DDL.",
        )
    elif isinstance(delta, CreateCompositeType):
        level, reason = RiskLevel.SAFE, "Creates a composite type."
    elif isinstance(delta, DropCompositeType):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes a composite type."
    elif isinstance(delta, AlterCompositeAddAttribute):
        level, reason = RiskLevel.SAFE, "Adds an attribute to a composite type."
    elif isinstance(delta, AlterCompositeDropAttribute):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes an attribute from a composite type."
    elif isinstance(delta, AlterCompositeAttributeType):
        level, reason = RiskLevel.DANGEROUS, "Changes a composite attribute's data type."
    elif isinstance(delta, AlterCompositeTypeAttrs):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Changes composite type owner, which can change effective access.",
        )
    elif isinstance(delta, ReplaceCompositeType):
        level, reason = (
            RiskLevel.BLOCKED,
            "Composite attribute reorder or middle insertion has no safe in-place DDL.",
        )
    elif isinstance(delta, CreateDomain):
        level, reason = RiskLevel.SAFE, "Creates a domain type."
    elif isinstance(delta, DropDomain):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes a domain type."
    elif isinstance(delta, AlterDomainDefault):
        level, reason = RiskLevel.SAFE, "Changes a domain default for future values."
    elif isinstance(delta, AlterDomainNullability):
        if delta.new_not_null and delta.used_in_container:
            level, reason = (
                RiskLevel.BLOCKED,
                "PostgreSQL cannot set domain NOT NULL when used inside "
                "a composite, array, or range column.",
            )
        elif delta.new_not_null:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Setting domain NOT NULL validates existing values and may block or fail.",
            )
        else:
            level, reason = RiskLevel.DESTRUCTIVE, "Removes a domain's NOT NULL guarantee."
    elif isinstance(delta, AddDomainCheck):
        if delta.used_in_container:
            level, reason = (
                RiskLevel.BLOCKED,
                "Domain checks used inside composite, array, or range types are unsupported.",
            )
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Adds a domain check and validates existing values; migration may fail.",
            )
    elif isinstance(delta, ValidateDomainCheck):
        if delta.used_in_container:
            level, reason = (
                RiskLevel.BLOCKED,
                "Domain checks used inside composite, array, or range types are unsupported.",
            )
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Validates existing domain values and may block or fail.",
            )
    elif isinstance(delta, DropDomainCheck):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes an enforced domain integrity rule."
    elif isinstance(delta, AlterDomainAttrs):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Changes domain owner, which can change effective access.",
        )
    elif isinstance(delta, ReplaceDomainType):
        level, reason = (
            RiskLevel.BLOCKED,
            "Changing a domain base type or collation has no safe in-place DDL.",
        )
    else:
        level, reason = RiskLevel.BLOCKED, "No risk policy exists for this delta type."

    return RiskAssessment(delta=delta, level=level, reason=reason)
