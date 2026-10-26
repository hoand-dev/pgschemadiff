"""Read persisted migration history through a read-only PostgreSQL session."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import psycopg

from pgschemadiff.application.migration.history import (
    MigrationHistoryRun,
    MigrationHistoryUnavailableError,
    MigrationHistoryUnit,
)
from pgschemadiff.infrastructure.postgres.applier import (
    _check_history_layout,
)
from pgschemadiff.infrastructure.postgres.applier import (
    _map_history_rows as _map_applier_history_rows,
)
from pgschemadiff.shared.errors import ApplyMigrationError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence


_HISTORY_COLUMNS_SQL = (
    "SELECT c.relname, c.relkind::text, a.attname, "
    "       pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull "
    "FROM pg_catalog.pg_class AS c "
    "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
    "LEFT JOIN pg_catalog.pg_attribute AS a "
    "  ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
    "WHERE n.nspname = 'pgschemadiff' AND c.relkind NOT IN ('i', 'I', 't') "
    "ORDER BY c.relname, a.attnum"
)
_HISTORY_CONSTRAINTS_SQL = (
    "SELECT c.relname, con.conname, con.contype::text, "
    "       pg_catalog.pg_get_constraintdef(con.oid, true) "
    "FROM pg_catalog.pg_constraint AS con "
    "JOIN pg_catalog.pg_class AS c ON c.oid = con.conrelid "
    "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'pgschemadiff' AND con.contype <> 'n' "
    "ORDER BY c.relname, con.conname"
)
_HISTORY_ROWS_SQL = (
    "SELECT r.bundle_id, r.status, r.started_at, r.finished_at, r.up_sql_sha256, "
    "       u.unit_index, u.sql_sha256, u.status, u.transactional, "
    "       u.started_at, u.finished_at, "
    "       u.failed_statement_index, u.error_class, u.sqlstate "
    "FROM ("
    "    SELECT bundle_id, status, started_at, finished_at, up_sql_sha256 "
    "    FROM pgschemadiff.migration_runs "
    "    ORDER BY started_at DESC, bundle_id "
    "    LIMIT %s"
    ") AS r "
    "LEFT JOIN pgschemadiff.migration_units AS u ON u.bundle_id = r.bundle_id "
    "ORDER BY r.started_at DESC, r.bundle_id, u.unit_index"
)


class PostgresMigrationHistoryReader:
    """Read the target database's persisted migration history."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo

    async def list_history(self, *, limit: int = 50) -> tuple[MigrationHistoryRun, ...]:
        """Return at most ``limit`` runs, newest first, without taking the apply lock."""
        async with _open_read_only_connection(self._conninfo) as connection:
            cursor = await connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
                "WHERE nspname = 'pgschemadiff')"
            )
            schema_row = await cursor.fetchone()
            if schema_row is None or schema_row[0] is not True:
                return ()

            columns_cursor = await connection.execute(_HISTORY_COLUMNS_SQL)
            column_rows = await columns_cursor.fetchall()
            if not column_rows:
                return ()

            constraints_cursor = await connection.execute(_HISTORY_CONSTRAINTS_SQL)
            constraint_rows = await constraints_cursor.fetchall()
            try:
                _check_history_layout(True, column_rows, constraint_rows)
            except ApplyMigrationError as error:
                raise MigrationHistoryUnavailableError(
                    "Incompatible pgschemadiff migration history layout."
                ) from error

            history_cursor = await connection.execute(_HISTORY_ROWS_SQL, (limit,))
            rows = await history_cursor.fetchall()
            return _map_history_rows(rows)


@asynccontextmanager
async def _open_read_only_connection(
    conninfo: str,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Open one bounded, read-only connection without acquiring an advisory lock."""
    connection = await psycopg.AsyncConnection.connect(conninfo, autocommit=True)
    try:
        await connection.execute("SET SESSION search_path TO pg_catalog")
        await connection.execute("SET SESSION statement_timeout TO '10s'")
        await connection.execute("SET SESSION default_transaction_read_only TO on")
        yield connection
    finally:
        await connection.close()


def _map_history_rows(rows: Sequence[Sequence[object]]) -> tuple[MigrationHistoryRun, ...]:
    grouped_rows: list[list[Sequence[object]]] = []
    for row in rows:
        if len(row) != 14:
            raise _invalid_history_data()
        if not grouped_rows or grouped_rows[-1][0][0] != row[0]:
            grouped_rows.append([])
        grouped_rows[-1].append(row)
    return tuple(_map_run_rows(group) for group in grouped_rows)


def _map_run_rows(rows: Sequence[Sequence[object]]) -> MigrationHistoryRun:
    first_row = rows[0]
    bundle_id, _status, started_at, finished_at, _checksum = first_row[:5]
    if (
        not isinstance(bundle_id, str)
        or not isinstance(started_at, datetime)
        or (finished_at is not None and not isinstance(finished_at, datetime))
    ):
        raise _invalid_history_data()

    applier_unit_rows: list[tuple[object, ...]] = []
    selected_unit_rows: list[Sequence[object]] = []
    for row in rows:
        unit_index = row[5]
        if unit_index is not None:
            applier_unit_rows.append((unit_index, row[6], row[8], row[7]))
            selected_unit_rows.append(row)
    try:
        history = _map_applier_history_rows(
            (_status, _checksum),
            applier_unit_rows,
        )
    except ApplyMigrationError as error:
        raise _invalid_history_data() from error

    units = tuple(
        MigrationHistoryUnit(
            index=unit.index,
            status=unit.status,
            transactional=unit.transactional,
            started_at=cast("datetime | None", row[9]),
            finished_at=cast("datetime | None", row[10]),
            failed_statement_index=cast("int | None", row[11]),
            error_class=cast("str | None", row[12]),
            sqlstate=cast("str | None", row[13]),
        )
        for unit, row in zip(history.units, selected_unit_rows, strict=True)
    )
    return MigrationHistoryRun(
        bundle_id=bundle_id,
        status=history.status,
        started_at=started_at,
        finished_at=finished_at,
        up_sql_sha256=history.up_sql_sha256,
        units=units,
    )


def _invalid_history_data() -> MigrationHistoryUnavailableError:
    return MigrationHistoryUnavailableError("PostgreSQL migration history contains invalid data.")
