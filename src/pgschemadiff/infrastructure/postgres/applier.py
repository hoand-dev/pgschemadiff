"""PostgreSQL migration executor and target-database history adapter.

This adapter pins one psycopg async connection for each apply run. It uses a
direct connection instead of ``Pool``: the pool cannot set autocommit and adds
nothing for the one connection that must remain pinned for the whole run.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import psycopg

from pgschemadiff.application.migration.ports import (
    BundleHistory,
    UnitFailure,
    UnitHistory,
)
from pgschemadiff.shared.errors import ApplyMigrationError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from pgschemadiff.application.migration.bundle import BundleUnit, ValidatedBundle
    from pgschemadiff.application.migration.ports import (
        RunFailure,
        RunFinishStatus,
        RunStatus,
        StatementObserver,
        UnitStatus,
    )


_MAX_TIMEOUT_MS = 86_400_000
_ADVISORY_LOCK_KEY_1 = 1_347_838_788  # 0x50475344, ASCII "PGSD".
_ADVISORY_LOCK_KEY_2 = 1  # One global migration lock per database.
_HISTORY_SCHEMA = "pgschemadiff"
_RUN_TABLE = "pgschemadiff.migration_runs"
_UNIT_TABLE = "pgschemadiff.migration_units"
_RUN_STATUSES = frozenset({"running", "applied", "failed", "cancelled"})
_UNIT_STATUSES = frozenset({"pending", "running", "applied", "failed"})
_EXPECTED_COLUMNS: dict[str, dict[str, tuple[str, bool]]] = {
    "migration_runs": {
        "bundle_id": ("text", True),
        "up_sql_sha256": ("text", True),
        "status": ("text", True),
        "started_at": ("timestamp with time zone", True),
        "finished_at": ("timestamp with time zone", False),
        "failed_unit_index": ("integer", False),
        "failed_statement_index": ("integer", False),
        "error_class": ("text", False),
        "sqlstate": ("text", False),
    },
    "migration_units": {
        "bundle_id": ("text", True),
        "unit_index": ("integer", True),
        "sql_sha256": ("text", True),
        "transactional": ("boolean", True),
        "status": ("text", True),
        "started_at": ("timestamp with time zone", False),
        "finished_at": ("timestamp with time zone", False),
        "failed_statement_index": ("integer", False),
        "error_class": ("text", False),
        "sqlstate": ("text", False),
    },
}
_EXPECTED_CONSTRAINTS: dict[str, dict[str, str]] = {
    "migration_runs": {
        "migration_runs_pkey": "p",
        "migration_runs_status_check": "c",
    },
    "migration_units": {
        "migration_units_pkey": "p",
        "migration_units_status_check": "c",
        "migration_units_bundle_id_fkey": "f",
    },
}
_EXPECTED_STATUSES = {
    "migration_runs": frozenset({"running", "applied", "failed", "cancelled"}),
    "migration_units": frozenset({"pending", "running", "applied", "failed"}),
}


def _validate_timeout_ms(value: object, *, name: str) -> int:
    """Validate a libpq timeout in milliseconds, capped at 24 hours."""
    if type(value) is not int or value < 0 or value > _MAX_TIMEOUT_MS:
        raise ValueError(f"{name} must be an integer from 0 to {_MAX_TIMEOUT_MS} milliseconds.")
    return value


def _safe_database_error(
    error: psycopg.Error,
    *,
    message: str,
    lock_contention: bool = False,
) -> ApplyMigrationError:
    """Create a user-safe error without copying driver text or SQL."""
    if lock_contention and error.sqlstate == "55P03":
        message = "Another pgschemadiff apply holds the migration lock."
    return ApplyMigrationError(message)


def _map_history_rows(
    run_row: Sequence[object],
    unit_rows: Sequence[Sequence[object]],
) -> BundleHistory:
    """Map database result tuples into the migration history port models."""
    if len(run_row) != 2:
        raise ApplyMigrationError("Migration history is corrupt.")
    status, up_sql_sha256 = run_row
    if (
        not isinstance(status, str)
        or status not in _RUN_STATUSES
        or not isinstance(up_sql_sha256, str)
        or not _is_sha256(up_sql_sha256)
    ):
        raise ApplyMigrationError("Migration history is corrupt.")

    units: list[UnitHistory] = []
    for row in unit_rows:
        if len(row) != 4:
            raise ApplyMigrationError("Migration history is corrupt.")
        index, sql_sha256, transactional, unit_status = row
        if (
            type(index) is not int
            or index < 0
            or not isinstance(sql_sha256, str)
            or not _is_sha256(sql_sha256)
            or type(transactional) is not bool
            or not isinstance(unit_status, str)
            or unit_status not in _UNIT_STATUSES
        ):
            raise ApplyMigrationError("Migration history is corrupt.")
        units.append(
            UnitHistory(
                index=index,
                sql_sha256=sql_sha256,
                transactional=transactional,
                status=cast("UnitStatus", unit_status),
            )
        )

    return BundleHistory(
        status=cast("RunStatus", status),
        up_sql_sha256=up_sql_sha256,
        units=tuple(units),
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _check_history_layout(
    schema_exists: bool,
    column_rows: Sequence[tuple[str, str, str | None, str | None, bool | None]],
    constraint_rows: Sequence[tuple[str, str, str, str]],
) -> None:
    """Reject an existing reserved schema unless its full table layout matches."""
    if not schema_exists:
        return

    _check_history_columns(column_rows)
    _check_history_constraints(constraint_rows)


def _check_history_columns(
    rows: Sequence[tuple[str, str, str | None, str | None, bool | None]],
) -> None:
    columns_by_table: dict[str, dict[str, tuple[str, bool]]] = {}
    for table_name, relation_kind, column_name, data_type, not_null in rows:
        expected_columns = _EXPECTED_COLUMNS.get(table_name)
        if expected_columns is None or relation_kind != "r":
            raise ApplyMigrationError("Incompatible pgschemadiff history schema.")
        columns = columns_by_table.setdefault(table_name, {})
        if column_name is not None:
            if not isinstance(data_type, str) or type(not_null) is not bool:
                raise ApplyMigrationError("Incompatible pgschemadiff history schema.")
            columns[column_name] = (data_type, not_null)

    if set(columns_by_table) != set(_EXPECTED_COLUMNS) or any(
        columns_by_table[table_name] != expected_columns
        for table_name, expected_columns in _EXPECTED_COLUMNS.items()
    ):
        raise ApplyMigrationError("Incompatible pgschemadiff history schema.")


def _check_history_constraints(rows: Sequence[tuple[str, str, str, str]]) -> None:
    constraints_by_table: dict[str, dict[str, tuple[str, str]]] = {}
    for table_name, constraint_name, constraint_type, definition in rows:
        expected_constraints = _EXPECTED_CONSTRAINTS.get(table_name)
        if expected_constraints is None or constraint_name not in expected_constraints:
            raise ApplyMigrationError("Incompatible pgschemadiff history schema.")
        if expected_constraints[constraint_name] != constraint_type:
            raise ApplyMigrationError("Incompatible pgschemadiff history schema.")
        constraints = constraints_by_table.setdefault(table_name, {})
        if constraint_name in constraints:
            raise ApplyMigrationError("Incompatible pgschemadiff history schema.")
        constraints[constraint_name] = (constraint_type, definition)

    if set(constraints_by_table) != set(_EXPECTED_CONSTRAINTS):
        raise ApplyMigrationError("Incompatible pgschemadiff history schema.")
    for table_name, expected_constraints in _EXPECTED_CONSTRAINTS.items():
        constraints = constraints_by_table[table_name]
        if set(constraints) != set(expected_constraints) or any(
            not _constraint_definition_matches(table_name, name, definition)
            for name, (_constraint_type, definition) in constraints.items()
        ):
            raise ApplyMigrationError("Incompatible pgschemadiff history schema.")


def _constraint_definition_matches(table_name: str, name: str, definition: str) -> bool:
    if name.endswith("_status_check"):
        values = frozenset(re.findall(r"'([^']*)'", definition))
        return (
            bool(re.search(r"\bstatus\b", definition, re.IGNORECASE))
            and values == (_EXPECTED_STATUSES[table_name])
        )

    if name.endswith("_pkey"):
        match = re.fullmatch(r"\s*PRIMARY KEY\s*\(([^)]+)\)\s*", definition, re.IGNORECASE)
        if match is None:
            return False
        columns = tuple(column.strip().strip('"') for column in match.group(1).split(","))
        expected = ("bundle_id",) if table_name == "migration_runs" else ("bundle_id", "unit_index")
        return columns == expected

    match = re.match(
        r"^FOREIGN KEY\s*\(([^)]+)\)\s+REFERENCES\s+([^\s(]+)\s*\(([^)]+)\)",
        definition,
        re.IGNORECASE,
    )
    if match is None:
        return False
    local_columns = tuple(column.strip().strip('"') for column in match.group(1).split(","))
    referenced_table = match.group(2).replace('"', "").lower()
    referenced_columns = tuple(column.strip().strip('"') for column in match.group(3).split(","))
    return (
        table_name == "migration_units"
        and local_columns == ("bundle_id",)
        and referenced_table == "pgschemadiff.migration_runs"
        and referenced_columns == ("bundle_id",)
    )


class _StatementExecutionError(Exception):
    """Internal marker that preserves the failed statement index and cause."""

    def __init__(self, statement_index: int, error: psycopg.Error) -> None:
        super().__init__("Migration statement failed.")
        self.statement_index = statement_index
        self.error = error


class PostgresMigrationExecutor:
    """Execute validated migration units and persist safe history metadata."""

    def __init__(self, connection: psycopg.AsyncConnection[Any]) -> None:
        self._conn = connection

    async def load_history(self, bundle_id: str) -> BundleHistory | None:
        """Read run and unit state without creating history objects."""
        try:
            async with self._conn.transaction():
                schema_exists = await self._history_schema_exists()
                if not schema_exists:
                    return None
                await self._verify_history_layout()
                cursor = await self._conn.execute(
                    f"SELECT status, up_sql_sha256 FROM {_RUN_TABLE} WHERE bundle_id = %s",
                    (bundle_id,),
                )
                run_row = await cursor.fetchone()
                if run_row is None:
                    return None
                units_cursor = await self._conn.execute(
                    f"SELECT unit_index, sql_sha256, transactional, status "
                    f"FROM {_UNIT_TABLE} WHERE bundle_id = %s ORDER BY unit_index",
                    (bundle_id,),
                )
                unit_rows = await units_cursor.fetchall()
                return _map_history_rows(run_row, unit_rows)
        except ApplyMigrationError:
            raise
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not read PostgreSQL migration history.",
            ) from error

    async def start_run(self, bundle: ValidatedBundle, *, resume: bool) -> None:
        """Bootstrap history, then create or resume a run atomically."""
        await self._bootstrap_history()
        try:
            async with self._conn.transaction():
                if resume:
                    cursor = await self._conn.execute(
                        f"UPDATE {_RUN_TABLE} "
                        "SET status = 'running', started_at = pg_catalog.clock_timestamp(), "
                        "    finished_at = NULL, failed_unit_index = NULL, "
                        "    failed_statement_index = NULL, error_class = NULL, sqlstate = NULL "
                        "WHERE bundle_id = %s",
                        (bundle.id,),
                    )
                    self._require_one_row(cursor.rowcount)
                    return

                await self._conn.execute(
                    f"INSERT INTO {_RUN_TABLE} "
                    "(bundle_id, up_sql_sha256, status, started_at) "
                    "VALUES (%s, %s, 'running', pg_catalog.clock_timestamp())",
                    (bundle.id, bundle.up_sql_sha256),
                )
                async with self._conn.cursor() as cursor:
                    await cursor.executemany(
                        f"INSERT INTO {_UNIT_TABLE} "
                        "(bundle_id, unit_index, sql_sha256, transactional, status) "
                        "VALUES (%s, %s, %s, %s, 'pending')",
                        tuple(
                            (bundle.id, unit.index, unit.sql_sha256, unit.transactional)
                            for unit in bundle.units
                        ),
                    )
        except ApplyMigrationError:
            raise
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not start PostgreSQL migration history.",
            ) from error

    async def apply_unit(
        self,
        bundle_id: str,
        unit: BundleUnit,
        on_statement: StatementObserver,
    ) -> UnitFailure | None:
        """Apply one unit with transactional DDL/marker semantics."""
        if unit.transactional:
            return await self._apply_transactional_unit(bundle_id, unit, on_statement)
        return await self._apply_non_transactional_unit(bundle_id, unit, on_statement)

    async def _apply_transactional_unit(
        self,
        bundle_id: str,
        unit: BundleUnit,
        on_statement: StatementObserver,
    ) -> UnitFailure | None:
        attempt_started_at = await self._database_timestamp()
        try:
            async with self._conn.transaction():
                cursor = await self._conn.execute(
                    f"UPDATE {_UNIT_TABLE} "
                    "SET status = 'running', started_at = %s, "
                    "    finished_at = NULL, failed_statement_index = NULL, "
                    "    error_class = NULL, sqlstate = NULL "
                    "WHERE bundle_id = %s AND unit_index = %s",
                    (attempt_started_at, bundle_id, unit.index),
                )
                self._require_one_row(cursor.rowcount)
                for statement_index, statement in enumerate(unit.statements):
                    await self._execute_statement(statement.sql, statement_index, on_statement)
                cursor = await self._conn.execute(
                    f"UPDATE {_UNIT_TABLE} "
                    "SET status = 'applied', finished_at = pg_catalog.clock_timestamp(), "
                    "    failed_statement_index = NULL, error_class = NULL, sqlstate = NULL "
                    "WHERE bundle_id = %s AND unit_index = %s",
                    (bundle_id, unit.index),
                )
                self._require_one_row(cursor.rowcount)
        except _StatementExecutionError as failure:
            unit_failure = _unit_failure(failure.statement_index, failure.error)
            await self._record_unit_failure(
                bundle_id,
                unit.index,
                unit_failure,
                attempt_started_at=attempt_started_at,
            )
            return unit_failure
        except ApplyMigrationError:
            raise
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not update PostgreSQL migration history.",
            ) from error
        return None

    async def _apply_non_transactional_unit(
        self,
        bundle_id: str,
        unit: BundleUnit,
        on_statement: StatementObserver,
    ) -> UnitFailure | None:
        try:
            async with self._conn.transaction():
                cursor = await self._conn.execute(
                    f"UPDATE {_UNIT_TABLE} "
                    "SET status = 'running', started_at = pg_catalog.clock_timestamp(), "
                    "    finished_at = NULL, failed_statement_index = NULL, "
                    "    error_class = NULL, sqlstate = NULL "
                    "WHERE bundle_id = %s AND unit_index = %s",
                    (bundle_id, unit.index),
                )
                self._require_one_row(cursor.rowcount)
        except ApplyMigrationError:
            raise
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not update PostgreSQL migration history.",
            ) from error

        statement = unit.statements[0]
        try:
            await self._execute_statement(statement.sql, 0, on_statement)
        except _StatementExecutionError as failure:
            unit_failure = _unit_failure(failure.statement_index, failure.error)
            await self._record_unit_failure(bundle_id, unit.index, unit_failure)
            return unit_failure

        try:
            async with self._conn.transaction():
                cursor = await self._conn.execute(
                    f"UPDATE {_UNIT_TABLE} "
                    "SET status = 'applied', finished_at = pg_catalog.clock_timestamp(), "
                    "    failed_statement_index = NULL, error_class = NULL, sqlstate = NULL "
                    "WHERE bundle_id = %s AND unit_index = %s",
                    (bundle_id, unit.index),
                )
                self._require_one_row(cursor.rowcount)
        except ApplyMigrationError:
            raise
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not update PostgreSQL migration history.",
            ) from error
        return None

    async def _execute_statement(
        self,
        sql: str,
        statement_index: int,
        on_statement: StatementObserver,
    ) -> None:
        on_statement(statement_index, True)
        try:
            await self._conn.execute(sql)
        except psycopg.Error as error:
            raise _StatementExecutionError(statement_index, error) from error
        on_statement(statement_index, False)

    async def _record_unit_failure(
        self,
        bundle_id: str,
        unit_index: int,
        failure: UnitFailure,
        *,
        attempt_started_at: datetime | None = None,
    ) -> None:
        try:
            async with self._conn.transaction():
                cursor = await self._conn.execute(
                    f"UPDATE {_UNIT_TABLE} "
                    "SET status = 'failed', "
                    "    started_at = COALESCE(%s, started_at, pg_catalog.clock_timestamp()), "
                    "    finished_at = pg_catalog.clock_timestamp(), "
                    "    failed_statement_index = %s, error_class = %s, sqlstate = %s "
                    "WHERE bundle_id = %s AND unit_index = %s",
                    (
                        attempt_started_at,
                        failure.statement_index,
                        failure.error_class,
                        failure.sqlstate,
                        bundle_id,
                        unit_index,
                    ),
                )
                self._require_one_row(cursor.rowcount)
        except ApplyMigrationError:
            raise
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not record PostgreSQL migration unit failure.",
            ) from error

    async def finish_run(
        self,
        bundle_id: str,
        status: RunFinishStatus,
        failure: RunFailure | None,
    ) -> None:
        """Persist final status and optional safe failure metadata."""
        try:
            async with self._conn.transaction():
                cursor = await self._conn.execute(
                    f"UPDATE {_RUN_TABLE} "
                    "SET status = %s, finished_at = pg_catalog.clock_timestamp(), "
                    "    failed_unit_index = %s, failed_statement_index = %s, "
                    "    error_class = %s, sqlstate = %s "
                    "WHERE bundle_id = %s",
                    (
                        status,
                        failure.unit_index if failure is not None else None,
                        failure.statement_index if failure is not None else None,
                        failure.error_class if failure is not None else None,
                        failure.sqlstate if failure is not None else None,
                        bundle_id,
                    ),
                )
                self._require_one_row(cursor.rowcount)
        except ApplyMigrationError:
            raise
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not finish PostgreSQL migration history.",
            ) from error

    async def _bootstrap_history(self) -> None:
        try:
            async with self._conn.transaction():
                schema_exists = await self._history_schema_exists()
                if schema_exists:
                    await self._verify_history_layout()
                await self._conn.execute("CREATE SCHEMA IF NOT EXISTS pgschemadiff")
                await self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {_RUN_TABLE} ("
                    "bundle_id text NOT NULL, "
                    "up_sql_sha256 text NOT NULL, "
                    "status text NOT NULL, "
                    "started_at timestamp with time zone NOT NULL, "
                    "finished_at timestamp with time zone, "
                    "failed_unit_index integer, "
                    "failed_statement_index integer, "
                    "error_class text, "
                    "sqlstate text, "
                    "CONSTRAINT migration_runs_pkey PRIMARY KEY (bundle_id), "
                    "CONSTRAINT migration_runs_status_check CHECK "
                    "(status IN ('running', 'applied', 'failed', 'cancelled')))"
                )
                await self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {_UNIT_TABLE} ("
                    "bundle_id text NOT NULL, "
                    "unit_index integer NOT NULL, "
                    "sql_sha256 text NOT NULL, "
                    "transactional boolean NOT NULL, "
                    "status text NOT NULL, "
                    "started_at timestamp with time zone, "
                    "finished_at timestamp with time zone, "
                    "failed_statement_index integer, "
                    "error_class text, "
                    "sqlstate text, "
                    "CONSTRAINT migration_units_pkey PRIMARY KEY (bundle_id, unit_index), "
                    "CONSTRAINT migration_units_status_check CHECK "
                    "(status IN ('pending', 'running', 'applied', 'failed')), "
                    f"CONSTRAINT migration_units_bundle_id_fkey FOREIGN KEY (bundle_id) "
                    f"REFERENCES {_RUN_TABLE} (bundle_id))"
                )
                await self._verify_history_layout()
        except ApplyMigrationError:
            raise
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not initialize PostgreSQL migration history.",
            ) from error

    async def _history_schema_exists(self) -> bool:
        cursor = await self._conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s)",
            (_HISTORY_SCHEMA,),
        )
        row = await cursor.fetchone()
        return row is not None and row[0] is True

    async def _database_timestamp(self) -> datetime:
        try:
            cursor = await self._conn.execute("SELECT pg_catalog.clock_timestamp()")
            row = await cursor.fetchone()
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not read PostgreSQL migration timestamp.",
            ) from error
        if row is None or not isinstance(row[0], datetime):
            raise ApplyMigrationError("Could not read PostgreSQL migration timestamp.")
        return row[0]

    async def _verify_history_layout(self) -> None:
        cursor = await self._conn.execute(
            "SELECT c.relname, c.relkind::text, a.attname, "
            "       pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull "
            "FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_catalog.pg_attribute AS a "
            "  ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
            "WHERE n.nspname = %s AND c.relkind NOT IN ('i', 'I', 't') "
            "ORDER BY c.relname, a.attnum",
            (_HISTORY_SCHEMA,),
        )
        column_rows = await cursor.fetchall()
        constraints_cursor = await self._conn.execute(
            "SELECT c.relname, con.conname, con.contype::text, "
            "       pg_catalog.pg_get_constraintdef(con.oid, true) "
            "FROM pg_catalog.pg_constraint AS con "
            "JOIN pg_catalog.pg_class AS c ON c.oid = con.conrelid "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            # PG18 records NOT NULL as contype 'n'; attnotnull already covers it.
            "WHERE n.nspname = %s AND con.contype <> 'n' "
            "ORDER BY c.relname, con.conname",
            (_HISTORY_SCHEMA,),
        )
        constraint_rows = await constraints_cursor.fetchall()
        _check_history_layout(True, column_rows, constraint_rows)

    @staticmethod
    def _require_one_row(rowcount: int) -> None:
        if rowcount != 1:
            raise ApplyMigrationError("Migration history changed unexpectedly.")


def _unit_failure(statement_index: int, error: psycopg.Error) -> UnitFailure:
    return UnitFailure(
        statement_index=statement_index,
        error_class=type(error).__name__,
        sqlstate=error.sqlstate,
    )


@asynccontextmanager
async def open_executor(
    conninfo: str,
    *,
    lock_timeout_ms: int = 5_000,
    statement_timeout_ms: int = 0,
) -> AsyncIterator[PostgresMigrationExecutor]:
    """Open one configured connection and hold the database migration lock."""
    lock_timeout_ms = _validate_timeout_ms(lock_timeout_ms, name="lock_timeout_ms")
    statement_timeout_ms = _validate_timeout_ms(
        statement_timeout_ms,
        name="statement_timeout_ms",
    )

    # Connection failures propagate as psycopg.Error so callers can report them
    # as connectivity problems (CLI exit 1), distinct from apply failures.
    connection = await psycopg.AsyncConnection.connect(conninfo, autocommit=True)

    locked = False
    active_error: BaseException | None = None
    try:
        try:
            await connection.execute(
                "SELECT set_config('standard_conforming_strings', %s, false), "
                "set_config('lock_timeout', %s, false), "
                "set_config('statement_timeout', %s, false), "
                "set_config('application_name', %s, false), "
                "set_config('search_path', %s, false)",
                (
                    "on",
                    f"{lock_timeout_ms}ms",
                    f"{statement_timeout_ms}ms",
                    "pgschemadiff apply",
                    "pg_catalog",
                ),
            )
            try:
                await connection.execute(
                    "SELECT pg_catalog.pg_advisory_lock(%s, %s)",
                    (_ADVISORY_LOCK_KEY_1, _ADVISORY_LOCK_KEY_2),
                )
            except psycopg.Error as error:
                raise _safe_database_error(
                    error,
                    message="Could not acquire the PostgreSQL migration lock.",
                    lock_contention=True,
                ) from error
            locked = True
        except psycopg.Error as error:
            raise _safe_database_error(
                error,
                message="Could not configure the PostgreSQL migration session.",
            ) from error

        yield PostgresMigrationExecutor(connection)
    except BaseException as error:
        active_error = error
        raise
    finally:
        try:
            if locked:
                try:
                    await connection.execute(
                        "SELECT pg_catalog.pg_advisory_unlock(%s, %s)",
                        (_ADVISORY_LOCK_KEY_1, _ADVISORY_LOCK_KEY_2),
                    )
                except psycopg.Error as error:
                    mapped = _safe_database_error(
                        error,
                        message="Could not release the PostgreSQL migration lock.",
                    )
                    if active_error is None:
                        raise mapped from error
                    active_error.add_note("Migration lock cleanup failed; details omitted.")
        finally:
            try:
                await connection.close()
            except psycopg.Error as error:
                mapped = _safe_database_error(
                    error,
                    message="Could not close the PostgreSQL migration connection.",
                )
                if active_error is None:
                    raise mapped from error
                active_error.add_note("Connection cleanup failed; details omitted.")
