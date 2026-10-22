"""Risk assessments and generation-limit checks for schema deltas."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from pgschemadiff.domain.delta import DeltaBase


class RiskLevel(StrEnum):
    """Ordered risk levels assigned to SQL-generating schema deltas."""

    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"
    DESTRUCTIVE = "destructive"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RiskAssessment:
    """Risk classification and rationale for one domain delta."""

    delta: DeltaBase
    level: RiskLevel
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("Risk assessment reason must not be blank")


_RISK_RANK = {
    RiskLevel.SAFE: 0,
    RiskLevel.WARNING: 1,
    RiskLevel.DANGEROUS: 2,
    RiskLevel.DESTRUCTIVE: 3,
    RiskLevel.BLOCKED: 4,
}


def passes_risk_limit(
    assessments: Iterable[RiskAssessment],
    *,
    max_risk: RiskLevel = RiskLevel.DANGEROUS,
) -> bool:
    """Return whether assessments stay within the limit and contain no BLOCKED risk."""
    return all(
        assessment.level is not RiskLevel.BLOCKED
        and _RISK_RANK[assessment.level] <= _RISK_RANK[max_risk]
        for assessment in assessments
    )
