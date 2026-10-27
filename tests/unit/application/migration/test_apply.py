import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from pgschemadiff.application.migration.apply import (
    ApplyEvent,
    ApplyResult,
    RunCancelled,
    RunFinished,
    RunStarted,
    StatementFinished,
    StatementStarted,
    UnitFailed,
    UnitFinished,
    UnitStarted,
    apply_migration,
)
from pgschemadiff.application.migration.bundle import BundleUnit, ValidatedBundle, load_bundle
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.ports import (
    BundleHistory,
    MigrationExecutor,
    RunFailure,
    RunFinishStatus,
    RunStatus,
    StatementObserver,
    UnitFailure,
    UnitHistory,
    UnitStatus,
)
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta import CreateIndex, CreateSchema, CreateTable, DeltaBase, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.shared.errors import ApplyMigrationError, RiskGateError

_FINGERPRINT = "sha256:" + "0" * 64


def _bundle() -> ValidatedBundle:
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="app"),
    )
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="app", name="accounts"),
    )
    index_ref = ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace="app", name="accounts_id_idx"),
    )
    table = Table(
        ref=table_ref,
        columns=(Column(name="id", position=1, data_type="integer", nullable=False),),
    )
    index = Index(
        ref=index_ref,
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(IndexKeyColumn(column_name="id"),),
        definition='CREATE INDEX "accounts_id_idx" ON "app"."accounts" USING btree ("id")',
    )
    deltas: tuple[DeltaBase, ...] = (
        CreateSchema(target=schema_ref, pg_schema=Schema(ref=schema_ref)),
        CreateTable(target=table_ref, table=table),
        CreateIndex(target=index_ref, index=index),
    )
    plan = generate_migration(
        DeltaSet.from_iterable(deltas),
        source_fingerprint=_FINGERPRINT,
        target_fingerprint=_FINGERPRINT,
        clock=lambda: datetime(2026, 10, 24, 12, 30, 45, tzinfo=UTC),
        id_factory=lambda: "apply-test-bundle",
    )
    files = dict(render_bundle(plan).files)
    return load_bundle(files["manifest.json"], files["up.sql"])


def _history(
    bundle: ValidatedBundle,
    statuses: tuple[UnitStatus, ...],
    *,
    run_status: RunStatus = "failed",
) -> BundleHistory:
    return BundleHistory(
        status=run_status,
        up_sql_sha256=bundle.up_sql_sha256,
        units=tuple(
            UnitHistory(
                index=unit.index,
                sql_sha256=unit.sql_sha256,
                transactional=unit.transactional,
                status=status,
            )
            for unit, status in zip(bundle.units, statuses, strict=True)
        ),
    )


class FakeExecutor:
    def __init__(
        self,
        history: BundleHistory | None = None,
        *,
        failures: dict[tuple[int, int], UnitFailure] | None = None,
        cancel_on_unit: int | None = None,
        fail_cancel_finish: bool = False,
    ) -> None:
        self.history = history
        self.failures = failures or {}
        self.cancel_on_unit = cancel_on_unit
        self.fail_cancel_finish = fail_cancel_finish
        self.calls: list[tuple[object, ...]] = []

    async def load_history(self, bundle_id: str) -> BundleHistory | None:
        self.calls.append(("load_history", bundle_id))
        return self.history

    async def start_run(self, bundle: ValidatedBundle, *, resume: bool) -> None:
        self.calls.append(("start_run", resume))
        if not resume:
            pending = cast("tuple[UnitStatus, ...]", ("pending",) * len(bundle.units))
            self.history = _history(bundle, pending, run_status="running")
        elif self.history is not None:
            self.history = replace(self.history, status="running")

    async def apply_unit(
        self,
        bundle_id: str,
        unit: BundleUnit,
        on_statement: StatementObserver,
    ) -> UnitFailure | None:
        self.calls.append(("apply_unit", bundle_id, unit.index))
        for statement_index, _statement in enumerate(unit.statements):
            on_statement(statement_index, True)
            if self.cancel_on_unit == unit.index:
                self._set_unit_status(unit.index, "running")
                raise asyncio.CancelledError
            failure = self.failures.get((unit.index, statement_index))
            if failure is not None:
                self._set_unit_status(unit.index, "failed")
                return failure
            on_statement(statement_index, False)
        self._set_unit_status(unit.index, "applied")
        return None

    async def finish_run(
        self,
        bundle_id: str,
        status: RunFinishStatus,
        failure: RunFailure | None,
    ) -> None:
        self.calls.append(("finish_run", bundle_id, status, failure))
        if self.fail_cancel_finish and status == "cancelled":
            raise RuntimeError("private finish failure")
        if self.history is not None:
            self.history = replace(self.history, status=status)

    def _set_unit_status(self, index: int, status: UnitStatus) -> None:
        assert self.history is not None
        units = list(self.history.units)
        units[index] = replace(units[index], status=status)
        self.history = replace(self.history, units=tuple(units))


async def _apply(
    bundle: ValidatedBundle,
    executor: FakeExecutor,
    *,
    approve_destructive: bool,
    on_event: Callable[[ApplyEvent], None] | None = None,
) -> ApplyResult:
    return await apply_migration(
        bundle,
        executor,
        approve_destructive=approve_destructive,
        on_event=on_event,
    )


def test_executor_port_is_runtime_checkable() -> None:
    assert isinstance(FakeExecutor(), MigrationExecutor)


async def test_apply_runs_units_in_order_and_emits_ordered_events() -> None:
    bundle = _bundle()
    executor = FakeExecutor()
    events: list[object] = []

    result = await _apply(bundle, executor, approve_destructive=False, on_event=events.append)

    assert result.status == "applied"
    assert result.applied_unit_count == len(bundle.units)
    assert result.resumed is False
    assert ("start_run", False) in executor.calls
    assert [call[2] for call in executor.calls if call[0] == "apply_unit"] == [0, 1]
    expected: list[type[object]] = [RunStarted]
    for unit in bundle.units:
        expected.append(UnitStarted)
        for _statement in unit.statements:
            expected.extend((StatementStarted, StatementFinished))
        expected.append(UnitFinished)
    expected.append(RunFinished)
    assert [type(event) for event in events] == expected
    assert all(not hasattr(event, "sql") for event in events)
    assert "CREATE" not in repr(events)
    assert "postgresql://" not in repr(events)


@pytest.mark.parametrize("approved", [False, True])
async def test_blocked_units_always_fail_risk_gate_without_executor_calls(approved: bool) -> None:
    bundle = _bundle()
    units = (replace(bundle.units[0], max_risk=RiskLevel.BLOCKED), *bundle.units[1:])
    blocked_bundle = replace(bundle, units=units)
    executor = FakeExecutor()

    with pytest.raises(RiskGateError):
        await _apply(blocked_bundle, executor, approve_destructive=approved)

    assert executor.calls == []


async def test_unapproved_destructive_unit_fails_before_executor_call() -> None:
    bundle = _bundle()
    units = (replace(bundle.units[0], max_risk=RiskLevel.DESTRUCTIVE), *bundle.units[1:])
    executor = FakeExecutor()

    with pytest.raises(RiskGateError):
        await _apply(replace(bundle, units=units), executor, approve_destructive=False)

    assert executor.calls == []


async def test_approved_destructive_unit_runs() -> None:
    bundle = _bundle()
    units = (replace(bundle.units[0], max_risk=RiskLevel.DESTRUCTIVE), *bundle.units[1:])
    executor = FakeExecutor()

    result = await _apply(replace(bundle, units=units), executor, approve_destructive=True)

    assert result.status == "applied"
    assert any(call[0] == "apply_unit" for call in executor.calls)


async def test_unit_failure_stops_at_exact_statement_and_carries_safe_result() -> None:
    bundle = _bundle()
    target = bundle.units[0].statements[1]
    executor = FakeExecutor(
        failures={(0, 1): UnitFailure(1, "SyntaxError", "42601")},
    )
    events: list[object] = []

    with pytest.raises(ApplyMigrationError) as raised:
        await _apply(bundle, executor, approve_destructive=False, on_event=events.append)

    result = cast("ApplyResult", raised.value.result)
    assert result.status == "failed"
    assert result.failed_unit_index == 0
    assert result.failed_statement_index == 1
    assert result.delta_id == target.delta_id
    assert result.line_range == (target.start_line, target.end_line)
    assert result.error_class == "SyntaxError"
    assert result.sqlstate == "42601"
    assert result.manual_inspection_required is False
    assert [call[2] for call in executor.calls if call[0] == "apply_unit"] == [0]
    finish = next(call for call in executor.calls if call[0] == "finish_run")
    assert finish[2] == "failed"
    run_failure = cast("RunFailure", finish[3])
    assert (run_failure.unit_index, run_failure.statement_index) == (0, 1)
    assert (run_failure.error_class, run_failure.sqlstate) == ("SyntaxError", "42601")
    assert any(isinstance(event, UnitFailed) for event in events)
    assert [type(event) for event in events[-2:]] == [UnitFailed, RunFinished]
    finished = cast("RunFinished", events[-1])
    assert finished.status == "failed"
    assert "private" not in str(raised.value)
    assert target.sql not in str(raised.value)


async def test_nontransactional_failure_requires_manual_inspection() -> None:
    bundle = _bundle()
    unit = bundle.units[1]
    executor = FakeExecutor(failures={(unit.index, 0): UnitFailure(0, "UniqueViolation", "23505")})

    with pytest.raises(ApplyMigrationError) as raised:
        await _apply(bundle, executor, approve_destructive=False)

    result = cast("ApplyResult", raised.value.result)
    assert result.failed_unit_index == unit.index
    assert result.delta_id == unit.statements[0].delta_id
    assert result.line_range == (unit.statements[0].start_line, unit.statements[0].end_line)
    assert result.manual_inspection_required is True


async def test_failed_transactional_unit_resumes_at_that_unit() -> None:
    bundle = _bundle()
    executor = FakeExecutor(_history(bundle, ("failed", "pending")))

    result = await _apply(bundle, executor, approve_destructive=False)

    assert result.resumed is True
    assert [call[2] for call in executor.calls if call[0] == "apply_unit"] == [0, 1]
    assert ("start_run", True) in executor.calls


async def test_applied_prefix_resumes_at_first_non_applied_unit() -> None:
    bundle = _bundle()
    executor = FakeExecutor(_history(bundle, ("applied", "pending")))

    result = await _apply(bundle, executor, approve_destructive=False)

    assert result.applied_unit_count == 2
    assert [call[2] for call in executor.calls if call[0] == "apply_unit"] == [1]


async def test_fully_applied_bundle_is_an_error() -> None:
    bundle = _bundle()
    executor = FakeExecutor(_history(bundle, ("applied", "applied"), run_status="applied"))

    with pytest.raises(ApplyMigrationError, match="already been applied"):
        await _apply(bundle, executor, approve_destructive=False)

    assert not any(call[0] in {"start_run", "apply_unit"} for call in executor.calls)


async def test_all_applied_units_are_an_error_even_if_run_status_is_failed() -> None:
    bundle = _bundle()
    executor = FakeExecutor(_history(bundle, ("applied", "applied"), run_status="failed"))

    with pytest.raises(ApplyMigrationError, match="already been applied"):
        await _apply(bundle, executor, approve_destructive=False)

    assert not any(call[0] in {"start_run", "apply_unit"} for call in executor.calls)


@pytest.mark.parametrize(
    "mismatch",
    ["up-checksum", "unit-checksum", "transaction-mode", "unit-count", "unit-index"],
)
async def test_history_mismatch_fails_before_execution(mismatch: str) -> None:
    bundle = _bundle()
    history = _history(bundle, ("pending", "pending"))
    if mismatch == "up-checksum":
        history = replace(history, up_sql_sha256="0" * 64)
    elif mismatch == "unit-checksum":
        units = (replace(history.units[0], sql_sha256="0" * 64), *history.units[1:])
        history = replace(history, units=units)
    elif mismatch == "transaction-mode":
        units = (
            replace(history.units[0], transactional=not history.units[0].transactional),
            *history.units[1:],
        )
        history = replace(history, units=units)
    elif mismatch == "unit-index":
        units = (replace(history.units[0], index=1), *history.units[1:])
        history = replace(history, units=units)
    else:
        history = replace(history, units=history.units[:-1])
    executor = FakeExecutor(history)

    with pytest.raises(ApplyMigrationError):
        await _apply(bundle, executor, approve_destructive=False)

    assert not any(call[0] in {"start_run", "apply_unit"} for call in executor.calls)


@pytest.mark.parametrize("corrupt", ["run-status", "unit-status"])
async def test_invalid_history_status_fails_closed(corrupt: str) -> None:
    bundle = _bundle()
    history = _history(bundle, ("pending", "pending"))
    if corrupt == "run-status":
        history = replace(history, status=cast("RunStatus", "unknown"))
    else:
        units = (
            replace(history.units[0], status=cast("UnitStatus", "unknown")),
            *history.units[1:],
        )
        history = replace(history, units=units)
    executor = FakeExecutor(history)

    with pytest.raises(ApplyMigrationError, match="corrupt"):
        await _apply(bundle, executor, approve_destructive=False)

    assert not any(call[0] in {"start_run", "apply_unit"} for call in executor.calls)


async def test_non_prefix_history_fails_closed() -> None:
    bundle = _bundle()
    executor = FakeExecutor(_history(bundle, ("pending", "applied")))

    with pytest.raises(ApplyMigrationError, match="corrupt"):
        await _apply(bundle, executor, approve_destructive=False)

    assert not any(call[0] in {"start_run", "apply_unit"} for call in executor.calls)


async def test_running_nontransactional_unit_fails_closed() -> None:
    bundle = _bundle()
    executor = FakeExecutor(_history(bundle, ("applied", "running")))

    with pytest.raises(ApplyMigrationError, match="manual inspection"):
        await _apply(bundle, executor, approve_destructive=False)

    assert not any(call[0] in {"start_run", "apply_unit"} for call in executor.calls)


async def test_running_transactional_unit_is_safe_to_retry() -> None:
    bundle = _bundle()
    executor = FakeExecutor(_history(bundle, ("running", "pending")))

    result = await _apply(bundle, executor, approve_destructive=False)

    assert result.resumed is True
    assert [call[2] for call in executor.calls if call[0] == "apply_unit"] == [0, 1]


async def test_cancellation_emits_event_finishes_cancelled_and_reraises() -> None:
    bundle = _bundle()
    executor = FakeExecutor(cancel_on_unit=0, fail_cancel_finish=True)
    events: list[object] = []

    with pytest.raises(asyncio.CancelledError):
        await _apply(bundle, executor, approve_destructive=False, on_event=events.append)

    assert any(isinstance(event, RunCancelled) for event in events)
    cancelled = next(event for event in events if isinstance(event, RunCancelled))
    assert (cancelled.current_unit_index, cancelled.current_statement_index) == (0, 0)
    finish = next(call for call in executor.calls if call[0] == "finish_run")
    assert finish[2] == "cancelled"


async def test_empty_bundle_is_noop_without_executor_calls() -> None:
    plan = generate_migration(
        DeltaSet(),
        source_fingerprint=_FINGERPRINT,
        target_fingerprint=_FINGERPRINT,
        clock=lambda: datetime(2026, 10, 24, 12, 30, 45, tzinfo=UTC),
        id_factory=lambda: "empty-apply-bundle",
    )
    files = dict(render_bundle(plan).files)
    bundle = load_bundle(files["manifest.json"], files["up.sql"])
    executor = FakeExecutor()

    result = await _apply(bundle, executor, approve_destructive=False)

    assert result.status == "noop"
    assert result.unit_count == 0
    assert executor.calls == []
