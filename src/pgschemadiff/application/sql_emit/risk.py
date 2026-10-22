"""Risk assessments and generation-limit checks for schema deltas."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from pgschemadiff.domain.delta import (
    AddColumn,
    AddConstraint,
    AlterColumnType,
    AlterExtension,
    AlterTableAttrs,
    CreateExtension,
    CreateIndex,
    CreateSchema,
    CreateTable,
    DeltaBase,
    DropColumn,
    DropConstraint,
    DropExtension,
    DropIndex,
    DropSchema,
    DropTable,
    RenameColumn,
    RenameTable,
    ReplaceIndex,
    SetColumnDefault,
    SetColumnNullability,
)


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
        if not self.reason.strip():
            raise ValueError("Risk assessment reason must not be blank")


_RISK_RANK = {
    RiskLevel.SAFE: 0,
    RiskLevel.WARNING: 1,
    RiskLevel.DANGEROUS: 2,
    RiskLevel.DESTRUCTIVE: 3,
    RiskLevel.BLOCKED: 4,
}


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


def classify_risk(delta: DeltaBase) -> RiskAssessment:  # noqa: PLR0912, PLR0915
    """Classify a schema delta using the approved static risk policy."""
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
        if has_partition_change and delta.new_tablespace is not None:
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
        if not delta.column.nullable:
            conditions.append("NOT NULL")
        if delta.column.default_expr is not None:
            conditions.append("a default")
        if delta.column.identity is not None:
            conditions.append("identity generation")
        if delta.column.generated_expression is not None:
            conditions.append("a generated expression")
        if conditions:
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
        if delta.old_index.unique and not delta.new_index.unique:
            level, reason = (
                RiskLevel.DESTRUCTIVE,
                "Replacing a unique index with a non-unique index "
                "removes an enforced uniqueness guarantee.",
            )
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Replacing an index requires a rebuild that may block.",
            )
    elif isinstance(delta, AddConstraint):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Adding a constraint may scan or validate rows, block, or fail on existing data.",
        )
    elif isinstance(delta, DropConstraint):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes an enforced integrity rule."
    else:
        level, reason = RiskLevel.BLOCKED, "No risk policy exists for this delta type."

    return RiskAssessment(delta=delta, level=level, reason=reason)
