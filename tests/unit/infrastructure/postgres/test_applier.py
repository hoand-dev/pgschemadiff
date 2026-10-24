"""Pure helper tests for the PostgreSQL migration executor."""

from __future__ import annotations

import psycopg
import pytest

from pgschemadiff.application.migration.ports import BundleHistory, UnitHistory
from pgschemadiff.infrastructure.postgres.applier import (
    _MAX_TIMEOUT_MS,
    _check_history_layout,
    _map_history_rows,
    _safe_database_error,
    _unit_failure,
    _validate_timeout_ms,
    open_executor,
)
from pgschemadiff.shared.errors import ApplyMigrationError


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [pytest.param(0), pytest.param(5_000), pytest.param(_MAX_TIMEOUT_MS)],
)
def test_timeout_validation_accepts_non_negative_bounded_integers(value: int) -> None:
    assert _validate_timeout_ms(value, name="lock_timeout_ms") == value


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(-1),
        pytest.param(_MAX_TIMEOUT_MS + 1),
        pytest.param(True),
        pytest.param(1.5),
        pytest.param("5000"),
    ],
)
def test_timeout_validation_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError, match="lock_timeout_ms"):
        _validate_timeout_ms(value, name="lock_timeout_ms")


@pytest.mark.unit
def test_safe_database_error_omits_driver_message() -> None:
    error = psycopg.OperationalError("postgresql://user:password@host/db driver-private")

    mapped = _safe_database_error(error, message="Could not read migration history.")

    assert str(mapped) == "Could not read migration history."
    assert "password" not in str(mapped)
    assert "driver-private" not in str(mapped)


@pytest.mark.unit
def test_lock_contention_maps_to_fixed_safe_message() -> None:
    error = psycopg.errors.LockNotAvailable("lock-private-driver-detail")

    mapped = _safe_database_error(
        error,
        message="Could not acquire migration lock.",
        lock_contention=True,
    )

    assert str(mapped) == "Another pgschemadiff apply holds the migration lock."
    assert "lock-private-driver-detail" not in str(mapped)


@pytest.mark.unit
def test_sql_error_mapping_keeps_only_class_and_sqlstate() -> None:
    error = psycopg.errors.UndefinedTable("private SQL and relation detail")

    failure = _unit_failure(3, error)

    assert failure.statement_index == 3
    assert failure.error_class == "UndefinedTable"
    assert failure.sqlstate == "42P01"
    assert "private" not in repr(failure)


@pytest.mark.unit
def test_history_rows_map_to_immutable_port_models() -> None:
    history = _map_history_rows(
        ("running", "a" * 64),
        (
            (0, "b" * 64, True, "applied"),
            (1, "c" * 64, False, "pending"),
        ),
    )

    assert history == BundleHistory(
        status="running",
        up_sql_sha256="a" * 64,
        units=(
            UnitHistory(index=0, sql_sha256="b" * 64, transactional=True, status="applied"),
            UnitHistory(index=1, sql_sha256="c" * 64, transactional=False, status="pending"),
        ),
    )


@pytest.mark.unit
def test_history_row_mapping_rejects_unknown_status_without_driver_data() -> None:
    with pytest.raises(ApplyMigrationError, match="history") as exc_info:
        _map_history_rows(("surprise", "a" * 64), ())

    assert "surprise" not in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    "unit_row",
    [
        pytest.param((0, "bad-checksum", True, "pending")),
        pytest.param((-1, "b" * 64, True, "pending")),
        pytest.param((0, "b" * 64, 1, "pending")),
        pytest.param((0, "b" * 64, True, "unknown")),
    ],
)
def test_history_row_mapping_rejects_corrupt_unit_rows(
    unit_row: tuple[object, ...],
) -> None:
    with pytest.raises(ApplyMigrationError, match="history"):
        _map_history_rows(("running", "a" * 64), (unit_row,))


def _layout_rows() -> tuple[tuple[str, str, str | None, str | None, bool | None], ...]:
    columns: dict[str, dict[str, tuple[str, bool]]] = {
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
    return tuple(
        (table, "r", column, data_type, not_null)
        for table, table_columns in columns.items()
        for column, (data_type, not_null) in table_columns.items()
    )


def _constraint_rows() -> tuple[tuple[str, str, str, str], ...]:
    return (
        ("migration_runs", "migration_runs_pkey", "p", "PRIMARY KEY (bundle_id)"),
        (
            "migration_runs",
            "migration_runs_status_check",
            "c",
            "CHECK (status IN ('running', 'applied', 'failed', 'cancelled'))",
        ),
        (
            "migration_units",
            "migration_units_pkey",
            "p",
            "PRIMARY KEY (bundle_id, unit_index)",
        ),
        (
            "migration_units",
            "migration_units_status_check",
            "c",
            "CHECK (status IN ('pending', 'running', 'applied', 'failed'))",
        ),
        (
            "migration_units",
            "migration_units_bundle_id_fkey",
            "f",
            "FOREIGN KEY (bundle_id) REFERENCES pgschemadiff.migration_runs(bundle_id)",
        ),
    )


def _change_column(
    rows: tuple[tuple[str, str, str | None, str | None, bool | None], ...],
    table_name: str,
    column_name: str,
    *,
    relation_kind: str | None = None,
    data_type: str | None = None,
    not_null: bool | None = None,
) -> tuple[tuple[str, str, str | None, str | None, bool | None], ...]:
    changed: list[tuple[str, str, str | None, str | None, bool | None]] = []
    for table, kind, column, column_type, column_not_null in rows:
        if table == table_name and column == column_name:
            changed.append(
                (
                    table,
                    relation_kind or kind,
                    column,
                    data_type or column_type,
                    not_null if not_null is not None else column_not_null,
                )
            )
        else:
            changed.append((table, kind, column, column_type, column_not_null))
    return tuple(changed)


def _change_constraint(
    rows: tuple[tuple[str, str, str, str], ...],
    constraint_name: str,
    *,
    constraint_type: str | None = None,
    definition: str | None = None,
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            table,
            name,
            constraint_type or kind if name == constraint_name else kind,
            definition or constraint if name == constraint_name else constraint,
        )
        for table, name, kind, constraint in rows
    )


@pytest.mark.unit
def test_history_layout_accepts_expected_tables_and_columns() -> None:
    _check_history_layout(True, _layout_rows(), _constraint_rows())


@pytest.mark.unit
def test_history_layout_allows_absent_schema_before_bootstrap() -> None:
    _check_history_layout(False, (), ())


@pytest.mark.unit
@pytest.mark.parametrize(
    "column_rows",
    [
        pytest.param(_layout_rows()[:-1]),
        pytest.param((*_layout_rows(), ("unexpected", "r", None, None, None))),
        pytest.param((*_layout_rows(), ("migration_runs", "r", "unexpected", "text", True))),
        pytest.param(tuple(row for row in _layout_rows() if row[0] != "migration_runs")),
        pytest.param(_change_column(_layout_rows(), "migration_runs", "status", relation_kind="v")),
        pytest.param(
            _change_column(
                _layout_rows(),
                "migration_runs",
                "status",
                data_type="character varying",
            )
        ),
        pytest.param(
            _change_column(
                _layout_rows(),
                "migration_runs",
                "bundle_id",
                not_null=False,
            )
        ),
    ],
)
def test_history_layout_fails_closed_on_other_layout(
    column_rows: tuple[tuple[str, str, str | None, str | None, bool | None], ...],
) -> None:
    with pytest.raises(ApplyMigrationError, match="history schema"):
        _check_history_layout(True, column_rows, _constraint_rows())


@pytest.mark.unit
@pytest.mark.parametrize(
    "constraint_rows",
    [
        pytest.param(_constraint_rows()[:-1]),
        pytest.param((*_constraint_rows(), ("migration_runs", "unexpected", "c", "CHECK (true)"))),
        pytest.param(
            _change_constraint(_constraint_rows(), "migration_runs_pkey", constraint_type="c")
        ),
        pytest.param(
            _change_constraint(
                _constraint_rows(),
                "migration_runs_status_check",
                definition="CHECK (status = 'running')",
            )
        ),
        pytest.param(
            _change_constraint(
                _constraint_rows(),
                "migration_runs_pkey",
                definition="PRIMARY KEY (unexpected)",
            )
        ),
        pytest.param(
            _change_constraint(
                _constraint_rows(),
                "migration_units_bundle_id_fkey",
                definition="FOREIGN KEY (bundle_id) REFERENCES public.other(bundle_id)",
            )
        ),
    ],
)
def test_history_layout_fails_closed_on_other_constraints(
    constraint_rows: tuple[tuple[str, str, str, str], ...],
) -> None:
    with pytest.raises(ApplyMigrationError, match="history schema"):
        _check_history_layout(True, _layout_rows(), constraint_rows)


@pytest.mark.unit
async def test_open_executor_validates_timeouts_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected = False

    async def connect(*_args: object, **_kwargs: object) -> None:
        nonlocal connected
        connected = True

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)

    with pytest.raises(ValueError, match="lock_timeout_ms"):
        async with open_executor("not-a-dsn", lock_timeout_ms=-1):
            pass

    assert not connected
