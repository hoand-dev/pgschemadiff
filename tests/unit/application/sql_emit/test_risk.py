from dataclasses import FrozenInstanceError
from typing import Literal

import pytest

from pgschemadiff.application.sql_emit.risk import (
    RiskAssessment,
    RiskLevel,
    classify_risk,
    passes_risk_limit,
)
from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    Constraint,
    ExclusionConstraint,
    ExclusionElement,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
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
    AlterSequenceOptions,
    AlterSequenceOwnedBy,
    AlterSequenceOwner,
    AlterTableAttrs,
    CreateCompositeType,
    CreateDomain,
    CreateEnum,
    CreateExtension,
    CreateFunction,
    CreateIndex,
    CreateSchema,
    CreateSequence,
    CreateTable,
    DeltaBase,
    DeltaOp,
    DropColumn,
    DropCompositeType,
    DropConstraint,
    DropDomain,
    DropDomainCheck,
    DropEnum,
    DropExtension,
    DropFunction,
    DropIndex,
    DropSchema,
    DropSequence,
    DropTable,
    RenameColumn,
    RenameTable,
    ReplaceCompositeType,
    ReplaceDomainType,
    ReplaceEnumLabels,
    ReplaceFunction,
    ReplaceIndex,
    SetColumnDefault,
    SetColumnNullability,
    ValidateDomainCheck,
)
from pgschemadiff.domain.domain_type import DomainCheck, DomainType
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import PartitionInfo, PartitionOf, PartitionStrategy, Table

_SCHEMA_REF = ObjectRef(
    kind=ObjectKind.SCHEMA,
    qname=QualifiedName(namespace="public", name="public"),
)
_DELTA = CreateSchema(target=_SCHEMA_REF, pg_schema=Schema(ref=_SCHEMA_REF))
_TABLE_REF = ObjectRef(
    kind=ObjectKind.TABLE,
    qname=QualifiedName(namespace="public", name="users"),
)
_COLUMN_REF = ObjectRef(
    kind=ObjectKind.COLUMN,
    qname=QualifiedName(namespace="public", name="email"),
    parent=_TABLE_REF,
)
_INDEX_REF = ObjectRef(
    kind=ObjectKind.INDEX,
    qname=QualifiedName(namespace="public", name="users_email_idx"),
)
_EXTENSION_REF = ObjectRef(
    kind=ObjectKind.EXTENSION,
    qname=QualifiedName(namespace="public", name="pgcrypto"),
)
_ENUM_REF = ObjectRef(
    kind=ObjectKind.ENUM,
    qname=QualifiedName(namespace="public", name="state"),
)
_COMPOSITE_REF = ObjectRef(
    kind=ObjectKind.COMPOSITE_TYPE,
    qname=QualifiedName(namespace="public", name="record"),
)
_DOMAIN_REF = ObjectRef(
    kind=ObjectKind.DOMAIN_TYPE,
    qname=QualifiedName(namespace="public", name="positive"),
)
_SEQUENCE_REF = ObjectRef(
    kind=ObjectKind.SEQUENCE,
    qname=QualifiedName(namespace="public", name="users_id_seq"),
)
_FUNCTION_REF = ObjectRef(
    kind=ObjectKind.FUNCTION,
    qname=QualifiedName(namespace="public", name="sample"),
    arg_signature=("integer",),
)


def _table(*, partition_of: PartitionOf | None = None, unlogged: bool = False) -> Table:
    return Table(ref=_TABLE_REF, partition_of=partition_of, unlogged=unlogged)


def _enum() -> EnumType:
    return EnumType(ref=_ENUM_REF, labels=("ready", "done"), owner="app_owner")


def _composite() -> CompositeType:
    return CompositeType(
        ref=_COMPOSITE_REF,
        attributes=(CompositeAttribute(name="value", data_type="integer"),),
        owner="app_owner",
    )


def _domain() -> DomainType:
    return DomainType(ref=_DOMAIN_REF, base_type="integer", owner="app_owner")


def _sequence(*, owned_by: ObjectRef | None = None) -> Sequence:
    return Sequence(
        ref=_SEQUENCE_REF,
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=9223372036854775807,
        cache=1,
        cycle=False,
        owner="app_owner",
        owned_by=owned_by,
    )


def _function(
    *,
    body: str = "SELECT 1",
    language: str = "sql",
    security_definer: bool = False,
    return_type: str = "integer",
) -> Function:
    return Function(
        ref=_FUNCTION_REF,
        arguments=(FunctionArgument(name="value", data_type="integer"),),
        return_type=return_type,
        language=language,
        volatility="immutable",
        strict=False,
        security_definer=security_definer,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        body=body,
        definition=f"CREATE OR REPLACE FUNCTION public.sample(integer) AS $$ {body} $$",
        owner="app_owner",
    )


def _add_constraint(table_ref: ObjectRef, constraint: Constraint) -> AddConstraint:
    target = ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=constraint.name),
        parent=table_ref,
    )
    return AddConstraint(target=target, constraint=constraint)


def _column(
    *,
    nullable: bool = True,
    default_expr: str | None = None,
    identity: IdentitySpec | None = None,
    generated_expression: str | None = None,
    generated_kind: Literal["stored", "virtual"] | None = None,
) -> Column:
    return Column(
        name="email",
        position=1,
        data_type="text",
        nullable=nullable,
        default_expr=default_expr,
        identity=identity,
        generated_expression=generated_expression,
        generated_kind=generated_kind,
    )


def _index(
    *,
    unique: bool = False,
    method: IndexMethod = IndexMethod.BTREE,
    partitioned: bool = False,
) -> Index:
    return Index(
        ref=_INDEX_REF,
        table_ref=_TABLE_REF,
        method=method,
        key_columns=(IndexKeyColumn(column_name="email"),),
        unique=unique,
        partitioned=partitioned,
    )


RISK_CASES = (
    pytest.param(
        CreateSchema(target=_SCHEMA_REF, pg_schema=Schema(ref=_SCHEMA_REF)),
        RiskLevel.SAFE,
        id="create-schema",
    ),
    pytest.param(
        DropSchema(target=_SCHEMA_REF, pg_schema=Schema(ref=_SCHEMA_REF)),
        RiskLevel.DESTRUCTIVE,
        id="drop-schema",
    ),
    pytest.param(
        CreateExtension(
            target=_EXTENSION_REF,
            extension=Extension(ref=_EXTENSION_REF, version="1.0"),
        ),
        RiskLevel.WARNING,
        id="create-extension",
    ),
    pytest.param(
        DropExtension(
            target=_EXTENSION_REF,
            extension=Extension(ref=_EXTENSION_REF, version="1.0"),
        ),
        RiskLevel.DESTRUCTIVE,
        id="drop-extension",
    ),
    pytest.param(
        AlterExtension(target=_EXTENSION_REF, new_schema="extensions"),
        RiskLevel.WARNING,
        id="alter-extension-schema",
    ),
    pytest.param(
        AlterExtension(target=_EXTENSION_REF, new_version="2.0"),
        RiskLevel.DANGEROUS,
        id="alter-extension-version",
    ),
    pytest.param(CreateTable(target=_TABLE_REF, table=_table()), RiskLevel.SAFE, id="create-table"),
    pytest.param(
        CreateTable(
            target=_TABLE_REF,
            table=_table(
                partition_of=PartitionOf(parent_namespace="public", parent_name="users_root")
            ),
        ),
        RiskLevel.WARNING,
        id="create-partition-child",
    ),
    pytest.param(
        DropTable(target=_TABLE_REF, table=_table()), RiskLevel.DESTRUCTIVE, id="drop-table"
    ),
    pytest.param(
        RenameTable(
            target=_TABLE_REF,
            old_name=_TABLE_REF.qname,
            new_name=QualifiedName(namespace="public", name="accounts"),
        ),
        RiskLevel.WARNING,
        id="rename-table",
    ),
    pytest.param(
        AlterTableAttrs(target=_TABLE_REF, new_owner="app_owner"),
        RiskLevel.SAFE,
        id="table-owner",
    ),
    pytest.param(
        AlterTableAttrs(target=_TABLE_REF, new_comment="customer accounts"),
        RiskLevel.SAFE,
        id="table-comment",
    ),
    pytest.param(
        AlterTableAttrs(target=_TABLE_REF, new_tablespace="fast_storage"),
        RiskLevel.WARNING,
        id="table-tablespace",
    ),
    pytest.param(
        AlterTableAttrs(
            target=_TABLE_REF,
            new_partition_info=PartitionInfo(
                strategy=PartitionStrategy.RANGE,
                partition_key="created_at",
            ),
        ),
        RiskLevel.DANGEROUS,
        id="table-partition-info",
    ),
    pytest.param(
        AlterTableAttrs(
            target=_TABLE_REF,
            new_partition_of=PartitionOf(parent_namespace="public", parent_name="users_root"),
        ),
        RiskLevel.DANGEROUS,
        id="table-partition-of",
    ),
    pytest.param(
        AlterTableAttrs(
            target=_TABLE_REF,
            new_tablespace="fast_storage",
            new_partition_info=PartitionInfo(
                strategy=PartitionStrategy.RANGE,
                partition_key="created_at",
            ),
        ),
        RiskLevel.DANGEROUS,
        id="table-tablespace-and-partition",
    ),
    pytest.param(
        AddColumn(target=_COLUMN_REF, column=_column()),
        RiskLevel.SAFE,
        id="add-nullable-column",
    ),
    pytest.param(
        AddColumn(target=_COLUMN_REF, column=_column(nullable=False)),
        RiskLevel.WARNING,
        id="add-not-null-column",
    ),
    pytest.param(
        AddColumn(target=_COLUMN_REF, column=_column(default_expr="'unknown'::text")),
        RiskLevel.WARNING,
        id="add-column-with-default",
    ),
    pytest.param(
        AddColumn(
            target=_COLUMN_REF,
            column=_column(identity=IdentitySpec(generated=GeneratedTiming.ALWAYS)),
        ),
        RiskLevel.WARNING,
        id="add-identity-column",
    ),
    pytest.param(
        AddColumn(
            target=_COLUMN_REF,
            column=_column(generated_expression="lower(email)"),
        ),
        RiskLevel.WARNING,
        id="add-generated-column",
    ),
    pytest.param(
        AddColumn(
            target=_COLUMN_REF,
            column=_column(
                generated_expression="lower(email)",
                generated_kind="virtual",
            ),
        ),
        RiskLevel.SAFE,
        id="add-virtual-generated-column",
    ),
    pytest.param(
        DropColumn(target=_COLUMN_REF, column=_column()),
        RiskLevel.DESTRUCTIVE,
        id="drop-column",
    ),
    pytest.param(
        AlterColumnType(target=_COLUMN_REF, new_data_type="varchar(255)"),
        RiskLevel.DANGEROUS,
        id="alter-column-type",
    ),
    pytest.param(
        SetColumnDefault(target=_COLUMN_REF, new_default="'unknown'::text"),
        RiskLevel.SAFE,
        id="set-column-default",
    ),
    pytest.param(
        SetColumnNullability(target=_COLUMN_REF, nullable=True),
        RiskLevel.SAFE,
        id="set-column-nullable",
    ),
    pytest.param(
        SetColumnNullability(target=_COLUMN_REF, nullable=False),
        RiskLevel.DANGEROUS,
        id="set-column-not-null",
    ),
    pytest.param(
        RenameColumn(target=_COLUMN_REF, old_name="email", new_name="email_address"),
        RiskLevel.WARNING,
        id="rename-column",
    ),
    pytest.param(
        CreateIndex(target=_INDEX_REF, index=_index()),
        RiskLevel.WARNING,
        id="create-index",
    ),
    pytest.param(
        CreateIndex(target=_INDEX_REF, index=_index(partitioned=True)),
        RiskLevel.DANGEROUS,
        id="create-partitioned-index",
    ),
    pytest.param(
        DropIndex(target=_INDEX_REF, index=_index()),
        RiskLevel.DANGEROUS,
        id="drop-nonunique-index",
    ),
    pytest.param(
        DropIndex(target=_INDEX_REF, index=_index(unique=True)),
        RiskLevel.DESTRUCTIVE,
        id="drop-unique-index",
    ),
    pytest.param(
        ReplaceIndex(
            target=_INDEX_REF,
            old_index=_index(),
            new_index=_index(method=IndexMethod.HASH),
        ),
        RiskLevel.DANGEROUS,
        id="replace-index",
    ),
    pytest.param(
        ReplaceIndex(
            target=_INDEX_REF,
            old_index=_index(partitioned=True),
            new_index=_index(partitioned=True, method=IndexMethod.HASH),
        ),
        RiskLevel.DANGEROUS,
        id="replace-partitioned-index",
    ),
    pytest.param(
        ReplaceIndex(
            target=_INDEX_REF,
            old_index=_index(unique=True),
            new_index=_index(unique=False, method=IndexMethod.HASH),
        ),
        RiskLevel.DESTRUCTIVE,
        id="replace-unique-with-nonunique-index",
    ),
    pytest.param(
        AddConstraint(
            target=ObjectRef(
                kind=ObjectKind.CONSTRAINT,
                qname=QualifiedName(namespace="public", name="users_pkey"),
                parent=_TABLE_REF,
            ),
            constraint=PrimaryKeyConstraint(name="users_pkey", columns=("id",)),
        ),
        RiskLevel.DANGEROUS,
        id="add-primary-key",
    ),
    pytest.param(
        AddConstraint(
            target=ObjectRef(
                kind=ObjectKind.CONSTRAINT,
                qname=QualifiedName(namespace="public", name="users_email_key"),
                parent=_TABLE_REF,
            ),
            constraint=UniqueConstraint(name="users_email_key", columns=("email",)),
        ),
        RiskLevel.DANGEROUS,
        id="add-unique-constraint",
    ),
    pytest.param(
        AddConstraint(
            target=ObjectRef(
                kind=ObjectKind.CONSTRAINT,
                qname=QualifiedName(namespace="public", name="users_email_check"),
                parent=_TABLE_REF,
            ),
            constraint=CheckConstraint(name="users_email_check", expression="email <> ''"),
        ),
        RiskLevel.DANGEROUS,
        id="add-check-constraint",
    ),
    pytest.param(
        AddConstraint(
            target=ObjectRef(
                kind=ObjectKind.CONSTRAINT,
                qname=QualifiedName(namespace="public", name="users_team_fkey"),
                parent=_TABLE_REF,
            ),
            constraint=ForeignKeyConstraint(
                name="users_team_fkey",
                columns=("team_id",),
                ref_namespace="public",
                ref_table="teams",
                ref_columns=("id",),
            ),
        ),
        RiskLevel.DANGEROUS,
        id="add-foreign-key",
    ),
    pytest.param(
        AddConstraint(
            target=ObjectRef(
                kind=ObjectKind.CONSTRAINT,
                qname=QualifiedName(namespace="public", name="users_email_excl"),
                parent=_TABLE_REF,
            ),
            constraint=ExclusionConstraint(
                name="users_email_excl",
                index_method="gist",
                elements=(ExclusionElement(column_or_expr="email", operator="="),),
            ),
        ),
        RiskLevel.DANGEROUS,
        id="add-exclusion-constraint",
    ),
    pytest.param(
        DropConstraint(
            target=ObjectRef(
                kind=ObjectKind.CONSTRAINT,
                qname=QualifiedName(namespace="public", name="users_pkey"),
                parent=_TABLE_REF,
            ),
            constraint=PrimaryKeyConstraint(name="users_pkey", columns=("id",)),
        ),
        RiskLevel.DESTRUCTIVE,
        id="drop-constraint",
    ),
    pytest.param(
        CreateEnum(target=_ENUM_REF, enum=_enum()),
        RiskLevel.SAFE,
        id="create-enum",
    ),
    pytest.param(
        AddEnumValue(target=_ENUM_REF, label="review", before="done"),
        RiskLevel.DANGEROUS,
        id="add-enum-value",
    ),
    pytest.param(
        DropEnum(target=_ENUM_REF, enum=_enum()),
        RiskLevel.DESTRUCTIVE,
        id="drop-enum",
    ),
    pytest.param(
        AlterEnumAttrs(target=_ENUM_REF, new_owner="other_owner"),
        RiskLevel.DANGEROUS,
        id="enum-owner",
    ),
    pytest.param(
        ReplaceEnumLabels(
            target=_ENUM_REF,
            old_labels=("ready", "done"),
            new_labels=("ready",),
        ),
        RiskLevel.BLOCKED,
        id="replace-enum-labels",
    ),
    pytest.param(
        CreateCompositeType(target=_COMPOSITE_REF, composite=_composite()),
        RiskLevel.SAFE,
        id="create-composite-type",
    ),
    pytest.param(
        DropCompositeType(target=_COMPOSITE_REF, composite=_composite()),
        RiskLevel.DESTRUCTIVE,
        id="drop-composite-type",
    ),
    pytest.param(
        AlterCompositeAddAttribute(
            target=_COMPOSITE_REF,
            attribute=CompositeAttribute(name="label", data_type="text"),
        ),
        RiskLevel.SAFE,
        id="add-composite-attribute",
    ),
    pytest.param(
        AlterCompositeDropAttribute(target=_COMPOSITE_REF, attribute_name="value"),
        RiskLevel.DESTRUCTIVE,
        id="drop-composite-attribute",
    ),
    pytest.param(
        AlterCompositeAttributeType(
            target=_COMPOSITE_REF,
            attribute_name="value",
            new_data_type="bigint",
        ),
        RiskLevel.DANGEROUS,
        id="alter-composite-attribute-type",
    ),
    pytest.param(
        AlterCompositeTypeAttrs(target=_COMPOSITE_REF, new_owner="other_owner"),
        RiskLevel.DANGEROUS,
        id="composite-type-owner",
    ),
    pytest.param(
        ReplaceCompositeType(
            target=_COMPOSITE_REF,
            old_attributes=(CompositeAttribute(name="a", data_type="integer"),),
            new_attributes=(CompositeAttribute(name="b", data_type="integer"),),
        ),
        RiskLevel.BLOCKED,
        id="replace-composite-type-blocked",
    ),
    pytest.param(
        CreateDomain(target=_DOMAIN_REF, domain=_domain()),
        RiskLevel.SAFE,
        id="create-domain",
    ),
    pytest.param(
        DropDomain(target=_DOMAIN_REF, domain=_domain()),
        RiskLevel.DESTRUCTIVE,
        id="drop-domain",
    ),
    pytest.param(
        AlterDomainDefault(target=_DOMAIN_REF, new_default_expr="0"),
        RiskLevel.SAFE,
        id="domain-default",
    ),
    pytest.param(
        AlterDomainNullability(target=_DOMAIN_REF, new_not_null=True),
        RiskLevel.DANGEROUS,
        id="domain-set-not-null",
    ),
    pytest.param(
        AlterDomainNullability(
            target=_DOMAIN_REF,
            new_not_null=True,
            used_in_container=True,
        ),
        RiskLevel.BLOCKED,
        id="domain-set-not-null-in-container",
    ),
    pytest.param(
        AlterDomainNullability(target=_DOMAIN_REF, new_not_null=False),
        RiskLevel.DESTRUCTIVE,
        id="domain-drop-not-null",
    ),
    pytest.param(
        AddDomainCheck(
            target=_DOMAIN_REF,
            check=DomainCheck(name="positive_check", expression="VALUE > 0"),
        ),
        RiskLevel.DANGEROUS,
        id="domain-add-check",
    ),
    pytest.param(
        ValidateDomainCheck(target=_DOMAIN_REF, check_name="positive_check"),
        RiskLevel.DANGEROUS,
        id="domain-validate-check",
    ),
    pytest.param(
        DropDomainCheck(target=_DOMAIN_REF, check_name="positive_check"),
        RiskLevel.DESTRUCTIVE,
        id="domain-drop-check",
    ),
    pytest.param(
        AlterDomainAttrs(target=_DOMAIN_REF, new_owner="other_owner"),
        RiskLevel.DANGEROUS,
        id="domain-owner",
    ),
    pytest.param(
        ReplaceDomainType(
            target=_DOMAIN_REF,
            old_base_type="integer",
            new_base_type="text",
            old_collation=None,
            new_collation=None,
        ),
        RiskLevel.BLOCKED,
        id="replace-domain-type-blocked",
    ),
    pytest.param(
        CreateSequence(target=_SEQUENCE_REF, sequence=_sequence()),
        RiskLevel.SAFE,
        id="create-unowned-sequence",
    ),
    pytest.param(
        CreateSequence(target=_SEQUENCE_REF, sequence=_sequence(owned_by=_COLUMN_REF)),
        RiskLevel.DANGEROUS,
        id="create-column-owned-sequence",
    ),
    pytest.param(
        DropSequence(target=_SEQUENCE_REF, sequence=_sequence()),
        RiskLevel.DESTRUCTIVE,
        id="drop-sequence",
    ),
    pytest.param(
        AlterSequenceOptions(target=_SEQUENCE_REF, new_increment=2),
        RiskLevel.WARNING,
        id="alter-sequence-options",
    ),
    pytest.param(
        AlterSequenceOwner(target=_SEQUENCE_REF, new_owner="other_owner"),
        RiskLevel.DANGEROUS,
        id="alter-sequence-role-owner",
    ),
    pytest.param(
        AlterSequenceOwnedBy(target=_SEQUENCE_REF, new_owned_by=_COLUMN_REF),
        RiskLevel.WARNING,
        id="alter-sequence-owned-by",
    ),
    pytest.param(
        CreateFunction(target=_FUNCTION_REF, function=_function()),
        RiskLevel.WARNING,
        id="create-function",
    ),
    pytest.param(
        DropFunction(target=_FUNCTION_REF, function=_function()),
        RiskLevel.DESTRUCTIVE,
        id="drop-function",
    ),
    pytest.param(
        ReplaceFunction(
            target=_FUNCTION_REF,
            old_function=_function(),
            new_function=_function(body="SELECT 2"),
        ),
        RiskLevel.DANGEROUS,
        id="replace-function",
    ),
    pytest.param(
        AlterFunctionOwner(
            target=_FUNCTION_REF,
            function=_function(),
            new_owner="other_owner",
        ),
        RiskLevel.DANGEROUS,
        id="alter-function-owner",
    ),
)


def _assessment(level: RiskLevel) -> RiskAssessment:
    return RiskAssessment(delta=_DELTA, level=level, reason=level.value)


@pytest.mark.parametrize(("delta", "expected_level"), RISK_CASES)
def test_classify_risk_matches_policy(delta: DeltaBase, expected_level: RiskLevel) -> None:
    assessment = classify_risk(delta)
    assert assessment.delta is delta
    assert assessment.level is expected_level
    assert assessment.reason.strip()
    assert classify_risk(delta).reason == assessment.reason


def test_replacing_enum_labels_has_precise_blocked_reason() -> None:
    delta = ReplaceEnumLabels(
        target=_ENUM_REF,
        old_labels=("ready", "done"),
        new_labels=("ready",),
    )

    assessment = classify_risk(delta)

    assert assessment.level is RiskLevel.BLOCKED
    assert assessment.reason == ("Enum label removal, rename, or reorder has no safe in-place DDL.")


def test_replacing_composite_layout_has_precise_blocked_reason() -> None:
    delta = ReplaceCompositeType(
        target=_COMPOSITE_REF,
        old_attributes=(CompositeAttribute(name="a", data_type="integer"),),
        new_attributes=(CompositeAttribute(name="b", data_type="integer"),),
    )

    assessment = classify_risk(delta)

    assert assessment.level is RiskLevel.BLOCKED
    assert assessment.reason == (
        "Composite attribute reorder or middle insertion has no safe in-place DDL."
    )


def test_new_security_definer_function_is_blocked() -> None:
    delta = CreateFunction(
        target=_FUNCTION_REF,
        function=_function(security_definer=True),
    )

    assessment = classify_risk(delta)

    assert assessment.level is RiskLevel.BLOCKED
    assert "SECURITY DEFINER" in assessment.reason
    assert not passes_risk_limit((assessment,), max_risk=RiskLevel.BLOCKED)


def test_unsupported_function_languages_are_blocked_for_every_delta() -> None:
    supported = _function()
    unsupported = _function(language="c")
    deltas = (
        CreateFunction(target=_FUNCTION_REF, function=unsupported),
        DropFunction(target=_FUNCTION_REF, function=unsupported),
        ReplaceFunction(
            target=_FUNCTION_REF,
            old_function=supported,
            new_function=unsupported,
        ),
        ReplaceFunction(
            target=_FUNCTION_REF,
            old_function=unsupported,
            new_function=supported,
        ),
        AlterFunctionOwner(
            target=_FUNCTION_REF,
            function=unsupported,
            new_owner="other_owner",
        ),
    )

    for delta in deltas:
        assessment = classify_risk(delta)
        assert assessment.level is RiskLevel.BLOCKED
        assert "sql and plpgsql" in assessment.reason


@pytest.mark.parametrize(
    "delta",
    [
        CreateFunction(target=_FUNCTION_REF, function=_function(), default_conflict=True),
        ReplaceFunction(
            target=_FUNCTION_REF,
            old_function=_function(),
            new_function=_function(body="SELECT 2"),
            default_conflict=True,
        ),
        ReplaceFunction(
            target=_FUNCTION_REF,
            old_function=_function(),
            new_function=_function(return_type="text"),
            incompatible=True,
        ),
    ],
    ids=("create-default-conflict", "replace-default-conflict", "incompatible-replace"),
)
def test_unsafe_function_delta_shapes_are_blocked(delta: DeltaBase) -> None:
    assert classify_risk(delta).level is RiskLevel.BLOCKED


@pytest.mark.parametrize(
    "delta",
    [
        AddDomainCheck(
            target=_DOMAIN_REF,
            check=DomainCheck(name="positive_check", expression="VALUE > 0"),
            used_in_container=True,
        ),
        ValidateDomainCheck(
            target=_DOMAIN_REF,
            check_name="positive_check",
            used_in_container=True,
        ),
    ],
    ids=("add-check", "validate-check"),
)
def test_domain_check_changes_inside_containers_are_blocked(delta: DeltaBase) -> None:
    assessment = classify_risk(delta)

    assert assessment.level is RiskLevel.BLOCKED
    assert assessment.reason == (
        "Domain checks used inside composite, array, or range types are unsupported."
    )


def test_virtual_generated_column_addition_has_precise_safe_reason() -> None:
    delta = AddColumn(
        target=_COLUMN_REF,
        column=_column(generated_expression="lower(email)", generated_kind="virtual"),
    )

    assessment = classify_risk(delta)

    assert assessment.level is RiskLevel.SAFE
    assert assessment.reason == (
        "Adds a virtual generated column; existing row values are computed on read, not rewritten."
    )


@pytest.mark.unit
def test_unlogged_table_creation_stays_safe() -> None:
    delta = CreateTable(target=_TABLE_REF, table=_table(unlogged=True))

    assert classify_risk(delta).level is RiskLevel.SAFE


@pytest.mark.unit
@pytest.mark.parametrize("unlogged", [True, False], ids=["set-unlogged", "set-logged"])
def test_table_persistence_change_is_dangerous_with_lock_reason(unlogged: bool) -> None:
    delta = AlterTableAttrs(target=_TABLE_REF, new_unlogged=unlogged)

    assessment = classify_risk(delta)

    assert assessment.level is RiskLevel.DANGEROUS
    assert assessment.reason == (
        "Changing table persistence rewrites the table under an ACCESS EXCLUSIVE lock."
    )


def test_not_null_virtual_generated_column_remains_warning() -> None:
    delta = AddColumn(
        target=_COLUMN_REF,
        column=_column(
            nullable=False,
            generated_expression="lower(email)",
            generated_kind="virtual",
        ),
    )

    assert classify_risk(delta).level is RiskLevel.WARNING


def test_add_constraint_on_new_table_is_safe() -> None:
    delta = _add_constraint(
        _TABLE_REF,
        CheckConstraint(name="users_email_check", expression="email <> ''"),
    )

    assessment = classify_risk(delta, created_tables=frozenset({_TABLE_REF}))

    assert assessment.level is RiskLevel.SAFE
    assert "created in the same migration" in assessment.reason
    assert "no existing rows" in assessment.reason


def test_foreign_key_to_existing_table_is_warning_for_new_table() -> None:
    delta = _add_constraint(
        _TABLE_REF,
        ForeignKeyConstraint(
            name="users_team_fkey",
            columns=("team_id",),
            ref_namespace="public",
            ref_table="teams",
            ref_columns=("id",),
        ),
    )

    assessment = classify_risk(delta, created_tables=frozenset({_TABLE_REF}))

    assert assessment.level is RiskLevel.WARNING
    assert "SHARE ROW EXCLUSIVE" in assessment.reason
    assert "lock_timeout" in assessment.reason


def test_foreign_key_between_new_tables_is_safe() -> None:
    teams_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="teams"),
    )
    delta = _add_constraint(
        _TABLE_REF,
        ForeignKeyConstraint(
            name="users_team_fkey",
            columns=("team_id",),
            ref_namespace="public",
            ref_table="teams",
            ref_columns=("id",),
        ),
    )

    assessment = classify_risk(delta, created_tables=frozenset({_TABLE_REF, teams_ref}))

    assert assessment.level is RiskLevel.SAFE
    assert "created in the same migration" in assessment.reason
    assert "no existing rows" in assessment.reason


def test_index_on_new_table_is_safe() -> None:
    delta = CreateIndex(target=_INDEX_REF, index=_index())

    assessment = classify_risk(delta, created_tables=frozenset({_TABLE_REF}))

    assert assessment.level is RiskLevel.SAFE
    assert "empty table" in assessment.reason


def test_partitioned_index_on_new_table_stays_safe() -> None:
    delta = CreateIndex(target=_INDEX_REF, index=_index(partitioned=True))

    assessment = classify_risk(delta, created_tables=frozenset({_TABLE_REF}))

    assert assessment.level is RiskLevel.SAFE
    assert "empty table" in assessment.reason


def test_partitioned_index_on_existing_table_has_blocking_risk_reason() -> None:
    delta = CreateIndex(target=_INDEX_REF, index=_index(partitioned=True))

    assessment = classify_risk(delta)

    assert assessment.level is RiskLevel.DANGEROUS
    assert assessment.reason == "Builds the index on every partition while blocking writes."


def test_partitioned_index_replacement_on_new_table_stays_safe() -> None:
    delta = ReplaceIndex(
        target=_INDEX_REF,
        old_index=_index(partitioned=True),
        new_index=_index(partitioned=True, method=IndexMethod.HASH),
    )

    assessment = classify_risk(delta, created_tables=frozenset({_TABLE_REF}))

    assert assessment.level is RiskLevel.SAFE
    assert "created in this migration" in assessment.reason


def test_existing_table_risks_stay_conservative_with_context() -> None:
    other_table = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="teams"),
    )
    constraint = _add_constraint(
        _TABLE_REF,
        CheckConstraint(name="users_email_check", expression="email <> ''"),
    )
    index = CreateIndex(target=_INDEX_REF, index=_index())

    assert classify_risk(constraint, created_tables=frozenset({other_table})).level is (
        RiskLevel.DANGEROUS
    )
    assert classify_risk(index, created_tables=frozenset({other_table})).level is RiskLevel.WARNING


def test_default_context_preserves_existing_constraint_and_index_risks() -> None:
    constraint = _add_constraint(
        _TABLE_REF,
        CheckConstraint(name="users_email_check", expression="email <> ''"),
    )
    index = CreateIndex(target=_INDEX_REF, index=_index())

    assert classify_risk(constraint).level is RiskLevel.DANGEROUS
    assert classify_risk(index).level is RiskLevel.WARNING


class UnsupportedDelta(DeltaBase):
    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["unsupported"] = "unsupported"


class DerivedCreateSchema(CreateSchema):
    pass


def test_unknown_delta_fails_closed() -> None:
    delta = UnsupportedDelta(op=DeltaOp.ALTER, target=_SCHEMA_REF)
    assessment = classify_risk(delta)
    assert assessment.level is RiskLevel.BLOCKED
    assert not passes_risk_limit((assessment,), max_risk=RiskLevel.BLOCKED)


def test_unrecognized_subclass_of_known_delta_fails_closed() -> None:
    delta = DerivedCreateSchema(target=_SCHEMA_REF, pg_schema=Schema(ref=_SCHEMA_REF))
    assessment = classify_risk(delta)
    assert assessment.level is RiskLevel.BLOCKED
    assert not passes_risk_limit((assessment,), max_risk=RiskLevel.BLOCKED)


def test_risk_levels_have_explicit_severity_order() -> None:
    assert tuple(level.name for level in RiskLevel) == (
        "SAFE",
        "WARNING",
        "DANGEROUS",
        "DESTRUCTIVE",
        "BLOCKED",
    )


def test_assessment_keeps_delta_is_frozen_and_rejects_blank_reason() -> None:
    assessment = _assessment(RiskLevel.SAFE)
    assert assessment.delta is _DELTA
    with pytest.raises(FrozenInstanceError):
        assessment.reason = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="blank"):
        RiskAssessment(delta=_DELTA, level=RiskLevel.SAFE, reason="  ")


def test_assessment_rejects_non_risk_level() -> None:
    with pytest.raises(TypeError, match=r"RiskAssessment\.level must be a RiskLevel"):
        RiskAssessment(delta=_DELTA, level="blocked", reason="blocked")  # type: ignore[arg-type]


def test_default_risk_limit_allows_through_dangerous() -> None:
    allowed = tuple(
        _assessment(level)
        for level in (
            RiskLevel.SAFE,
            RiskLevel.WARNING,
            RiskLevel.DANGEROUS,
        )
    )
    assert passes_risk_limit(allowed)
    assert not passes_risk_limit((_assessment(RiskLevel.DESTRUCTIVE),))


def test_blocked_never_passes_even_when_selected_as_limit() -> None:
    assert not passes_risk_limit(
        (_assessment(RiskLevel.DANGEROUS),),
        max_risk=RiskLevel.WARNING,
    )
    assert passes_risk_limit(
        (_assessment(RiskLevel.DESTRUCTIVE),),
        max_risk=RiskLevel.DESTRUCTIVE,
    )
    assert not passes_risk_limit(
        (_assessment(RiskLevel.BLOCKED),),
        max_risk=RiskLevel.BLOCKED,
    )


def test_empty_assessment_collection_passes() -> None:
    assert passes_risk_limit(())
