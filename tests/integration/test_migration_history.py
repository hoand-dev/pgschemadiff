"""Read-only PostgreSQL migration history tests (PostgreSQL 18)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

from pgschemadiff.application.migration.apply import apply_migration
from pgschemadiff.application.migration.bundle import ValidatedBundle, load_bundle
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.history import (
    MigrationHistoryUnavailableError,
    list_migration_history,
)
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta import CreateIndex, CreateSchema, CreateTable, DeltaBase, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.infrastructure.postgres.applier import (
    _ADVISORY_LOCK_KEY_1,
    _ADVISORY_LOCK_KEY_2,
    open_executor,
)
from pgschemadiff.infrastructure.postgres.history import (
    PostgresMigrationHistoryReader,
    _open_read_only_connection,
)
from pgschemadiff.shared.errors import ApplyMigrationError

if TYPE_CHECKING:
    from collections.abc import Iterable


_FAILURE_SQL = "history_missing_function('HISTORY_SQL_SENTINEL')"


def _ref(kind: ObjectKind, schema: str, name: str) -> ObjectRef:
    namespace = "public" if kind is ObjectKind.SCHEMA else schema
    return ObjectRef(kind=kind, qname=QualifiedName(namespace=namespace, name=name))


def _table(schema: str, name: str, *, default_expr: str | None = None) -> Table:
    return Table(
        ref=_ref(ObjectKind.TABLE, schema, name),
        columns=(
            Column(name="id", position=1, data_type="integer", nullable=False),
            Column(
                name="value",
                position=2,
                data_type="integer",
                nullable=False,
                default_expr=default_expr,
            ),
        ),
    )


def _index(schema: str, table_name: str, name: str) -> Index:
    table_ref = _ref(ObjectKind.TABLE, schema, table_name)
    return Index(
        ref=_ref(ObjectKind.INDEX, schema, name),
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(IndexKeyColumn(column_name="value"),),
        definition=(f"CREATE INDEX {name} ON {schema}.{table_name} USING btree (value)"),
    )


def _bundle(deltas: Iterable[DeltaBase], bundle_id: str) -> tuple[ValidatedBundle, str]:
    plan = generate_migration(
        DeltaSet.from_iterable(deltas),
        max_risk=RiskLevel.DANGEROUS,
        slug="history-test",
        clock=lambda: datetime(2026, 10, 26, tzinfo=UTC),
        id_factory=lambda: bundle_id,
    )
    files = dict(render_bundle(plan).files)
    manifest = json.loads(files["manifest.json"])
    checksum = manifest["checksums"]["up_sql_sha256"]
    return load_bundle(files["manifest.json"], files["up.sql"]), checksum


async def _run_sql(dsn: str, *statements: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        for statement in statements:
            await conn.execute(statement)


@pytest.mark.integration
async def test_history_is_empty_when_schema_or_tables_are_missing(pg_test_dsn: str) -> None:
    reader = PostgresMigrationHistoryReader(pg_test_dsn)

    assert await list_migration_history(reader) == ()

    async with await psycopg.AsyncConnection.connect(pg_test_dsn) as conn:
        schema_exists = await (
            await conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
                "WHERE nspname = 'pgschemadiff')"
            )
        ).fetchone()
    assert schema_exists == (False,)

    await _run_sql(pg_test_dsn, "CREATE SCHEMA pgschemadiff")
    assert await list_migration_history(reader) == ()


@pytest.mark.integration
async def test_history_reads_applied_run_and_ordered_units(pg_test_dsn: str) -> None:
    schema = "history_applied"
    schema_ref = _ref(ObjectKind.SCHEMA, schema, schema)
    table = _table(schema, "items")
    index = _index(schema, "items", "items_value_idx")
    bundle, manifest_checksum = _bundle(
        (
            CreateSchema(target=schema_ref, pg_schema=Schema(ref=schema_ref)),
            CreateTable(target=table.ref, table=table),
            CreateIndex(target=index.ref, index=index),
        ),
        "history-applied-bundle",
    )

    async with open_executor(pg_test_dsn) as executor:
        result = await apply_migration(bundle, executor, approve_destructive=True)
    assert result.status == "applied"

    runs = await list_migration_history(PostgresMigrationHistoryReader(pg_test_dsn))

    assert len(runs) == 1
    run = runs[0]
    assert run.bundle_id == bundle.id
    assert run.status == "applied"
    assert run.finished_at is not None
    assert run.started_at <= run.finished_at
    assert run.up_sql_sha256 == manifest_checksum
    assert [unit.index for unit in run.units] == list(range(len(bundle.units)))
    assert [unit.status for unit in run.units] == ["applied"] * len(bundle.units)
    assert [unit.transactional for unit in run.units] == [
        unit.transactional for unit in bundle.units
    ]
    for unit in run.units:
        assert unit.started_at is not None
        assert unit.finished_at is not None
        assert unit.started_at <= unit.finished_at


@pytest.mark.integration
async def test_history_exposes_only_safe_failure_metadata(pg_test_dsn: str) -> None:
    schema = "history_failure"
    await _run_sql(pg_test_dsn, f'CREATE SCHEMA "{schema}"')
    table = _table(schema, "items", default_expr=_FAILURE_SQL)
    bundle, _manifest_checksum = _bundle(
        (CreateTable(target=table.ref, table=table),),
        "history-failed-bundle",
    )

    with pytest.raises(ApplyMigrationError):
        async with open_executor(pg_test_dsn) as executor:
            await apply_migration(bundle, executor, approve_destructive=True)

    runs = await list_migration_history(PostgresMigrationHistoryReader(pg_test_dsn))

    assert len(runs) == 1
    run = runs[0]
    assert run.status == "failed"
    assert len(run.units) == 1
    unit = run.units[0]
    assert unit.index == 0
    assert unit.status == "failed"
    assert unit.failed_statement_index == 0
    assert unit.error_class == "UndefinedFunction"
    assert unit.sqlstate == "42883"
    assert _FAILURE_SQL not in repr(asdict(run))
    assert "HISTORY_SQL_SENTINEL" not in repr(asdict(run))


@pytest.mark.integration
async def test_history_reader_does_not_wait_for_migration_advisory_lock(
    pg_test_dsn: str,
) -> None:
    holder = await psycopg.AsyncConnection.connect(pg_test_dsn, autocommit=True)
    try:
        await holder.execute(
            "SELECT pg_catalog.pg_advisory_lock(%s, %s)",
            (_ADVISORY_LOCK_KEY_1, _ADVISORY_LOCK_KEY_2),
        )
        runs = await asyncio.wait_for(
            list_migration_history(PostgresMigrationHistoryReader(pg_test_dsn)),
            timeout=2,
        )
        assert runs == ()
    finally:
        await holder.execute(
            "SELECT pg_catalog.pg_advisory_unlock(%s, %s)",
            (_ADVISORY_LOCK_KEY_1, _ADVISORY_LOCK_KEY_2),
        )
        await holder.close()


@pytest.mark.integration
async def test_history_reader_rejects_incompatible_layout(pg_test_dsn: str) -> None:
    await _run_sql(
        pg_test_dsn,
        "CREATE SCHEMA pgschemadiff",
        "CREATE TABLE pgschemadiff.migration_runs (unexpected integer)",
    )

    with pytest.raises(MigrationHistoryUnavailableError):
        await list_migration_history(PostgresMigrationHistoryReader(pg_test_dsn))


@pytest.mark.integration
async def test_history_connection_is_read_only(pg_test_dsn: str) -> None:
    async with _open_read_only_connection(pg_test_dsn) as conn:
        assert await (
            await conn.execute(
                "SELECT current_setting('search_path'), "
                "current_setting('statement_timeout'), "
                "current_setting('default_transaction_read_only')"
            )
        ).fetchone() == ("pg_catalog", "10s", "on")

        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            async with conn.transaction():
                await conn.execute("CREATE TABLE public.history_readonly_probe (id integer)")
