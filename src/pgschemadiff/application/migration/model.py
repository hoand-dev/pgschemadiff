"""Immutable application models for generated migration plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.risk import RiskLevel

if TYPE_CHECKING:
    from pgschemadiff.application.sql_emit.risk import RiskAssessment
    from pgschemadiff.application.sql_emit.transaction import TransactionUnit
    from pgschemadiff.domain.delta import DeltaSet

IRREVERSIBILITY_REASON = (
    "MVP-A does not derive inverse SQL from DeltaSet; complete prior state may be missing."
)

_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DELTA_ID_PATTERN = re.compile(r"d[0-9]{4,}")
_RISK_LEVELS = tuple(RiskLevel)


def validate_slug(slug: str) -> None:
    if not isinstance(slug, str) or _SLUG_PATTERN.fullmatch(slug) is None:
        raise ValueError(
            "slug must use lowercase ASCII letters, digits, and hyphen-separated parts"
        )


def _validate_delta_id(delta_id: str) -> None:
    if not isinstance(delta_id, str) or _DELTA_ID_PATTERN.fullmatch(delta_id) is None:
        raise ValueError("delta_id must use the bundle-local form d0001, d0002, ...")


@dataclass(frozen=True)
class MigrationDeltaAssessment:
    """Risk and MVP-A reversibility metadata for one ordered delta."""

    delta_id: str
    assessment: RiskAssessment
    reversible: bool = False
    reversibility_reason: str = IRREVERSIBILITY_REASON

    def __post_init__(self) -> None:
        _validate_delta_id(self.delta_id)
        if self.reversible is not False:
            raise ValueError("MVP-A migration assessments must be irreversible")
        if not self.reversibility_reason.strip():
            raise ValueError("reversibility_reason must not be blank")
        if self.reversibility_reason != IRREVERSIBILITY_REASON:
            raise ValueError("MVP-A reversibility reason must match the approved contract")


@dataclass(frozen=True)
class MigrationPlanUnit:
    """A transaction unit with its plan-local position, risk, and provenance."""

    index: int
    transaction_unit: TransactionUnit
    max_risk: RiskLevel
    delta_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("MigrationPlanUnit.index must not be negative")
        if not isinstance(self.max_risk, RiskLevel):
            raise TypeError("MigrationPlanUnit.max_risk must be a RiskLevel")
        if not isinstance(self.delta_ids, tuple):
            raise TypeError("MigrationPlanUnit.delta_ids must be a tuple")
        if not self.delta_ids:
            raise ValueError("MigrationPlanUnit.delta_ids must not be empty")
        for delta_id in self.delta_ids:
            _validate_delta_id(delta_id)
        if len(self.delta_ids) != len(set(self.delta_ids)):
            raise ValueError("MigrationPlanUnit.delta_ids must be unique and ordered")


@dataclass(frozen=True)
class MigrationPlan:
    """Ordered, risk-gated migration output before bundle rendering or writing."""

    id: str
    slug: str
    created_at: datetime
    delta_set: DeltaSet
    source_fingerprint: str | None
    target_fingerprint: str | None
    assessments: tuple[MigrationDeltaAssessment, ...]
    units: tuple[MigrationPlanUnit, ...]
    overall_max_risk: RiskLevel | None
    inspected_schemas: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _validate_plan_metadata(self)
        _validate_plan_assessments(self)
        _validate_plan_units(self)
        expected_overall = max(
            (record.assessment.level for record in self.assessments),
            key=_RISK_LEVELS.index,
            default=None,
        )
        if self.overall_max_risk is not expected_overall:
            raise ValueError("MigrationPlan overall_max_risk must match its assessments")


def _validate_plan_metadata(plan: MigrationPlan) -> None:
    if not isinstance(plan.id, str) or not plan.id.strip():
        raise ValueError("MigrationPlan.id must not be blank")
    validate_slug(plan.slug)
    if plan.created_at.tzinfo is None or plan.created_at.utcoffset() is None:
        raise ValueError("MigrationPlan.created_at must be timezone-aware")
    object.__setattr__(plan, "created_at", plan.created_at.astimezone(UTC))


def _validate_plan_assessments(plan: MigrationPlan) -> None:
    if not isinstance(plan.assessments, tuple):
        raise TypeError("MigrationPlan.assessments must be a tuple")
    if len(plan.assessments) != len(plan.delta_set):
        raise ValueError("MigrationPlan must contain one assessment per ordered delta")

    for index, (delta, record) in enumerate(zip(plan.delta_set, plan.assessments, strict=True), 1):
        if record.delta_id != f"d{index:04d}":
            raise ValueError("MigrationPlan assessment IDs must follow ordered position")
        if record.assessment.delta is not delta:
            raise ValueError("MigrationPlan assessment must retain original delta identity")


def _validate_plan_units(plan: MigrationPlan) -> None:
    if not isinstance(plan.units, tuple):
        raise TypeError("MigrationPlan.units must be a tuple")

    assessments_by_id = {record.delta_id: record for record in plan.assessments}
    delta_ids_by_identity = {
        id(record.assessment.delta): record.delta_id for record in plan.assessments
    }
    used_delta_ids: set[str] = set()
    for index, planned_unit in enumerate(plan.units):
        if planned_unit.index != index:
            raise ValueError("MigrationPlan unit indices must be zero-based and ordered")

        expected_ids: list[str] = []
        for statement in planned_unit.transaction_unit.statements:
            delta_id = delta_ids_by_identity.get(id(statement.delta))
            if delta_id is None:
                raise ValueError("MigrationPlan unit statement has unknown delta provenance")
            if delta_id not in expected_ids:
                expected_ids.append(delta_id)
        if planned_unit.delta_ids != tuple(expected_ids):
            raise ValueError("MigrationPlan unit delta IDs must match statement provenance")

        expected_risk = max(
            (assessments_by_id[delta_id].assessment.level for delta_id in expected_ids),
            key=_RISK_LEVELS.index,
        )
        if planned_unit.max_risk is not expected_risk:
            raise ValueError("MigrationPlan unit max_risk must match its delta assessments")
        used_delta_ids.update(expected_ids)

    if used_delta_ids != set(assessments_by_id):
        raise ValueError("MigrationPlan units must cover every assessed delta")
