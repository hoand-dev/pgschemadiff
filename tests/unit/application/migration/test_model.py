from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from pgschemadiff.application.migration import MigrationPlan, generate_migration
from pgschemadiff.application.migration.model import (
    IRREVERSIBILITY_REASON,
    MigrationDeltaAssessment,
    MigrationPlanUnit,
)
from pgschemadiff.application.sql_emit.emitter import SqlStatement
from pgschemadiff.application.sql_emit.risk import RiskLevel, classify_risk
from pgschemadiff.application.sql_emit.transaction import TransactionUnit
from pgschemadiff.domain.delta import CreateSchema, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema


def _create_schema(name: str) -> CreateSchema:
    ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )
    return CreateSchema(target=ref, pg_schema=Schema(ref=ref))


def _plan() -> MigrationPlan:
    return generate_migration(
        DeltaSet.from_iterable((_create_schema("app"),)),
        clock=lambda: datetime(2026, 10, 24, 12, tzinfo=UTC),
        id_factory=lambda: "plan-id",
    )


def test_generated_model_records_are_frozen_and_irreversible() -> None:
    plan = _plan()

    with pytest.raises(FrozenInstanceError):
        plan.slug = "changed"  # type: ignore[misc]

    assessment = plan.assessments[0]
    assert assessment.delta_id == "d0001"
    assert assessment.reversible is False
    assert assessment.reversibility_reason == IRREVERSIBILITY_REASON
    with pytest.raises(FrozenInstanceError):
        assessment.delta_id = "d0002"  # type: ignore[misc]

    unit = plan.units[0]
    assert unit.index == 0
    assert unit.max_risk is RiskLevel.SAFE
    assert unit.delta_ids == ("d0001",)
    with pytest.raises(FrozenInstanceError):
        unit.index = 1  # type: ignore[misc]


@pytest.mark.parametrize("delta_id", [("",), ("d1",), ("d000x",), ("../01",)])
def test_delta_assessment_rejects_invalid_bundle_id(delta_id: str) -> None:
    delta = _create_schema("app")

    with pytest.raises(ValueError, match="delta_id"):
        MigrationDeltaAssessment(delta_id, classify_risk(delta))


def test_delta_assessment_rejects_reversible_mvp_record() -> None:
    with pytest.raises(ValueError, match="irreversible"):
        MigrationDeltaAssessment("d0001", classify_risk(_create_schema("app")), reversible=True)


def test_delta_assessment_rejects_blank_reversibility_reason() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        MigrationDeltaAssessment(
            "d0001",
            classify_risk(_create_schema("app")),
            reversibility_reason=" ",
        )


def test_delta_assessment_rejects_noncanonical_reversibility_reason() -> None:
    with pytest.raises(ValueError, match="MVP-A reversibility reason"):
        MigrationDeltaAssessment(
            "d0001",
            classify_risk(_create_schema("app")),
            reversibility_reason="An inverse might be available.",
        )


def test_plan_normalizes_aware_timestamps_to_utc() -> None:
    plan = _plan()
    non_utc = replace(plan, created_at=datetime.fromisoformat("2026-10-24T14:00:00+02:00"))

    assert non_utc.created_at == datetime(2026, 10, 24, 12, tzinfo=UTC)
    assert non_utc.created_at.tzinfo is UTC


def test_plan_rejects_assessment_identity_or_id_mismatch() -> None:
    plan = _plan()
    wrong_id = replace(plan.assessments[0], delta_id="d0002")

    with pytest.raises(ValueError, match="ordered position"):
        replace(plan, assessments=(wrong_id,))

    wrong_delta = replace(
        plan.assessments[0],
        assessment=classify_risk(_create_schema("other")),
    )
    with pytest.raises(ValueError, match="original delta identity"):
        replace(plan, assessments=(wrong_delta,))


def test_plan_rejects_blank_id_naive_time_and_assessment_count_mismatch() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="id must not be blank"):
        replace(plan, id=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(plan, created_at=datetime(2026, 10, 24, 12))
    with pytest.raises(ValueError, match="one assessment per ordered delta"):
        replace(plan, assessments=())


def test_plan_unit_rejects_duplicate_delta_ids() -> None:
    plan = _plan()
    unit = plan.units[0]

    with pytest.raises(ValueError, match="unique"):
        replace(unit, delta_ids=("d0001", "d0001"))


def test_plan_unit_rejects_invalid_index_risk_and_delta_id_container() -> None:
    unit = _plan().units[0]

    with pytest.raises(ValueError, match="must not be negative"):
        replace(unit, index=-1)
    with pytest.raises(TypeError, match="RiskLevel"):
        replace(unit, max_risk="safe")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="tuple"):
        replace(unit, delta_ids=["d0001"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be empty"):
        replace(unit, delta_ids=())


def test_plan_rejects_unit_metadata_that_disagrees_with_statements() -> None:
    plan = _plan()
    unit = plan.units[0]

    with pytest.raises(ValueError, match="zero-based and ordered"):
        replace(plan, units=(replace(unit, index=1),))
    with pytest.raises(ValueError, match="match statement provenance"):
        replace(plan, units=(replace(unit, delta_ids=("d0002",)),))
    with pytest.raises(ValueError, match="max_risk must match"):
        replace(plan, units=(replace(unit, max_risk=RiskLevel.WARNING),))
    with pytest.raises(ValueError, match="overall_max_risk"):
        replace(plan, overall_max_risk=RiskLevel.WARNING)


def test_plan_rejects_units_with_unknown_delta_provenance() -> None:
    plan = _plan()
    other_delta = _create_schema("other")
    transaction_unit = TransactionUnit(
        statements=(SqlStatement("CREATE SCHEMA", True, other_delta),),
        transactional=True,
    )
    unit = MigrationPlanUnit(0, transaction_unit, RiskLevel.SAFE, ("d0001",))

    with pytest.raises(ValueError, match="unknown delta provenance"):
        replace(plan, units=(unit,))


def test_nonempty_plan_requires_unit_provenance_for_every_delta() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="cover every assessed delta"):
        replace(plan, units=())


def test_plan_rejects_mutable_assessment_and_unit_collections() -> None:
    plan = _plan()

    with pytest.raises(TypeError, match="tuple"):
        replace(plan, assessments=list(plan.assessments))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="tuple"):
        replace(plan, units=list(plan.units))  # type: ignore[arg-type]
