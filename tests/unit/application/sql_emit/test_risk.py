from dataclasses import FrozenInstanceError

import pytest

from pgschemadiff.application.sql_emit.risk import (
    RiskAssessment,
    RiskLevel,
    passes_risk_limit,
)
from pgschemadiff.domain.delta import CreateSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema

_SCHEMA_REF = ObjectRef(
    kind=ObjectKind.SCHEMA,
    qname=QualifiedName(namespace="public", name="public"),
)
_DELTA = CreateSchema(target=_SCHEMA_REF, pg_schema=Schema(ref=_SCHEMA_REF))


def _assessment(level: RiskLevel) -> RiskAssessment:
    return RiskAssessment(delta=_DELTA, level=level, reason=level.value)


def test_risk_levels_have_explicit_severity_order() -> None:
    assert tuple(level.name for level in RiskLevel) == (
        "SAFE",
        "WARNING",
        "DANGEROUS",
        "DESTRUCTIVE",
        "BLOCKED",
    )


def test_assessment_keeps_delta_is_frozen_and_rejects_blank_reason() -> None:
    assessment = _assessment(RiskLevel.SAFE)
    assert assessment.delta is _DELTA
    with pytest.raises(FrozenInstanceError):
        assessment.reason = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="blank"):
        RiskAssessment(delta=_DELTA, level=RiskLevel.SAFE, reason="  ")


def test_default_risk_limit_allows_through_dangerous() -> None:
    allowed = tuple(
        _assessment(level)
        for level in (
            RiskLevel.SAFE,
            RiskLevel.WARNING,
            RiskLevel.DANGEROUS,
        )
    )
    assert passes_risk_limit(allowed)
    assert not passes_risk_limit((_assessment(RiskLevel.DESTRUCTIVE),))


def test_blocked_never_passes_even_when_selected_as_limit() -> None:
    assert not passes_risk_limit(
        (_assessment(RiskLevel.DANGEROUS),),
        max_risk=RiskLevel.WARNING,
    )
    assert passes_risk_limit(
        (_assessment(RiskLevel.DESTRUCTIVE),),
        max_risk=RiskLevel.DESTRUCTIVE,
    )
    assert not passes_risk_limit(
        (_assessment(RiskLevel.BLOCKED),),
        max_risk=RiskLevel.BLOCKED,
    )


def test_empty_assessment_collection_passes() -> None:
    assert passes_risk_limit(())
