from types import UnionType
from typing import Annotated, Union, get_args, get_origin

import pytest
from syrupy.assertion import SnapshotAssertion

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.application.sql_emit import default_handlers, schema_emitter
from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlHandler
from pgschemadiff.application.sql_emit.transaction import split_units
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import ForeignKeyConstraint, PrimaryKeyConstraint
from pgschemadiff.domain.delta import (
    AddColumn,
    AddConstraint,
    CreateIndex,
    CreateSchema,
    CreateTable,
    Delta,
    DeltaBase,
    DeltaSet,
    ReplaceCompositeType,
    ReplaceDomainType,
    ReplaceEnumLabels,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.shared.errors import MigrationError


def _union_members(annotation: object) -> set[type[DeltaBase]]:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _union_members(get_args(annotation)[0])
    if origin in (Union, UnionType):
        return set().union(*(_union_members(member) for member in get_args(annotation)))
    if isinstance(annotation, type) and issubclass(annotation, DeltaBase):
        return {annotation}
    raise AssertionError(f"Unexpected Delta union member: {annotation!r}")


def test_default_handlers_cover_every_emittable_delta_union_member() -> None:
    members = _union_members(Delta) - {
        ReplaceCompositeType,
        ReplaceDomainType,
        ReplaceEnumLabels,
    }
    handlers = default_handlers()

    assert set(handlers) == members
    assert len(handlers) == len(members)
    assert all(callable(handler) for handler in handlers.values())


def test_default_handlers_returns_a_fresh_mapping() -> None:
    first = default_handlers()
    second = default_handlers()

    assert first is not second
    first.clear()
    assert second


def test_duplicate_handler_registration_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def duplicate_handlers() -> dict[type[DeltaBase], SqlHandler]:
        return {CreateTable: lambda _delta: ()}

    monkeypatch.setattr(schema_emitter, "handlers", duplicate_handlers)

    with pytest.raises(MigrationError, match="CreateTable"):
        default_handlers()


def _object_ref(kind: ObjectKind, namespace: str, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace=namespace, name=name))


def _constraint_ref(table: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=table.qname.namespace, name=name),
        parent=table,
    )


def test_ordered_delta_set_emits_valid_migration_order(snapshot: SnapshotAssertion) -> None:
    schema_ref = _object_ref(ObjectKind.SCHEMA, "public", "app")
    create_schema = CreateSchema(target=schema_ref, pg_schema=Schema(ref=schema_ref))

    accounts_ref = _object_ref(ObjectKind.TABLE, "app", "accounts")
    accounts = Table(
        ref=accounts_ref,
        columns=(
            Column(name="id", position=1, data_type="integer", nullable=False),
            Column(name="email", position=2, data_type="text"),
        ),
    )
    create_accounts = CreateTable(target=accounts_ref, table=accounts)
    accounts_pk = PrimaryKeyConstraint(
        name="accounts_pkey",
        columns=("id",),
        definition='PRIMARY KEY ("id")',
    )
    add_accounts_pk = AddConstraint(
        target=_constraint_ref(accounts_ref, accounts_pk.name),
        constraint=accounts_pk,
    )

    orders_ref = _object_ref(ObjectKind.TABLE, "app", "orders")
    orders = Table(
        ref=orders_ref,
        columns=(
            Column(name="id", position=1, data_type="integer", nullable=False),
            Column(name="account_id", position=2, data_type="integer", nullable=False),
            Column(name="status", position=3, data_type="text"),
        ),
    )
    create_orders = CreateTable(target=orders_ref, table=orders)
    orders_pk = PrimaryKeyConstraint(
        name="orders_pkey",
        columns=("id",),
        definition='PRIMARY KEY ("id")',
    )
    add_orders_pk = AddConstraint(
        target=_constraint_ref(orders_ref, orders_pk.name),
        constraint=orders_pk,
    )
    orders_fk = ForeignKeyConstraint(
        name="orders_account_fkey",
        columns=("account_id",),
        ref_namespace="app",
        ref_table="accounts",
        ref_columns=("id",),
    )
    add_orders_fk = AddConstraint(
        target=_constraint_ref(orders_ref, orders_fk.name),
        constraint=orders_fk,
    )

    index_ref = _object_ref(ObjectKind.INDEX, "app", "orders_account_id_idx")
    index = Index(
        ref=index_ref,
        table_ref=orders_ref,
        method=IndexMethod.BTREE,
        key_columns=(IndexKeyColumn(column_name="account_id"),),
        definition=(
            'CREATE INDEX "orders_account_id_idx" ON "app"."orders" USING btree ("account_id")'
        ),
    )
    create_index = CreateIndex(target=index_ref, index=index)

    legacy_ref = _object_ref(ObjectKind.TABLE, "public", "legacy")
    new_column = Column(
        name="display_name",
        position=3,
        data_type="text",
        default_expr="'Guest'::text",
    )
    add_column = AddColumn(
        target=ObjectRef(
            kind=ObjectKind.COLUMN,
            qname=QualifiedName(namespace="public", name=new_column.name),
            parent=legacy_ref,
        ),
        column=new_column,
    )

    unordered = DeltaSet.from_iterable(
        (
            add_orders_fk,
            create_index,
            add_column,
            create_orders,
            add_orders_pk,
            create_schema,
            add_accounts_pk,
            create_accounts,
        )
    )
    ordered = order_deltas(unordered)
    statements = SqlEmitter(default_handlers()).emit(ordered)
    sql = tuple(statement.sql for statement in statements)

    accounts_create_index = next(
        index
        for index, statement in enumerate(sql)
        if statement.startswith('CREATE TABLE "app"."accounts"')
    )
    orders_create_index = next(
        index
        for index, statement in enumerate(sql)
        if statement.startswith('CREATE TABLE "app"."orders"')
    )
    fk_add_index = next(
        index
        for index, statement in enumerate(statements)
        if 'ADD CONSTRAINT "orders_account_fkey"' in statement.sql
    )
    fk_validate_index = next(
        index
        for index, statement in enumerate(statements)
        if 'VALIDATE CONSTRAINT "orders_account_fkey"' in statement.sql
    )
    concurrent_index = next(
        statement for statement in statements if "CREATE INDEX CONCURRENTLY" in statement.sql
    )

    assert accounts_create_index < orders_create_index < fk_add_index < fk_validate_index
    assert statements[fk_add_index].sql.endswith("NOT VALID")
    assert statements[fk_validate_index].new_unit is True
    assert concurrent_index.transactional is False
    assert (
        tuple(
            (statement.sql, statement.transactional, statement.new_unit) for statement in statements
        )
        == snapshot
    )

    units = split_units(statements)
    assert tuple((unit.transactional, len(unit.statements)) for unit in units) == (
        (True, 6),
        (False, 1),
        (True, 1),
        (True, 1),
    )
    assert units[1].statements == (concurrent_index,)
    assert units[3].statements == (statements[fk_validate_index],)
