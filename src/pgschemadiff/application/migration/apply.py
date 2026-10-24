"""Orchestrate safe, resumable application of a validated migration bundle."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pgschemadiff.application.migration.ports import RunFailure
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.shared.errors import ApplyMigrationError, RiskGateError

if TYPE_CHECKING:
    from collections.abc import Callable

    from pgschemadiff.application.migration.bundle import BundleUnit, ValidatedBundle
    from pgschemadiff.application.migration.ports import (
        BundleHistory,
        MigrationExecutor,
        UnitFailure,
    )


@dataclass(frozen=True)
class ApplyResult:
    """Safe summary of a successful, no-op, or failed apply attempt."""

    bundle_id: str
    status: Literal["applied", "failed", "noop"]
    unit_count: int
    applied_unit_count: int
    resumed: bool
    elapsed: float
    failed_unit_index: int | None = None
    failed_statement_index: int | None = None
    delta_id: str | None = None
    line_range: tuple[int, int] | None = None
    error_class: str | None = None
    sqlstate: str | None = None
    manual_inspection_required: bool = False


@dataclass(frozen=True)
class RunStarted:
    bundle_id: str
    unit_count: int
    resumed: bool
    elapsed: float


@dataclass(frozen=True)
class UnitStarted:
    unit_index: int
    unit_count: int
    statement_count: int
    delta_ids: tuple[str, ...]
    line_range: tuple[int, int]
    elapsed: float


@dataclass(frozen=True)
class StatementStarted:
    unit_index: int
    statement_index: int
    unit_count: int
    statement_count: int
    delta_id: str
    line_range: tuple[int, int]
    elapsed: float


@dataclass(frozen=True)
class StatementFinished:
    unit_index: int
    statement_index: int
    unit_count: int
    statement_count: int
    delta_id: str
    line_range: tuple[int, int]
    elapsed: float


@dataclass(frozen=True)
class UnitFinished:
    unit_index: int
    unit_count: int
    statement_count: int
    delta_ids: tuple[str, ...]
    line_range: tuple[int, int]
    elapsed: float


@dataclass(frozen=True)
class UnitFailed:
    unit_index: int
    unit_count: int
    statement_index: int
    statement_count: int
    delta_id: str
    line_range: tuple[int, int]
    error_class: str
    sqlstate: str | None
    manual_inspection_required: bool
    elapsed: float


@dataclass(frozen=True)
class RunFinished:
    bundle_id: str
    status: Literal["applied", "failed"]
    unit_count: int
    applied_unit_count: int
    elapsed: float


@dataclass(frozen=True)
class RunCancelled:
    bundle_id: str
    unit_count: int
    current_unit_index: int | None
    current_statement_index: int | None
    elapsed: float


ApplyEvent = (
    RunStarted
    | UnitStarted
    | StatementStarted
    | StatementFinished
    | UnitFinished
    | UnitFailed
    | RunFinished
    | RunCancelled
)

_RISK_RANK = {level: index for index, level in enumerate(RiskLevel)}
_RUN_STATUSES = frozenset({"running", "applied", "failed", "cancelled"})
_UNIT_STATUSES = frozenset({"pending", "running", "applied", "failed"})


def _risk_gate(bundle: ValidatedBundle, *, approve_destructive: bool) -> None:
    if any(unit.max_risk is RiskLevel.BLOCKED for unit in bundle.units):
        raise RiskGateError("Migration bundle contains a BLOCKED unit and cannot be applied.")
    if not approve_destructive and any(
        _RISK_RANK[unit.max_risk] >= _RISK_RANK[RiskLevel.DESTRUCTIVE] for unit in bundle.units
    ):
        raise RiskGateError(
            "Migration bundle contains a destructive unit; explicit approval is required."
        )


def _validate_history_layout(bundle: ValidatedBundle, history: BundleHistory) -> None:
    if history.up_sql_sha256 != bundle.up_sql_sha256 or len(history.units) != len(bundle.units):
        raise ApplyMigrationError("Migration history does not match this bundle.")

    for index, (record, unit) in enumerate(zip(history.units, bundle.units, strict=True)):
        layout_matches = (
            record.index == index
            and record.index == unit.index
            and record.sql_sha256 == unit.sql_sha256
            and record.transactional == unit.transactional
        )
        if not layout_matches:
            raise ApplyMigrationError("Migration history does not match this bundle.")
        if record.status not in _UNIT_STATUSES:
            raise ApplyMigrationError("Migration history is corrupt.")


def _first_non_applied(history: BundleHistory) -> int:
    first_non_applied: int | None = None
    for index, record in enumerate(history.units):
        if record.status == "applied":
            if first_non_applied is not None:
                raise ApplyMigrationError(
                    "Migration history is corrupt: applied units are not a prefix."
                )
        elif first_non_applied is None:
            first_non_applied = index
    if first_non_applied is None:
        raise ApplyMigrationError("Migration bundle has already been applied.")
    return first_non_applied


def _resume_index(bundle: ValidatedBundle, history: BundleHistory | None) -> int:
    if history is None:
        return 0
    if history.status not in _RUN_STATUSES:
        raise ApplyMigrationError("Migration history is corrupt.")
    if history.status == "applied":
        raise ApplyMigrationError("Migration bundle has already been applied.")
    _validate_history_layout(bundle, history)
    first_non_applied = _first_non_applied(history)

    for unit, record in zip(bundle.units, history.units, strict=True):
        if not unit.transactional and record.status == "running":
            raise ApplyMigrationError(
                "A non-transactional unit is still running; manual inspection is required."
            )
    return first_non_applied


def _unit_range(unit: BundleUnit) -> tuple[int, int]:
    return unit.start_line, unit.end_line


def _statement_observer(
    unit: BundleUnit,
    unit_count: int,
    emit: Callable[[ApplyEvent], None],
    elapsed: Callable[[], float],
    set_current_statement: Callable[[int | None], None],
) -> Callable[[int, bool], None]:
    def observe(statement_index: int, started: bool) -> None:
        statement = unit.statements[statement_index]
        event_type = StatementStarted if started else StatementFinished
        if started:
            set_current_statement(statement_index)
        emit(
            event_type(
                unit_index=unit.index,
                statement_index=statement_index,
                unit_count=unit_count,
                statement_count=len(unit.statements),
                delta_id=statement.delta_id,
                line_range=(statement.start_line, statement.end_line),
                elapsed=elapsed(),
            )
        )
        if not started:
            set_current_statement(None)

    return observe


async def apply_migration(
    bundle: ValidatedBundle,
    executor: MigrationExecutor,
    *,
    approve_destructive: bool,
    on_event: Callable[[ApplyEvent], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ApplyResult:
    """Apply bundle units in order, resuming only from safe history states."""
    _risk_gate(bundle, approve_destructive=approve_destructive)
    if not bundle.units:
        return ApplyResult(
            bundle_id=bundle.id,
            status="noop",
            unit_count=0,
            applied_unit_count=0,
            resumed=False,
            elapsed=0.0,
        )

    started_at = clock()

    def elapsed() -> float:
        return max(0.0, clock() - started_at)

    def emit(event: ApplyEvent) -> None:
        if on_event is not None:
            on_event(event)

    current_unit_index: int | None = None
    current_statement_index: int | None = None

    def set_current_statement(statement_index: int | None) -> None:
        nonlocal current_statement_index
        current_statement_index = statement_index

    applied_unit_count = 0
    resumed = False

    try:
        history = await executor.load_history(bundle.id)
        resume_index = _resume_index(bundle, history)
        resumed = history is not None
        applied_unit_count = resume_index
        await executor.start_run(bundle, resume=resumed)
        emit(RunStarted(bundle.id, len(bundle.units), resumed, elapsed()))

        for unit in bundle.units[resume_index:]:
            current_unit_index = unit.index
            emit(
                UnitStarted(
                    unit_index=unit.index,
                    unit_count=len(bundle.units),
                    statement_count=len(unit.statements),
                    delta_ids=unit.delta_ids,
                    line_range=_unit_range(unit),
                    elapsed=elapsed(),
                )
            )

            on_statement = _statement_observer(
                unit,
                len(bundle.units),
                emit,
                elapsed,
                set_current_statement,
            )
            failure = await executor.apply_unit(bundle.id, unit, on_statement)
            if failure is not None:
                failed_unit_result = _failure_result(
                    bundle=bundle,
                    unit=unit,
                    failure=failure,
                    applied_unit_count=applied_unit_count,
                    resumed=resumed,
                    elapsed=elapsed(),
                )
                statement = unit.statements[failure.statement_index]
                run_failure = _run_failure(unit.index, failure)
                emit(
                    UnitFailed(
                        unit_index=unit.index,
                        unit_count=len(bundle.units),
                        statement_index=failure.statement_index,
                        statement_count=len(unit.statements),
                        delta_id=statement.delta_id,
                        line_range=(statement.start_line, statement.end_line),
                        error_class=failure.error_class,
                        sqlstate=failure.sqlstate,
                        manual_inspection_required=not unit.transactional,
                        elapsed=elapsed(),
                    )
                )
                await executor.finish_run(bundle.id, "failed", run_failure)
                emit(
                    RunFinished(
                        bundle_id=bundle.id,
                        status="failed",
                        unit_count=len(bundle.units),
                        applied_unit_count=applied_unit_count,
                        elapsed=elapsed(),
                    )
                )
                raise ApplyMigrationError(
                    "Migration unit failed; inspect safe failure metadata.",
                    result=failed_unit_result,
                )

            applied_unit_count += 1
            emit(
                UnitFinished(
                    unit_index=unit.index,
                    unit_count=len(bundle.units),
                    statement_count=len(unit.statements),
                    delta_ids=unit.delta_ids,
                    line_range=_unit_range(unit),
                    elapsed=elapsed(),
                )
            )
            current_unit_index = None

        await executor.finish_run(bundle.id, "applied", None)
        emit(
            RunFinished(
                bundle_id=bundle.id,
                status="applied",
                unit_count=len(bundle.units),
                applied_unit_count=applied_unit_count,
                elapsed=elapsed(),
            )
        )
        return ApplyResult(
            bundle_id=bundle.id,
            status="applied",
            unit_count=len(bundle.units),
            applied_unit_count=applied_unit_count,
            resumed=resumed,
            elapsed=elapsed(),
        )
    except asyncio.CancelledError:
        emit(
            RunCancelled(
                bundle_id=bundle.id,
                unit_count=len(bundle.units),
                current_unit_index=current_unit_index,
                current_statement_index=current_statement_index,
                elapsed=elapsed(),
            )
        )
        with suppress(Exception):
            await executor.finish_run(bundle.id, "cancelled", None)
        raise


def _failure_result(
    *,
    bundle: ValidatedBundle,
    unit: BundleUnit,
    failure: UnitFailure,
    applied_unit_count: int,
    resumed: bool,
    elapsed: float,
) -> ApplyResult:
    statement = unit.statements[failure.statement_index]
    return ApplyResult(
        bundle_id=bundle.id,
        status="failed",
        unit_count=len(bundle.units),
        applied_unit_count=applied_unit_count,
        resumed=resumed,
        elapsed=elapsed,
        failed_unit_index=unit.index,
        failed_statement_index=failure.statement_index,
        delta_id=statement.delta_id,
        line_range=(statement.start_line, statement.end_line),
        error_class=failure.error_class,
        sqlstate=failure.sqlstate,
        manual_inspection_required=not unit.transactional,
    )


def _run_failure(unit_index: int, failure: UnitFailure) -> RunFailure:
    return RunFailure(
        unit_index=unit_index,
        statement_index=failure.statement_index,
        error_class=failure.error_class,
        sqlstate=failure.sqlstate,
    )
