from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
from pgschemadiff.application.migration.bundle import (
    BundleAssessment,
    BundleStatement,
    BundleUnit,
    ValidatedBundle,
)
from pgschemadiff.application.migration.generate import assess_deltas
from pgschemadiff.application.migration.render import target_label
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import CreateSchema, DeltaSet, DropSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.presentation.report.model import from_bundle, from_comparison

GENERATED_AT = datetime(2026, 10, 27, 1, 2, 3, tzinfo=UTC)


def _schema_delta(name: str, *, create: bool) -> CreateSchema | DropSchema:
    ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )
    schema = Schema(ref=ref)
    return (
        CreateSchema(target=ref, pg_schema=schema)
        if create
        else DropSchema(
            target=ref,
            pg_schema=schema,
        )
    )


def test_from_comparison_matches_summary_rows_and_counts_all_risks() -> None:
    delta_set = DeltaSet.from_iterable(
        (_schema_delta("legacy", create=False), _schema_delta("new", create=True))
    )
    result = SchemaComparisonResult(
        source=Database(name="current_db"),
        target=Database(name="desired_db"),
        deltas=delta_set,
    )

    report = from_comparison(result, assess_deltas(delta_set), generated_at=GENERATED_AT)

    expected_rows = tuple(
        (
            delta_id,
            assessment.level,
            assessment.delta.model_dump()["kind"],
            target_label(assessment.delta),
            assessment.reason,
        )
        for delta_id, assessment in assess_deltas(delta_set)
    )
    assert (
        tuple((row.delta_id, row.level, row.kind, row.target, row.reason) for row in report.rows)
        == expected_rows
    )
    assert report.source_name == "current_db"
    assert report.target_name == "desired_db"
    assert dict(report.risk_totals) == {
        RiskLevel.SAFE: 1,
        RiskLevel.WARNING: 0,
        RiskLevel.DANGEROUS: 0,
        RiskLevel.DESTRUCTIVE: 1,
        RiskLevel.BLOCKED: 0,
    }
    assert report.generated_at == GENERATED_AT


def test_from_comparison_normalizes_aware_generation_time_to_utc() -> None:
    delta_set = DeltaSet()
    result = SchemaComparisonResult(
        source=Database(name="current_db"),
        target=Database(name="desired_db"),
        deltas=delta_set,
    )
    generated_at = datetime.fromisoformat("2026-10-27T06:32:03+05:30")

    report = from_comparison(result, (), generated_at=generated_at)

    assert report.generated_at == GENERATED_AT


def test_report_builders_reject_naive_generation_time() -> None:
    result = SchemaComparisonResult(
        source=Database(name="current_db"),
        target=Database(name="desired_db"),
        deltas=DeltaSet(),
    )

    with pytest.raises(ValueError, match="generated_at must be timezone-aware"):
        from_comparison(result, (), generated_at=datetime(2026, 10, 27))


def test_from_bundle_maps_assessments_units_and_statement_ranges() -> None:
    bundle = ValidatedBundle(
        format_version=1,
        tool_version="0.1.0",
        id="bundle-123",
        slug="release-1",
        created_at="2026-10-26T12:00:00Z",
        source_fingerprint=None,
        target_fingerprint=None,
        delta_count=1,
        overall_max_risk=RiskLevel.SAFE,
        assessments=(
            BundleAssessment(
                delta_id="d0001",
                kind="create_schema",
                target="public.app",
                level=RiskLevel.SAFE,
                reason="Schema does not exist.",
                reversible=False,
                reversibility_reason="No inverse SQL is generated.",
            ),
        ),
        units=(
            BundleUnit(
                index=0,
                transactional=True,
                start_line=6,
                end_line=6,
                max_risk=RiskLevel.SAFE,
                delta_ids=("d0001",),
                statements=(
                    BundleStatement(
                        delta_id="d0001",
                        start_line=6,
                        end_line=6,
                        sql="CREATE SCHEMA app",
                    ),
                ),
                sql_sha256="a" * 64,
            ),
        ),
        up_sql_sha256="b" * 64,
    )

    report = from_bundle(bundle, generated_at=GENERATED_AT)

    assert report.bundle_id == "bundle-123"
    assert report.bundle_slug == "release-1"
    assert report.bundle_created_at == "2026-10-26T12:00:00Z"
    assert report.delta_count == 1
    assert report.overall_max_risk is RiskLevel.SAFE
    assert report.up_sql_sha256 == "b" * 64
    assert report.rows[0].reversible is False
    assert report.rows[0].reversibility_reason == "No inverse SQL is generated."
    assert report.units[0].index == 0
    assert report.units[0].transactional is True
    assert report.units[0].max_risk is RiskLevel.SAFE
    assert report.units[0].delta_ids == ("d0001",)
    assert report.units[0].start_line == 6
    assert report.units[0].end_line == 6
    assert report.units[0].statements == ((6, 6, "CREATE SCHEMA app"),)
