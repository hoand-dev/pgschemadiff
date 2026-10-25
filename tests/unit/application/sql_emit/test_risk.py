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
    AlterColumnType,
    AlterExtension,
    AlterTableAttrs,
    CreateExtension,
    CreateIndex,
    CreateSchema,
    CreateTable,
    DeltaBase,
    DeltaOp,
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
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema
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


def _table(*, partition_of: PartitionOf | None = None) -> Table:
    return Table(ref=_TABLE_REF, partition_of=partition_of)


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
) -> Column:
    return Column(
        name="email",
        position=1,
        data_type="text",
        nullable=nullable,
        default_expr=default_expr,
        identity=identity,
        generated_expression=generated_expression,
    )


def _index(*, unique: bool = False, method: IndexMethod = IndexMethod.BTREE) -> Index:
    return Index(
        ref=_INDEX_REF,
        table_ref=_TABLE_REF,
        method=method,
        key_columns=(IndexKeyColumn(column_name="email"),),
        unique=unique,
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
