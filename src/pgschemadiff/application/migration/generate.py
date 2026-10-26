"""Generate a deterministic, risk-gated migration plan from a DeltaSet."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.application.migration.model import (
    MigrationDeltaAssessment,
    MigrationPlan,
    MigrationPlanUnit,
    validate_slug,
)
from pgschemadiff.application.migration.render import target_label
from pgschemadiff.application.sql_emit.emitter import SqlEmitter
from pgschemadiff.application.sql_emit.registry import default_handlers
from pgschemadiff.application.sql_emit.risk import (
    RiskAssessment,
    RiskLevel,
    classify_risk,
    passes_risk_limit,
)
from pgschemadiff.application.sql_emit.transaction import split_units
from pgschemadiff.domain.delta import CreateTable, DeltaSet
from pgschemadiff.domain.delta.materialized_view import (
    DropMaterializedView,
    ReplaceMaterializedView,
)
from pgschemadiff.domain.delta.view import DropView, ReplaceView
from pgschemadiff.shared.errors import MigrationError, RiskGateError

if TYPE_CHECKING:
    from collections.abc import Callable

    from pgschemadiff.domain.identity import ObjectRef


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_plan_id() -> str:
    return str(uuid4())


def _clock_utc(clock: Callable[[], datetime]) -> datetime:
    created_at = clock()
    if not isinstance(created_at, datetime):
        raise MigrationError("clock must return an aware UTC datetime")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise MigrationError("clock must return an aware UTC datetime")
    return created_at.astimezone(UTC)


def _resolved_view_dependencies(
    deltas: DeltaSet,
) -> frozenset[tuple[ObjectRef, ObjectRef]]:
    resolved: set[tuple[ObjectRef, ObjectRef]] = set()
    for delta in deltas:
        old_prerequisites: tuple[ObjectRef, ...]
        new_prerequisites: tuple[ObjectRef, ...]
        if isinstance(delta, DropView):
            old_prerequisites = delta.view.prerequisites
            new_prerequisites = ()
        elif isinstance(delta, DropMaterializedView):
            old_prerequisites = delta.materialized_view.prerequisites
            new_prerequisites = ()
        elif isinstance(delta, ReplaceView):
            old_prerequisites = delta.old_view.prerequisites
            new_prerequisites = delta.new_view.prerequisites
        elif isinstance(delta, ReplaceMaterializedView):
            old_prerequisites = delta.old_materialized_view.prerequisites
            new_prerequisites = delta.new_materialized_view.prerequisites
        else:
            continue
        resolved.update(
            (delta.target, prerequisite)
            for prerequisite in old_prerequisites
            if prerequisite not in new_prerequisites
        )
    return frozenset(resolved)


def assess_deltas(delta_set: DeltaSet) -> tuple[tuple[str, RiskAssessment], ...]:
    """Return generator-ordered delta IDs and contextual risk assessments."""
    ordered_deltas = order_deltas(delta_set)
    created_tables = frozenset(
        delta.target for delta in delta_set if isinstance(delta, CreateTable)
    )
    resolved_view_dependencies = _resolved_view_dependencies(ordered_deltas)
    return tuple(
        (
            f"d{index:04d}",
            classify_risk(
                delta,
                created_tables=created_tables,
                resolved_view_dependencies=resolved_view_dependencies,
            ),
        )
        for index, delta in enumerate(ordered_deltas, start=1)
    )


def generate_migration(
    delta_set: DeltaSet,
    *,
    max_risk: RiskLevel = RiskLevel.DANGEROUS,
    source_fingerprint: str | None = None,
    target_fingerprint: str | None = None,
    slug: str = "diff",
    clock: Callable[[], datetime] = _utc_now,
    id_factory: Callable[[], str] = _new_plan_id,
) -> MigrationPlan:
    """Order, risk-gate, emit, and group SQL for a new migration plan."""
    if not isinstance(max_risk, RiskLevel):
        raise MigrationError("max_risk must be a RiskLevel")
    try:
        validate_slug(slug)
    except ValueError as error:
        raise MigrationError(str(error)) from error

    assessed_deltas = assess_deltas(delta_set)
    delta_ids = tuple(delta_id for delta_id, _assessment in assessed_deltas)
    risk_assessments = tuple(assessment for _delta_id, assessment in assessed_deltas)
    ordered_deltas = DeltaSet.from_iterable(assessment.delta for assessment in risk_assessments)

    if not passes_risk_limit(risk_assessments, max_risk=max_risk):
        offending = tuple(
            (delta_id, assessment)
            for delta_id, assessment in zip(delta_ids, risk_assessments, strict=True)
            if not passes_risk_limit((assessment,), max_risk=max_risk)
        )
        details = "\n".join(
            f"- {delta_id} kind={assessment.delta.model_dump()['kind']} "
            f"target={target_label(assessment.delta)} "
            f"level={assessment.level.value} reason={assessment.reason}"
            for delta_id, assessment in offending
        )
        raise RiskGateError(f"Migration risk gate failed (max_risk={max_risk.value}):\n{details}")

    statements = SqlEmitter(default_handlers()).emit(ordered_deltas)
    transaction_units = split_units(statements)

    records = tuple(
        MigrationDeltaAssessment(delta_id=delta_id, assessment=assessment)
        for delta_id, assessment in zip(delta_ids, risk_assessments, strict=True)
    )
    delta_id_by_identity = {
        id(assessment.delta): record.delta_id
        for assessment, record in zip(risk_assessments, records, strict=True)
    }
    assessments_by_delta = {assessment.delta: assessment for assessment in risk_assessments}

    planned_units: list[MigrationPlanUnit] = []
    for index, transaction_unit in enumerate(transaction_units):
        unit_delta_ids: list[str] = []
        for statement in transaction_unit.statements:
            delta_id = delta_id_by_identity.get(id(statement.delta))
            if delta_id is None:
                raise MigrationError("SQL statement provenance does not match an ordered delta.")
            if delta_id not in unit_delta_ids:
                unit_delta_ids.append(delta_id)
        planned_units.append(
            MigrationPlanUnit(
                index=index,
                transaction_unit=transaction_unit,
                max_risk=transaction_unit.max_risk_level(assessments_by_delta),
                delta_ids=tuple(unit_delta_ids),
            )
        )

    plan_id = id_factory()
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise MigrationError("id_factory must return a non-blank string")

    overall_max_risk = max(
        (assessment.level for assessment in risk_assessments),
        key=tuple(RiskLevel).index,
        default=None,
    )
    return MigrationPlan(
        id=plan_id,
        slug=slug,
        created_at=_clock_utc(clock),
        delta_set=ordered_deltas,
        source_fingerprint=source_fingerprint,
        target_fingerprint=target_fingerprint,
        assessments=records,
        units=tuple(planned_units),
        overall_max_risk=overall_max_risk,
    )
