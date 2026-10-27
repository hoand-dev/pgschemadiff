"""Immutable presentation models for offline HTML reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pgschemadiff import __version__
from pgschemadiff.application.migration.render import target_label
from pgschemadiff.application.sql_emit.risk import RiskLevel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.application.migration.bundle import ValidatedBundle
    from pgschemadiff.application.sql_emit.risk import RiskAssessment


@dataclass(frozen=True)
class ReportRow:
    """One assessed schema change displayed in the report."""

    delta_id: str
    level: RiskLevel
    kind: str
    target: str
    reason: str
    reversible: bool | None = None
    reversibility_reason: str | None = None


@dataclass(frozen=True)
class ReportUnit:
    """A validated bundle execution unit and its SQL source ranges."""

    index: int
    transactional: bool
    max_risk: RiskLevel
    delta_ids: tuple[str, ...]
    start_line: int
    end_line: int
    statements: tuple[tuple[int, int, str], ...]


@dataclass(frozen=True)
class ReportModel:
    """Complete data needed to render either supported report variant."""

    tool_version: str
    generated_at: datetime
    risk_totals: tuple[tuple[RiskLevel, int], ...]
    rows: tuple[ReportRow, ...]
    source_name: str | None = None
    target_name: str | None = None
    bundle_id: str | None = None
    bundle_slug: str | None = None
    bundle_created_at: str | None = None
    delta_count: int | None = None
    overall_max_risk: RiskLevel | None = None
    up_sql_sha256: str | None = None
    units: tuple[ReportUnit, ...] = ()


def _generated_at_utc(generated_at: datetime) -> datetime:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return generated_at.astimezone(UTC)


def _risk_totals(levels: Iterable[RiskLevel]) -> tuple[tuple[RiskLevel, int], ...]:
    counts = dict.fromkeys(RiskLevel, 0)
    for level in levels:
        counts[level] += 1
    return tuple((level, counts[level]) for level in RiskLevel)


def from_comparison(
    result: SchemaComparisonResult,
    assessments: tuple[tuple[str, RiskAssessment], ...],
    *,
    generated_at: datetime,
) -> ReportModel:
    """Build report data from the same assessments used by the CLI summary."""
    rows = tuple(
        ReportRow(
            delta_id=delta_id,
            level=assessment.level,
            kind=assessment.delta.model_dump()["kind"],
            target=target_label(assessment.delta),
            reason=assessment.reason,
        )
        for delta_id, assessment in assessments
    )
    return ReportModel(
        tool_version=__version__,
        generated_at=_generated_at_utc(generated_at),
        risk_totals=_risk_totals(assessment.level for _, assessment in assessments),
        rows=rows,
        source_name=result.source.name,
        target_name=result.target.name,
    )


def from_bundle(bundle: ValidatedBundle, *, generated_at: datetime) -> ReportModel:
    """Build report data from a checksum-validated migration bundle."""
    rows = tuple(
        ReportRow(
            delta_id=assessment.delta_id,
            level=assessment.level,
            kind=assessment.kind,
            target=assessment.target,
            reason=assessment.reason,
            reversible=assessment.reversible,
            reversibility_reason=assessment.reversibility_reason,
        )
        for assessment in bundle.assessments
    )
    units = tuple(
        ReportUnit(
            index=unit.index,
            transactional=unit.transactional,
            max_risk=unit.max_risk,
            delta_ids=unit.delta_ids,
            start_line=unit.start_line,
            end_line=unit.end_line,
            statements=tuple(
                (statement.start_line, statement.end_line, statement.sql)
                for statement in unit.statements
            ),
        )
        for unit in bundle.units
    )
    return ReportModel(
        tool_version=bundle.tool_version,
        generated_at=_generated_at_utc(generated_at),
        risk_totals=_risk_totals(assessment.level for assessment in bundle.assessments),
        rows=rows,
        bundle_id=bundle.id,
        bundle_slug=bundle.slug,
        bundle_created_at=bundle.created_at,
        delta_count=bundle.delta_count,
        overall_max_risk=bundle.overall_max_risk,
        up_sql_sha256=bundle.up_sql_sha256,
        units=units,
    )
