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
    AlterFunctionOwner,
    AlterMaterializedViewOwner,
    AlterPolicy,
    AlterProcedureOwner,
    AlterSequenceOptions,
    AlterSequenceOwnedBy,
    AlterSequenceOwner,
    AlterTableAttrs,
    AlterTriggerEnabled,
    AlterViewOwner,
    CreateCompositeType,
    CreateDomain,
    CreateEnum,
    CreateExtension,
    CreateFunction,
    CreateIndex,
    CreateMaterializedView,
    CreatePolicy,
    CreateProcedure,
    CreateSchema,
    CreateSequence,
    CreateTable,
    CreateTrigger,
    CreateView,
    DeltaBase,
    DropColumn,
    DropCompositeType,
    DropConstraint,
    DropDomain,
    DropDomainCheck,
    DropEnum,
    DropExtension,
    DropFunction,
    DropIndex,
    DropMaterializedView,
    DropPolicy,
    DropProcedure,
    DropSchema,
    DropSequence,
    DropTable,
    DropTrigger,
    DropView,
    RenameColumn,
    RenameTable,
    ReplaceCompositeType,
    ReplaceDomainType,
    ReplaceEnumLabels,
    ReplaceFunction,
    ReplaceIndex,
    ReplaceMaterializedView,
    ReplacePolicy,
    ReplaceProcedure,
    ReplaceTrigger,
    ReplaceView,
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
    CreateFunction,
    DropExtension,
    DropFunction,
    AlterExtension,
    AlterFunctionOwner,
    CreateProcedure,
    DropProcedure,
    ReplaceProcedure,
    AlterProcedureOwner,
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
    ReplaceFunction,
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
    CreateSequence,
    DropSequence,
    AlterSequenceOptions,
    AlterSequenceOwner,
    AlterSequenceOwnedBy,
    CreateView,
    DropView,
    ReplaceView,
    AlterViewOwner,
    CreateMaterializedView,
    DropMaterializedView,
    ReplaceMaterializedView,
    AlterMaterializedViewOwner,
    CreateTrigger,
    DropTrigger,
    ReplaceTrigger,
    AlterTriggerEnabled,
    CreatePolicy,
    DropPolicy,
    AlterPolicy,
    ReplacePolicy,
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
    resolved_view_dependencies: frozenset[tuple[ObjectRef, ObjectRef]] = frozenset(),
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
        if delta.table.row_security or delta.table.force_row_security:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Creates a table with row-level security access behavior enabled.",
            )
        elif delta.table.partition_of is not None:
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
        if delta.new_row_security is not None or delta.new_force_row_security is not None:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Changes row-level security access behavior.",
            )
        elif delta.new_unlogged is not None:
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
        elif delta.new_owner is not None:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Changes table owner, which can change effective access.",
            )
        elif delta.new_tablespace is not None:
            level, reason = (
                RiskLevel.WARNING,
                "Changes tablespace, which can move data or require stronger locks.",
            )
        else:
            level, reason = RiskLevel.SAFE, "Changes table comment metadata only."
    elif isinstance(delta, CreateView):
        level, reason = (
            RiskLevel.SAFE,
            "Creates a view without storing rows or changing relation data.",
        )
    elif isinstance(delta, DropView):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes a view and its definition."
    elif isinstance(delta, ReplaceView):
        if delta.incompatible or not delta.old_view.can_be_replaced_by(delta.new_view):
            level, reason = (
                RiskLevel.BLOCKED,
                "View output column names, order, and types must remain unchanged; "
                "only append is supported.",
            )
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Replaces view behavior or options and may change query results or access.",
            )
    elif isinstance(delta, AlterViewOwner):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Changes view ownership, which can change effective access to underlying relations.",
        )
    elif isinstance(
        delta,
        (CreateMaterializedView, DropMaterializedView, ReplaceMaterializedView),
    ):
        materialized_views = (
            (delta.old_materialized_view, delta.new_materialized_view)
            if isinstance(delta, ReplaceMaterializedView)
            else (delta.materialized_view,)
        )
        if any(view.has_indexes for view in materialized_views):
            level, reason = (
                RiskLevel.BLOCKED,
                "Materialized-view create, replace, or drop is blocked while attached indexes "
                "are not managed.",
            )
        elif isinstance(delta, (DropMaterializedView, ReplaceMaterializedView)):
            old_materialized_view = (
                delta.old_materialized_view
                if isinstance(delta, ReplaceMaterializedView)
                else delta.materialized_view
            )
            if any(
                (dependent, delta.target) not in resolved_view_dependencies
                for dependent in old_materialized_view.dependents
            ):
                level, reason = (
                    RiskLevel.BLOCKED,
                    "Materialized-view drop or replacement has dependent views or "
                    "materialized views that are not removed or detached.",
                )
            elif isinstance(delta, DropMaterializedView):
                level, reason = (
                    RiskLevel.DESTRUCTIVE,
                    "Removes a materialized view and its stored rows.",
                )
            else:
                level, reason = (
                    RiskLevel.DANGEROUS,
                    "Recreates a materialized view, evaluates its query, and rebuilds stored rows.",
                )
        elif isinstance(delta, CreateMaterializedView):
            level, reason = (
                RiskLevel.DANGEROUS,
                "Creates a materialized view and evaluates its defining query.",
            )
    elif isinstance(delta, AlterMaterializedViewOwner):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Changes materialized-view ownership, which can change effective access.",
        )
    elif isinstance(delta, CreateTrigger):
        level, reason = (
            RiskLevel.WARNING,
            "Creates a trigger that changes behavior on future table writes.",
        )
    elif isinstance(delta, ReplaceTrigger):
        level, reason = (
            RiskLevel.WARNING,
            "Replaces a trigger definition and changes behavior on future table writes.",
        )
    elif isinstance(delta, AlterTriggerEnabled):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Changes trigger firing state and may bypass or alter write-time behavior.",
        )
    elif isinstance(delta, DropTrigger):
        level, reason = (
            RiskLevel.DESTRUCTIVE,
            "Removes trigger behavior from future table writes.",
        )
    elif isinstance(delta, (CreatePolicy, AlterPolicy, ReplacePolicy)):
        level, reason = RiskLevel.DANGEROUS, "Changes row-level security access behavior."
    elif isinstance(delta, DropPolicy):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes a row-level security policy."
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
    elif isinstance(delta, (CreateFunction, DropFunction, ReplaceFunction, AlterFunctionOwner)):
        functions = (
            (delta.old_function, delta.new_function)
            if isinstance(delta, ReplaceFunction)
            else (delta.function,)
        )
        unsupported = next((function for function in functions if not function.is_supported), None)
        if unsupported is not None:
            level, reason = (
                RiskLevel.BLOCKED,
                f"Function language {unsupported.language!r} is unsupported; "
                "only sql and plpgsql are supported.",
            )
        elif isinstance(delta, CreateFunction) and delta.function.security_definer:
            level, reason = (
                RiskLevel.BLOCKED,
                "Creating a SECURITY DEFINER function is blocked because routine ACLs "
                "are not modeled.",
            )
        elif isinstance(delta, (CreateFunction, ReplaceFunction)) and delta.default_conflict:
            level, reason = (
                RiskLevel.BLOCKED,
                "Function default arguments conflict with an overload and may make calls "
                "ambiguous.",
            )
        elif isinstance(delta, ReplaceFunction) and delta.incompatible:
            level, reason = (
                RiskLevel.BLOCKED,
                "Function return or parameter shape cannot be changed safely in place.",
            )
        elif isinstance(delta, CreateFunction):
            level, reason = (
                RiskLevel.WARNING,
                "Creates a function and installs its executable body.",
            )
        elif isinstance(delta, DropFunction):
            level, reason = RiskLevel.DESTRUCTIVE, "Removes a function and its callable behavior."
        elif isinstance(delta, ReplaceFunction):
            level, reason = (
                RiskLevel.DANGEROUS,
                "Replaces function behavior and may change runtime results.",
            )
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Changes function owner, which can change effective access.",
            )
    elif isinstance(
        delta,
        (CreateProcedure, DropProcedure, ReplaceProcedure, AlterProcedureOwner),
    ):
        procedures = (
            (delta.old_procedure, delta.new_procedure)
            if isinstance(delta, ReplaceProcedure)
            else (delta.procedure,)
        )
        unsupported_procedure = next(
            (procedure for procedure in procedures if not procedure.is_supported), None
        )
        if unsupported_procedure is not None:
            level, reason = (
                RiskLevel.BLOCKED,
                f"Procedure language {unsupported_procedure.language!r} is unsupported; "
                "only sql and plpgsql are supported.",
            )
        elif isinstance(delta, CreateProcedure) and delta.procedure.security_definer:
            level, reason = (
                RiskLevel.BLOCKED,
                "Creating a SECURITY DEFINER procedure is blocked because routine ACLs "
                "are not modeled.",
            )
        elif isinstance(delta, ReplaceProcedure) and delta.incompatible:
            level, reason = (
                RiskLevel.BLOCKED,
                "Procedure parameter name, mode, or output shape cannot be changed in place.",
            )
        elif isinstance(delta, CreateProcedure):
            level, reason = (
                RiskLevel.WARNING,
                "Creates a procedure and installs its executable body.",
            )
        elif isinstance(delta, DropProcedure):
            level, reason = RiskLevel.DESTRUCTIVE, "Removes a procedure and its callable behavior."
        elif isinstance(delta, ReplaceProcedure):
            level, reason = (
                RiskLevel.DANGEROUS,
                "Replaces procedure behavior and may change runtime results.",
            )
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Changes procedure owner, which can change effective access.",
            )
    elif isinstance(delta, CreateSequence):
        if delta.sequence.owned_by is None:
            level, reason = RiskLevel.SAFE, "Creates an unowned sequence."
        else:
            level, reason = (
                RiskLevel.DANGEROUS,
                "Creates a column-owned sequence; runtime state is not copied.",
            )
    elif isinstance(delta, DropSequence):
        level, reason = RiskLevel.DESTRUCTIVE, "Removes a sequence and its future value generation."
    elif isinstance(delta, AlterSequenceOptions):
        level, reason = (
            RiskLevel.WARNING,
            "Changes sequence options without restarting its runtime counter.",
        )
    elif isinstance(delta, AlterSequenceOwner):
        level, reason = (
            RiskLevel.DANGEROUS,
            "Changes sequence owner, which can change effective access.",
        )
    elif isinstance(delta, AlterSequenceOwnedBy):
        level, reason = RiskLevel.WARNING, "Changes sequence OWNED BY behavior."
    else:
        level, reason = RiskLevel.BLOCKED, "No risk policy exists for this delta type."

    return RiskAssessment(delta=delta, level=level, reason=reason)
