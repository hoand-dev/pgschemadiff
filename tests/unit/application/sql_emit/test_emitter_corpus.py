from typing import cast

import pytest
from syrupy.assertion import SnapshotAssertion

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.application.sql_emit.emitter import SqlEmitter
from pgschemadiff.application.sql_emit.quoting import quote_ident, quote_qualified
from pgschemadiff.application.sql_emit.registry import default_handlers
from pgschemadiff.application.sql_emit.risk import _SUPPORTED_DELTA_TYPES
from pgschemadiff.application.sql_emit.transaction import split_units
from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ConstraintDeferrability,
    ExclusionConstraint,
    ExclusionElement,
    FKAction,
    FKMatch,
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
    AlterProcedureOwner,
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
    CreateProcedure,
    CreateSchema,
    CreateSequence,
    CreateTable,
    Delta,
    DeltaBase,
    DeltaSet,
    DropColumn,
    DropCompositeType,
    DropConstraint,
    DropDomain,
    DropDomainCheck,
    DropEnum,
    DropExtension,
    DropFunction,
    DropIndex,
    DropProcedure,
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
    ReplaceProcedure,
    SetColumnDefault,
    SetColumnNullability,
    ValidateDomainCheck,
)
from pgschemadiff.domain.domain_type import DomainCheck, DomainType
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod, SortOrder
from pgschemadiff.domain.procedure import Procedure, ProcedureArgument
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import PartitionInfo, PartitionOf, PartitionStrategy, Table
from pgschemadiff.shared.errors import MigrationError


def _schema_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )


def _extension_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.EXTENSION,
        qname=QualifiedName(namespace="public", name=name),
    )


def _table_ref(name: str, namespace: str = "App Schema") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _column_ref(table: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table.qname.namespace, name=name),
        parent=table,
    )


def _constraint_ref(table: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=table.qname.namespace, name=name),
        parent=table,
    )


def _index(
    name: str,
    table: ObjectRef,
    definition: str | None,
    *,
    key_columns: tuple[IndexKeyColumn, ...] = (IndexKeyColumn(column_name="id"),),
    method: IndexMethod = IndexMethod.BTREE,
    unique: bool = False,
    include_columns: tuple[str, ...] = (),
    predicate: str | None = None,
    comment: str | None = None,
    partitioned: bool = False,
) -> Index:
    return Index(
        ref=ObjectRef(
            kind=ObjectKind.INDEX,
            qname=QualifiedName(namespace=table.qname.namespace, name=name),
        ),
        table_ref=table,
        method=method,
        key_columns=key_columns,
        include_columns=include_columns,
        unique=unique,
        predicate=predicate,
        definition=definition,
        comment=comment,
        partitioned=partitioned,
    )


def _emitter_cases() -> tuple[tuple[str, Delta], ...]:
    schema_ref = _schema_ref("Billing")
    dropped_schema_ref = _schema_ref("old_schema")
    extension_ref = _extension_ref('Geo"Tools')
    plain_table_ref = _table_ref('Order"Items')
    account_ref = _table_ref("accounts")
    old_table_name = QualifiedName(namespace='Old "Schema', name="old_table")
    enum_ref = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace='App "Schema', name='Mood"Type'),
    )
    enum = EnumType(
        ref=enum_ref,
        labels=("open", "owner's choice"),
        owner='Role "Owner',
    )
    sequence_ref = ObjectRef(
        kind=ObjectKind.SEQUENCE,
        qname=QualifiedName(namespace='App "Schema', name='Serial"ID'),
    )
    sequence = Sequence(
        ref=sequence_ref,
        data_type="bigint",
        start=7,
        increment=5,
        min_value=1,
        max_value=999,
        cache=3,
        cycle=True,
        owner='Role "Owner',
    )
    function_ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace='App "Schema', name='sum"One'),
        arg_signature=("integer",),
    )
    function_definition = (
        'CREATE OR REPLACE FUNCTION "App ""Schema"."sum""One"('
        "value integer DEFAULT 7) RETURNS integer LANGUAGE sql IMMUTABLE "
        "AS $function$ SELECT value $function$"
    )
    function = Function(
        ref=function_ref,
        arguments=(FunctionArgument(name="value", data_type="integer", default_expr="7"),),
        return_type="integer",
        language="sql",
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        default_expressions="7",
        default_count=1,
        body="SELECT value",
        definition=function_definition,
        owner='Role "Owner',
    )
    procedure_ref = ObjectRef(
        kind=ObjectKind.PROCEDURE,
        qname=QualifiedName(namespace='App "Schema', name='run"task'),
        arg_signature=("integer",),
    )
    procedure_definition = (
        'CREATE OR REPLACE PROCEDURE "App ""Schema"."run""task"('
        "value integer DEFAULT 7) LANGUAGE sql AS $procedure$ SELECT value $procedure$"
    )
    procedure = Procedure(
        ref=procedure_ref,
        arguments=(ProcedureArgument(name="value", data_type="integer", default_expr="7"),),
        language="sql",
        security_definer=False,
        default_expressions="7",
        default_count=1,
        body="SELECT value",
        definition=procedure_definition,
        owner='Role "Owner',
    )
    empty_enum = EnumType(
        ref=ObjectRef(
            kind=ObjectKind.ENUM,
            qname=QualifiedName(namespace="App Schema", name="EmptyMood"),
        ),
    )
    composite_ref = ObjectRef(
        kind=ObjectKind.COMPOSITE_TYPE,
        qname=QualifiedName(namespace='App "Schema', name='Record"Type'),
    )
    composite = CompositeType(
        ref=composite_ref,
        attributes=(
            CompositeAttribute(name='Key"Value', data_type="integer"),
            CompositeAttribute(
                name="label",
                data_type="text",
                collation='"App ""Schema""".case_insensitive',
            ),
        ),
        owner='Role "Owner',
    )
    domain_ref = ObjectRef(
        kind=ObjectKind.DOMAIN_TYPE,
        qname=QualifiedName(namespace='App "Schema', name='Positive"Domain'),
    )
    domain = DomainType(
        ref=domain_ref,
        base_type="numeric(12, 2)",
        collation='"App ""Schema""".case_insensitive',
        default_expr="0",
        not_null=True,
        checks=(
            DomainCheck(
                name='nonzero "value',
                expression="VALUE <> 0",
            ),
        ),
        owner='Role "Owner',
    )
    unvalidated_domain_check = DomainCheck(
        name="new_check",
        expression="VALUE < 100",
        validated=False,
    )

    plain_table = Table(
        ref=plain_table_ref,
        columns=(
            Column(
                name="select",
                position=1,
                data_type="bigint",
                identity=IdentitySpec(
                    generated=GeneratedTiming.BY_DEFAULT,
                    sequence_start=100,
                    sequence_increment=5,
                ),
            ),
            Column(
                name='Display "name',
                position=2,
                data_type="text",
                collation='"App Schema"."case_insensitive"',
            ),
            Column(
                name="total",
                position=3,
                data_type="numeric(12, 2)",
                nullable=False,
                default_expr="0",
            ),
            Column(
                name="computed_total",
                position=4,
                data_type="numeric(12, 2)",
                generated_expression='"quantity" * "unit_price"',
            ),
        ),
        owner='Role "Owner',
        tablespace="fast space",
        comment="Customer's order table",
    )
    partition_parent_ref = _table_ref("events")
    partition_child_ref = _table_ref("events_2026")

    unique_index = _index(
        "users_email_unique",
        plain_table_ref,
        'CREATE UNIQUE INDEX "users_email_unique" ON "App Schema"."Order""Items" '
        'USING btree ("email")',
        key_columns=(IndexKeyColumn(column_name="email"),),
        unique=True,
    )
    partial_expression_index = _index(
        "active_email_idx",
        plain_table_ref,
        'CREATE INDEX "active_email_idx" ON "App Schema"."Order""Items" '
        'USING btree (lower("email")) INCLUDE ("Display ""name") WHERE (active = true)',
        key_columns=(IndexKeyColumn(expression='lower("email")'),),
        include_columns=('Display "name',),
        predicate="active = true",
        comment="Active email lookup",
    )
    gin_index = _index(
        "tags_gin_idx",
        plain_table_ref,
        'CREATE INDEX "tags_gin_idx" ON "App Schema"."Order""Items" USING gin ("tags")',
        key_columns=(IndexKeyColumn(column_name="tags"),),
        method=IndexMethod.GIN,
    )
    partitioned_index = _index(
        "events_date_idx",
        partition_parent_ref,
        'CREATE INDEX "events_date_idx" ON ONLY "App Schema"."events" USING btree ("created_at")',
        key_columns=(IndexKeyColumn(column_name="created_at"),),
        partitioned=True,
    )
    old_replaced_index = _index(
        "created_at_idx",
        plain_table_ref,
        'CREATE INDEX "created_at_idx" ON "App Schema"."Order""Items" USING btree ("created_at")',
        key_columns=(IndexKeyColumn(column_name="created_at"),),
    )
    new_replaced_index = old_replaced_index.model_copy(
        update={
            "definition": (
                'CREATE INDEX "created_at_idx" ON "App Schema"."Order""Items" '
                'USING btree ("created_at" DESC)'
            ),
            "key_columns": (IndexKeyColumn(column_name="created_at", sort_order=SortOrder.DESC),),
            "comment": "Rebuilt index",
        }
    )

    primary_key = PrimaryKeyConstraint(
        name="select",
        columns=("id",),
        definition='PRIMARY KEY ("id")',
    )
    unique_constraint = UniqueConstraint(
        name='uq "email"',
        columns=("email",),
        definition='UNIQUE ("email") DEFERRABLE INITIALLY DEFERRED',
        deferrability=ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED,
    )
    check_constraint = CheckConstraint(
        name="positive_total",
        expression="total > 0",
        definition="CHECK (total > 0)",
    )
    foreign_key = ForeignKeyConstraint(
        name='fk "customer"',
        columns=("customer_id",),
        ref_namespace="CRM",
        ref_table='Customer"Records',
        ref_columns=("id",),
        on_update=FKAction.CASCADE,
        on_delete=FKAction.SET_NULL,
        match_type=FKMatch.FULL,
        deferrability=ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED,
    )
    exclusion = ExclusionConstraint(
        name="no_overlapping_periods",
        index_method="gist",
        elements=(ExclusionElement(column_or_expr='"during"', operator="&&"),),
        predicate='WHERE ("during" IS NOT NULL)',
        definition='EXCLUDE USING gist ("during" WITH &&) WHERE ("during" IS NOT NULL)',
    )

    return (
        ("create function", CreateFunction(target=function_ref, function=function)),
        ("drop function overload", DropFunction(target=function_ref, function=function)),
        (
            "replace function",
            ReplaceFunction(
                target=function_ref,
                old_function=function,
                new_function=function.model_copy(
                    update={
                        "body": "SELECT value + 1",
                        "definition": function_definition.replace(
                            "SELECT value", "SELECT value + 1"
                        ),
                    }
                ),
            ),
        ),
        (
            "alter function owner",
            AlterFunctionOwner(
                target=function_ref,
                function=function,
                new_owner='New "Owner',
            ),
        ),
        ("create procedure", CreateProcedure(target=procedure_ref, procedure=procedure)),
        ("drop procedure overload", DropProcedure(target=procedure_ref, procedure=procedure)),
        (
            "replace procedure",
            ReplaceProcedure(
                target=procedure_ref,
                old_procedure=procedure,
                new_procedure=procedure.model_copy(
                    update={
                        "body": "SELECT value + 1",
                        "definition": procedure_definition.replace(
                            "SELECT value", "SELECT value + 1"
                        ),
                    }
                ),
            ),
        ),
        (
            "alter procedure owner",
            AlterProcedureOwner(
                target=procedure_ref,
                procedure=procedure,
                new_owner='New "Owner',
            ),
        ),
        ("create sequence", CreateSequence(target=sequence_ref, sequence=sequence)),
        ("drop sequence", DropSequence(target=sequence_ref, sequence=sequence)),
        (
            "alter sequence options",
            AlterSequenceOptions(
                target=sequence_ref,
                new_data_type="smallint",
                new_start=10,
                new_increment=2,
                new_min_value=0,
                new_max_value=100,
                new_cache=8,
                new_cycle=False,
            ),
        ),
        (
            "alter sequence owner",
            AlterSequenceOwner(target=sequence_ref, new_owner='New "Owner'),
        ),
        (
            "set sequence owned by",
            AlterSequenceOwnedBy(
                target=sequence_ref,
                new_owned_by=_column_ref(plain_table_ref, "select"),
            ),
        ),
        (
            "clear sequence owned by",
            AlterSequenceOwnedBy(target=sequence_ref, new_owned_by=None),
        ),
        ("create enum", CreateEnum(target=enum_ref, enum=enum)),
        ("create empty enum", CreateEnum(target=empty_enum.ref, enum=empty_enum)),
        ("drop enum", DropEnum(target=enum_ref, enum=enum)),
        ("append enum value", AddEnumValue(target=enum_ref, label="closed")),
        (
            "add enum value before",
            AddEnumValue(target=enum_ref, label="it's pending", before="closed"),
        ),
        (
            "add enum value after",
            AddEnumValue(target=enum_ref, label="archived", after="closed"),
        ),
        ("alter enum owner", AlterEnumAttrs(target=enum_ref, new_owner="other_owner")),
        (
            "replace enum labels blocked",
            ReplaceEnumLabels(
                target=enum_ref,
                old_labels=("open", "owner's choice"),
                new_labels=("open",),
            ),
        ),
        ("create composite type", CreateCompositeType(target=composite_ref, composite=composite)),
        ("drop composite type", DropCompositeType(target=composite_ref, composite=composite)),
        (
            "add composite attribute",
            AlterCompositeAddAttribute(
                target=composite_ref,
                attribute=CompositeAttribute(name="extra", data_type="numeric(12, 2)"),
            ),
        ),
        (
            "drop composite attribute",
            AlterCompositeDropAttribute(target=composite_ref, attribute_name="obsolete"),
        ),
        (
            "alter composite attribute type",
            AlterCompositeAttributeType(
                target=composite_ref,
                attribute_name="label",
                new_data_type="varchar(255)",
                new_collation='"C"',
            ),
        ),
        (
            "alter composite owner",
            AlterCompositeTypeAttrs(target=composite_ref, new_owner="new_owner"),
        ),
        (
            "replace composite type blocked",
            ReplaceCompositeType(
                target=composite_ref,
                old_attributes=composite.attributes,
                new_attributes=tuple(reversed(composite.attributes)),
            ),
        ),
        ("create domain", CreateDomain(target=domain_ref, domain=domain)),
        (
            "create domain with not-valid check",
            CreateDomain(
                target=domain_ref,
                domain=domain.model_copy(update={"checks": (unvalidated_domain_check,)}),
            ),
        ),
        ("drop domain", DropDomain(target=domain_ref, domain=domain)),
        (
            "set domain default",
            AlterDomainDefault(target=domain_ref, new_default_expr="0"),
        ),
        ("drop domain default", AlterDomainDefault(target=domain_ref, new_default_expr=None)),
        (
            "set domain not null",
            AlterDomainNullability(target=domain_ref, new_not_null=True),
        ),
        (
            "drop domain not null",
            AlterDomainNullability(target=domain_ref, new_not_null=False),
        ),
        (
            "add and validate domain check",
            AddDomainCheck(
                target=domain_ref,
                check=DomainCheck(name="positive", expression="VALUE > 0"),
            ),
        ),
        (
            "add not-valid domain check",
            AddDomainCheck(target=domain_ref, check=unvalidated_domain_check),
        ),
        (
            "validate domain check",
            ValidateDomainCheck(target=domain_ref, check_name="new_check"),
        ),
        (
            "drop domain check",
            DropDomainCheck(target=domain_ref, check_name="old_check"),
        ),
        (
            "alter domain owner",
            AlterDomainAttrs(target=domain_ref, new_owner="new_owner"),
        ),
        (
            "replace domain base type blocked",
            ReplaceDomainType(
                target=domain_ref,
                old_base_type="integer",
                new_base_type="text",
                old_collation=None,
                new_collation=None,
            ),
        ),
        (
            "create schema",
            CreateSchema(
                target=schema_ref,
                pg_schema=Schema(
                    ref=schema_ref,
                    owner='Role "Owner',
                    comment="Billing schema",
                ),
            ),
        ),
        (
            "drop schema",
            DropSchema(
                target=dropped_schema_ref,
                pg_schema=Schema(ref=dropped_schema_ref),
            ),
        ),
        (
            "create extension",
            CreateExtension(
                target=extension_ref,
                extension=Extension(
                    ref=extension_ref,
                    version="3.4'beta",
                    installed_schema="Extensions",
                    comment="Geo's coordinate system",
                ),
            ),
        ),
        (
            "drop extension",
            DropExtension(
                target=_extension_ref("unused_extension"),
                extension=Extension(ref=_extension_ref("unused_extension"), version="1.0"),
            ),
        ),
        (
            "alter extension version",
            AlterExtension(target=extension_ref, new_version="4.0", new_schema=None),
        ),
        (
            "alter extension schema",
            AlterExtension(target=extension_ref, new_version=None, new_schema="Extensions"),
        ),
        (
            "create plain table with column forms and attrs",
            CreateTable(target=plain_table_ref, table=plain_table),
        ),
        (
            "create unlogged table",
            CreateTable(
                target=plain_table_ref,
                table=Table(
                    ref=plain_table_ref,
                    columns=(Column(name="id", position=1, data_type="integer"),),
                    unlogged=True,
                ),
            ),
        ),
        (
            "create table with virtual generated column",
            CreateTable(
                target=account_ref,
                table=Table(
                    ref=account_ref,
                    columns=(
                        Column(name="value", position=1, data_type="integer"),
                        Column(
                            name="doubled",
                            position=2,
                            data_type="integer",
                            generated_expression="value * 2",
                            generated_kind="virtual",
                        ),
                    ),
                ),
            ),
        ),
        (
            "create partitioned parent",
            CreateTable(
                target=partition_parent_ref,
                table=Table(
                    ref=partition_parent_ref,
                    columns=(Column(name="created_at", position=1, data_type="date"),),
                    partition_info=PartitionInfo(
                        strategy=PartitionStrategy.RANGE,
                        partition_key="RANGE (created_at)",
                    ),
                ),
            ),
        ),
        (
            "create partition child",
            CreateTable(
                target=partition_child_ref,
                table=Table(
                    ref=partition_child_ref,
                    partition_of=PartitionOf(
                        parent_namespace="App Schema",
                        parent_name="events",
                        partition_bound=("FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')"),
                    ),
                ),
            ),
        ),
        (
            "drop table",
            DropTable(target=_table_ref("old_orders"), table=Table(ref=_table_ref("old_orders"))),
        ),
        (
            "rename table across schema",
            RenameTable(
                target=ObjectRef(kind=ObjectKind.TABLE, qname=old_table_name),
                old_name=old_table_name,
                new_name=QualifiedName(namespace="New Schema", name='select"copy'),
            ),
        ),
        (
            "alter table attrs",
            AlterTableAttrs(
                target=plain_table_ref,
                new_owner="New Owner",
                new_tablespace="archive",
                new_comment="",
            ),
        ),
        (
            "set table unlogged",
            AlterTableAttrs(target=plain_table_ref, new_unlogged=True),
        ),
        (
            "add nullable column",
            AddColumn(
                target=_column_ref(account_ref, "optional_note"),
                column=Column(name="optional_note", position=1, data_type="text"),
            ),
        ),
        (
            "add not-null column with default",
            AddColumn(
                target=_column_ref(account_ref, "priority"),
                column=Column(
                    name="priority",
                    position=2,
                    data_type="integer",
                    nullable=False,
                    default_expr="0",
                ),
            ),
        ),
        (
            "add identity column",
            AddColumn(
                target=_column_ref(account_ref, "generated_id"),
                column=Column(
                    name="generated_id",
                    position=3,
                    data_type="bigint",
                    nullable=False,
                    identity=IdentitySpec(
                        generated=GeneratedTiming.ALWAYS,
                        sequence_start=7,
                    ),
                ),
            ),
        ),
        (
            "add stored generated column",
            AddColumn(
                target=_column_ref(account_ref, "computed"),
                column=Column(
                    name="computed",
                    position=4,
                    data_type="integer",
                    generated_expression="quantity * unit_price",
                ),
            ),
        ),
        (
            "add virtual generated column",
            AddColumn(
                target=_column_ref(account_ref, "virtual_computed"),
                column=Column(
                    name="virtual_computed",
                    position=5,
                    data_type="integer",
                    generated_expression="quantity * unit_price",
                    generated_kind="virtual",
                ),
            ),
        ),
        (
            "add collated column",
            AddColumn(
                target=_column_ref(account_ref, 'Display "name'),
                column=Column(
                    name='Display "name',
                    position=5,
                    data_type="text",
                    collation='"App Schema"."case_insensitive"',
                ),
            ),
        ),
        (
            "drop column",
            DropColumn(
                target=_column_ref(account_ref, "legacy"),
                column=Column(name="legacy", position=1, data_type="text"),
            ),
        ),
        (
            "alter column type using and collation",
            AlterColumnType(
                target=_column_ref(account_ref, "amount"),
                new_data_type="numeric(12, 2)",
                using_expression='"amount"::numeric(12, 2)',
                new_collation='"C"',
            ),
        ),
        (
            "set column default",
            SetColumnDefault(target=_column_ref(account_ref, "created_at"), new_default="now()"),
        ),
        (
            "drop column default",
            SetColumnDefault(target=_column_ref(account_ref, "old_default"), new_default=None),
        ),
        (
            "set not null",
            SetColumnNullability(target=_column_ref(account_ref, "required"), nullable=False),
        ),
        (
            "drop not null",
            SetColumnNullability(target=_column_ref(account_ref, "optional"), nullable=True),
        ),
        (
            "rename column",
            RenameColumn(
                target=_column_ref(account_ref, "select"),
                old_name="select",
                new_name='Display "name',
            ),
        ),
        ("create unique index", CreateIndex(target=unique_index.ref, index=unique_index)),
        (
            "create partial expression include index",
            CreateIndex(target=partial_expression_index.ref, index=partial_expression_index),
        ),
        ("create non-btree index", CreateIndex(target=gin_index.ref, index=gin_index)),
        (
            "create partitioned index",
            CreateIndex(target=partitioned_index.ref, index=partitioned_index),
        ),
        (
            "drop index",
            DropIndex(
                target=_index("select", plain_table_ref, None).ref,
                index=_index("select", plain_table_ref, None),
            ),
        ),
        (
            "replace index",
            ReplaceIndex(
                target=new_replaced_index.ref,
                old_index=old_replaced_index,
                new_index=new_replaced_index,
            ),
        ),
        (
            "add primary key",
            AddConstraint(
                target=_constraint_ref(plain_table_ref, primary_key.name),
                constraint=primary_key,
            ),
        ),
        (
            "add unique constraint",
            AddConstraint(
                target=_constraint_ref(plain_table_ref, unique_constraint.name),
                constraint=unique_constraint,
            ),
        ),
        (
            "add check constraint",
            AddConstraint(
                target=_constraint_ref(plain_table_ref, check_constraint.name),
                constraint=check_constraint,
            ),
        ),
        (
            "add foreign key with actions and deferrability",
            AddConstraint(
                target=_constraint_ref(plain_table_ref, foreign_key.name),
                constraint=foreign_key,
            ),
        ),
        (
            "add exclusion constraint",
            AddConstraint(
                target=_constraint_ref(plain_table_ref, exclusion.name),
                constraint=exclusion,
            ),
        ),
        (
            "drop constraint",
            DropConstraint(
                target=_constraint_ref(plain_table_ref, "old_constraint"),
                constraint=CheckConstraint(
                    name="old_constraint",
                    expression="false",
                    definition="CHECK (false)",
                ),
            ),
        ),
    )


_EMITTER_CASES = _emitter_cases()


def _target_text(target: ObjectRef) -> str:
    if target.parent is None:
        name = quote_qualified(target.qname)
    else:
        name = f"{quote_qualified(target.parent.qname)}.{quote_ident(target.qname.name)}"
    return f"{target.kind.value} {name}"


def _delta_kind(delta: DeltaBase) -> str:
    return cast("Delta", delta).kind


def _render_emitter_corpus() -> str:
    emitter = SqlEmitter(default_handlers())
    lines: list[str] = []
    for label, delta in _EMITTER_CASES:
        lines.append(f"{label}: {_delta_kind(delta)} target={_target_text(delta.target)}")
        if isinstance(delta, (ReplaceEnumLabels, ReplaceCompositeType, ReplaceDomainType)):
            with pytest.raises(MigrationError):
                emitter.emit(DeltaSet.from_iterable((delta,)))
            lines.append("  raises MigrationError")
            continue
        for statement in emitter.emit(DeltaSet.from_iterable((delta,))):
            lines.append(
                f"  transactional={str(statement.transactional).lower()} "
                f"new_unit={str(statement.new_unit).lower()} "
                f"isolated={str(statement.isolated).lower()} sql={statement.sql}"
            )
    return "\n".join(lines)


def _pipeline_deltas() -> DeltaSet:
    schema_ref = _schema_ref("pipeline")
    customer_ref = _table_ref("customer", "pipeline")
    invoice_ref = _table_ref("invoice", "pipeline")
    legacy_ref = _table_ref("legacy", "pipeline")
    obsolete_ref = _table_ref("obsolete", "pipeline")

    create_customer = CreateTable(
        target=customer_ref,
        table=Table(
            ref=customer_ref,
            columns=(
                Column(name="id", position=1, data_type="bigint"),
                Column(name="email", position=2, data_type="text"),
            ),
        ),
    )
    create_invoice = CreateTable(
        target=invoice_ref,
        table=Table(
            ref=invoice_ref,
            columns=(
                Column(name="id", position=1, data_type="bigint"),
                Column(name="customer_id", position=2, data_type="bigint"),
                Column(name="total", position=3, data_type="numeric(12, 2)"),
                Column(name="created_at", position=4, data_type="timestamp with time zone"),
            ),
        ),
    )
    customer_pk = PrimaryKeyConstraint(
        name="customer_pkey",
        columns=("id",),
        definition='PRIMARY KEY ("id")',
    )
    customer_unique = UniqueConstraint(
        name="customer_email_key",
        columns=("email",),
        definition='UNIQUE ("email")',
    )
    invoice_check = CheckConstraint(
        name="invoice_total_check",
        expression="total >= 0",
        definition="CHECK (total >= 0)",
    )
    invoice_fk = ForeignKeyConstraint(
        name="invoice_customer_fkey",
        columns=("customer_id",),
        ref_namespace="pipeline",
        ref_table="customer",
        ref_columns=("id",),
        on_delete=FKAction.CASCADE,
        deferrability=ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED,
    )
    invoice_index = _index(
        "invoice_created_at_idx",
        invoice_ref,
        'CREATE INDEX "invoice_created_at_idx" ON "pipeline"."invoice" USING btree ("created_at")',
        key_columns=(IndexKeyColumn(column_name="created_at"),),
    )

    return DeltaSet.from_iterable(
        (
            AddConstraint(
                target=_constraint_ref(invoice_ref, invoice_fk.name),
                constraint=invoice_fk,
            ),
            create_invoice,
            DropTable(target=obsolete_ref, table=Table(ref=obsolete_ref)),
            AlterColumnType(
                target=_column_ref(legacy_ref, "amount"),
                new_data_type="numeric(12, 2)",
                using_expression='"amount"::numeric(12, 2)',
            ),
            CreateIndex(target=invoice_index.ref, index=invoice_index),
            AddConstraint(
                target=_constraint_ref(invoice_ref, invoice_check.name),
                constraint=invoice_check,
            ),
            CreateSchema(target=schema_ref, pg_schema=Schema(ref=schema_ref)),
            AddConstraint(
                target=_constraint_ref(customer_ref, customer_unique.name),
                constraint=customer_unique,
            ),
            AddConstraint(
                target=_constraint_ref(customer_ref, customer_pk.name),
                constraint=customer_pk,
            ),
            create_customer,
        )
    )


def _render_pipeline_snapshot() -> str:
    ordered = order_deltas(_pipeline_deltas())
    statements = SqlEmitter(default_handlers()).emit(ordered)
    units = split_units(statements)
    lines: list[str] = []
    for index, unit in enumerate(units):
        lines.append(f"unit[{index}] transactional={str(unit.transactional).lower()}")
        for statement in unit.statements:
            lines.append(
                f"  {_delta_kind(statement.delta)} new_unit={str(statement.new_unit).lower()} "
                f"sql={statement.sql}"
            )
    return "\n".join(lines)


def test_supported_delta_types_have_handlers_and_corpus_cases() -> None:
    supported = set(_SUPPORTED_DELTA_TYPES)
    no_emitter = {ReplaceEnumLabels, ReplaceCompositeType, ReplaceDomainType}
    emitter_supported = supported - no_emitter
    handler_types = set(default_handlers())
    corpus_types = {type(delta) for _, delta in _EMITTER_CASES}

    missing_handlers = sorted(emitter_supported - handler_types, key=lambda delta: delta.__name__)
    missing_cases = sorted(supported - corpus_types, key=lambda delta: delta.__name__)
    extra_handlers = sorted(handler_types - emitter_supported, key=lambda delta: delta.__name__)

    assert not missing_handlers, "missing default handlers: " + ", ".join(
        delta.__name__ for delta in missing_handlers
    )
    assert not missing_cases, "missing emitter corpus cases: " + ", ".join(
        delta.__name__ for delta in missing_cases
    )
    assert not extra_handlers, "handlers outside supported delta set: " + ", ".join(
        delta.__name__ for delta in extra_handlers
    )
    assert no_emitter <= supported


def test_emitter_corpus(snapshot: SnapshotAssertion) -> None:
    assert _render_emitter_corpus() == snapshot


def test_order_emit_split_pipeline(snapshot: SnapshotAssertion) -> None:
    assert _render_pipeline_snapshot() == snapshot


def test_valid_domain_check_addition_drains_old_transactions_before_validation() -> None:
    domain_ref = ObjectRef(
        kind=ObjectKind.DOMAIN_TYPE,
        qname=QualifiedName(namespace="public", name="positive"),
    )
    delta = AddDomainCheck(
        target=domain_ref,
        check=DomainCheck(name="positive_check", expression="VALUE > 0"),
    )

    statements = SqlEmitter(default_handlers()).emit(DeltaSet(deltas=(delta,)))
    units = split_units(statements)

    assert len(units) == 3
    assert all(unit.transactional for unit in units)
    assert all(len(unit.statements) == 1 for unit in units)
    assert "NOT VALID" in units[0].statements[0].sql
    drain_sql = units[1].statements[0].sql
    assert "pg_stat_activity" in drain_sql
    assert "pg_prepared_xacts" in drain_sql
    assert "pg_read_all_stats" in drain_sql
    assert "pg_sleep" in drain_sql
    assert "VALIDATE CONSTRAINT" in units[2].statements[0].sql


def test_existing_domain_check_validation_drains_old_transactions() -> None:
    domain_ref = ObjectRef(
        kind=ObjectKind.DOMAIN_TYPE,
        qname=QualifiedName(namespace="public", name="positive"),
    )
    delta = ValidateDomainCheck(target=domain_ref, check_name="positive_check")

    statements = SqlEmitter(default_handlers()).emit(DeltaSet(deltas=(delta,)))

    assert len(statements) == 2
    assert "pg_stat_activity" in statements[0].sql
    assert "VALIDATE CONSTRAINT" in statements[1].sql


def test_domain_container_alters_are_rejected_by_emitter() -> None:
    domain_ref = ObjectRef(
        kind=ObjectKind.DOMAIN_TYPE,
        qname=QualifiedName(namespace="public", name="positive"),
    )
    deltas = (
        AddDomainCheck(
            target=domain_ref,
            check=DomainCheck(name="positive_check", expression="VALUE > 0"),
            used_in_container=True,
        ),
        ValidateDomainCheck(
            target=domain_ref,
            check_name="positive_check",
            used_in_container=True,
        ),
        AlterDomainNullability(
            target=domain_ref,
            new_not_null=True,
            used_in_container=True,
        ),
    )
    emitter = SqlEmitter(default_handlers())

    for delta in deltas:
        with pytest.raises(MigrationError, match="container"):
            emitter.emit(DeltaSet(deltas=(delta,)))


@pytest.mark.unit
def test_alter_sequence_owner_unlinks_before_changing_owner() -> None:
    sequence_ref = ObjectRef(
        kind=ObjectKind.SEQUENCE,
        qname=QualifiedName(namespace="public", name="ticket_seq"),
    )
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="tickets"),
    )
    old_column = _column_ref(table_ref, "id")
    delta = AlterSequenceOwner(
        target=sequence_ref,
        new_owner="new_owner",
        old_owned_by=old_column,
    )

    statements = default_handlers()[AlterSequenceOwner](delta)

    assert tuple(statement.sql for statement in statements) == (
        'ALTER SEQUENCE "public"."ticket_seq" OWNED BY NONE',
        'ALTER SEQUENCE "public"."ticket_seq" OWNER TO "new_owner"',
    )
    assert all(statement.delta == delta for statement in statements)
