"""PostgreSQL migration executor integration tests (PostgreSQL 18)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

from pgschemadiff.application.migration.apply import ApplyResult, apply_migration
from pgschemadiff.application.migration.bundle import ValidatedBundle, load_bundle
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta import CreateIndex, CreateSchema, CreateTable, DeltaBase, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.infrastructure.postgres.applier import open_executor
from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool
from pgschemadiff.shared.errors import ApplyMigrationError
from tests.integration._plans import generate_test_migration

if TYPE_CHECKING:
    from collections.abc import Iterable


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


def _index(
    schema: str,
    table_name: str,
    name: str,
    *,
    unique: bool = False,
) -> Index:
    table_ref = _ref(ObjectKind.TABLE, schema, table_name)
    return Index(
        ref=_ref(ObjectKind.INDEX, schema, name),
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(IndexKeyColumn(column_name="value"),),
        unique=unique,
        definition=(
            f"CREATE {'UNIQUE ' if unique else ''}INDEX {name} "
            f"ON {schema}.{table_name} USING btree (value)"
        ),
    )


def _bundle(deltas: Iterable[DeltaBase], bundle_id: str) -> ValidatedBundle:
    plan = generate_test_migration(
        DeltaSet.from_iterable(deltas),
        max_risk=RiskLevel.DANGEROUS,
        slug="adapter-test",
        clock=lambda: datetime(2026, 10, 24, tzinfo=UTC),
        id_factory=lambda: bundle_id,
    )
    files = dict(render_bundle(plan).files)
    return load_bundle(files["manifest.json"], files["up.sql"])


def _create_schema_and_table(schema: str, table_name: str) -> tuple[DeltaBase, ...]:
    schema_ref = _ref(ObjectKind.SCHEMA, schema, schema)
    table = _table(schema, table_name)
    return (
        CreateSchema(target=schema_ref, pg_schema=Schema(ref=schema_ref)),
        CreateTable(target=table.ref, table=table),
    )


async def _run_sql(dsn: str, *statements: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        for statement in statements:
            await conn.execute(statement)


@pytest.mark.integration
async def test_executor_sets_session_settings_and_releases_database_lock(pg_test_dsn: str) -> None:
    async with open_executor(
        pg_test_dsn,
        lock_timeout_ms=1_234,
        statement_timeout_ms=2_345,
    ) as executor:
        row = await (
            await executor._conn.execute(
                "SELECT current_setting('standard_conforming_strings'), "
                "current_setting('lock_timeout'), current_setting('statement_timeout'), "
                "current_setting('application_name'), current_setting('search_path')"
            )
        ).fetchone()
        assert row == ("on", "1234ms", "2345ms", "pgschemadiff apply", "pg_catalog")

        with pytest.raises(ApplyMigrationError) as exc_info:
            async with open_executor(pg_test_dsn, lock_timeout_ms=100):
                pass
        assert str(exc_info.value) == "Another pgschemadiff apply holds the migration lock."

    async with open_executor(pg_test_dsn, lock_timeout_ms=100):
        pass


@pytest.mark.integration
async def test_load_history_without_schema_does_not_bootstrap(pg_test_dsn: str) -> None:
    async with open_executor(pg_test_dsn) as executor:
        assert await executor.load_history("not-recorded") is None

    async with await psycopg.AsyncConnection.connect(pg_test_dsn) as conn:
        exists = await (
            await conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s)",
                ("pgschemadiff",),
            )
        ).fetchone()
    assert exists == (False,)


@pytest.mark.integration
async def test_fresh_bundle_applies_with_history_and_inspector_exclusion(pg_test_dsn: str) -> None:
    schema = "apply_fresh"
    table = _table(schema, "items")
    index = _index(schema, "items", "items_value_idx")
    schema_ref = _ref(ObjectKind.SCHEMA, schema, schema)
    bundle = _bundle(
        (
            CreateSchema(target=schema_ref, pg_schema=Schema(ref=schema_ref)),
            CreateTable(target=table.ref, table=table),
            CreateIndex(target=index.ref, index=index),
        ),
        "fresh-apply-bundle",
    )

    async with open_executor(pg_test_dsn) as executor:
        before = await (await executor._conn.execute("SELECT pg_backend_pid()")).fetchone()
        result = await apply_migration(bundle, executor, approve_destructive=True)
        after = await (await executor._conn.execute("SELECT pg_backend_pid()")).fetchone()
        assert before == after
    assert result.status == "applied"

    async with await psycopg.AsyncConnection.connect(pg_test_dsn) as conn:
        objects = await (
            await conn.execute(
                "SELECT to_regclass(%s), to_regclass(%s)",
                ("apply_fresh.items", "apply_fresh.items_value_idx"),
            )
        ).fetchone()
    assert objects == ("apply_fresh.items", "apply_fresh.items_value_idx")

    async with open_executor(pg_test_dsn) as executor:
        history = await executor.load_history(bundle.id)
    assert history is not None
    assert history.status == "applied"
    assert all(unit.status == "applied" for unit in history.units)

    async with Pool(pg_test_dsn) as pool:
        database = await PgCatalogInspector(pool).inspect()
    assert "pgschemadiff" not in {schema.name for schema in database.schemas}
    assert "items" in {
        table.ref.qname.name
        for schema in database.schemas
        if schema.name == "apply_fresh"
        for table in schema.tables
    }


@pytest.mark.integration
async def test_transactional_failure_rolls_back_and_resumes_after_operator_fix(
    pg_test_dsn: str,
) -> None:
    await _run_sql(pg_test_dsn, 'CREATE SCHEMA "apply_retry"')
    table = _table("apply_retry", "items", default_expr="apply_retry.retry_value()")
    bundle = _bundle((CreateTable(target=table.ref, table=table),), "transactional-retry")

    with pytest.raises(ApplyMigrationError) as exc_info:
        async with open_executor(pg_test_dsn) as executor:
            await apply_migration(bundle, executor, approve_destructive=True)
    failure = exc_info.value.result
    assert isinstance(failure, ApplyResult)
    assert failure.status == "failed"
    assert failure.sqlstate == "42883"

    async with await psycopg.AsyncConnection.connect(pg_test_dsn) as conn:
        table_missing = await (
            await conn.execute("SELECT to_regclass(%s)", ("apply_retry.items",))
        ).fetchone()
    assert table_missing == (None,)

    async with open_executor(pg_test_dsn) as executor:
        failed_history = await executor.load_history(bundle.id)
    assert failed_history is not None
    assert failed_history.status == "failed"
    assert failed_history.units[0].status == "failed"
    async with await psycopg.AsyncConnection.connect(pg_test_dsn) as conn:
        unit_times = await (
            await conn.execute(
                "SELECT started_at, finished_at FROM pgschemadiff.migration_units "
                "WHERE bundle_id = %s AND unit_index = %s",
                (bundle.id, 0),
            )
        ).fetchone()
    assert unit_times is not None
    assert unit_times[0] is not None
    assert unit_times[1] is not None
    assert unit_times[0] <= unit_times[1]

    await _run_sql(
        pg_test_dsn,
        "CREATE FUNCTION apply_retry.retry_value() RETURNS integer "
        "LANGUAGE sql IMMUTABLE AS 'SELECT 1'",
    )
    async with open_executor(pg_test_dsn) as executor:
        result = await apply_migration(bundle, executor, approve_destructive=True)
        resumed_history = await executor.load_history(bundle.id)

    assert result.status == "applied"
    assert result.resumed
    assert resumed_history is not None
    assert resumed_history.status == "applied"
    assert resumed_history.units[0].status == "applied"


@pytest.mark.integration
async def test_failed_concurrent_unique_index_is_recorded_not_dropped(pg_test_dsn: str) -> None:
    await _run_sql(
        pg_test_dsn,
        'CREATE SCHEMA "apply_nontransactional"',
        "CREATE TABLE apply_nontransactional.items (id integer, value integer)",
        "INSERT INTO apply_nontransactional.items VALUES (1, 7), (2, 7)",
    )
    index = _index(
        "apply_nontransactional",
        "items",
        "items_value_unique_idx",
        unique=True,
    )
    bundle = _bundle((CreateIndex(target=index.ref, index=index),), "nontransactional-failure")

    with pytest.raises(ApplyMigrationError) as exc_info:
        async with open_executor(pg_test_dsn) as executor:
            await apply_migration(bundle, executor, approve_destructive=True)
    failure = exc_info.value.result
    assert isinstance(failure, ApplyResult)
    assert failure.manual_inspection_required
    assert failure.sqlstate == "23505"

    async with await psycopg.AsyncConnection.connect(pg_test_dsn) as conn:
        index_state = await (
            await conn.execute(
                "SELECT i.indisvalid FROM pg_catalog.pg_index AS i "
                "JOIN pg_catalog.pg_class AS c ON c.oid = i.indexrelid "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relname = %s",
                ("apply_nontransactional", "items_value_unique_idx"),
            )
        ).fetchone()
    assert index_state == (False,)

    async with open_executor(pg_test_dsn) as executor:
        history = await executor.load_history(bundle.id)
    assert history is not None
    assert history.status == "failed"
    assert history.units[0].status == "failed"


@pytest.mark.integration
async def test_incompatible_history_schema_fails_before_bundle_sql(pg_test_dsn: str) -> None:
    await _run_sql(
        pg_test_dsn,
        "CREATE SCHEMA pgschemadiff",
        "CREATE TABLE pgschemadiff.migration_runs (unexpected integer)",
    )
    bundle = _bundle(_create_schema_and_table("apply_collision", "items"), "layout-collision")

    with pytest.raises(ApplyMigrationError, match="history schema"):
        async with open_executor(pg_test_dsn) as executor:
            await apply_migration(bundle, executor, approve_destructive=True)

    async with await psycopg.AsyncConnection.connect(pg_test_dsn) as conn:
        table_missing = await (
            await conn.execute("SELECT to_regclass(%s)", ("apply_collision.items",))
        ).fetchone()
    assert table_missing == (None,)
