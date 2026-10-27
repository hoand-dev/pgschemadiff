from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pgschemadiff.presentation.report.model as report_model
from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
from pgschemadiff.application.migration.bundle import (
    BundleAssessment,
    BundleStatement,
    BundleUnit,
    ValidatedBundle,
)
from pgschemadiff.application.migration.generate import assess_deltas
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import CreateSchema, DeltaSet, DropSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.presentation.report.html import render_report
from pgschemadiff.presentation.report.model import ReportModel, from_bundle, from_comparison

if TYPE_CHECKING:
    import pytest
    from syrupy.assertion import SnapshotAssertion

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


def _comparison_report(*, realistic: bool) -> ReportModel:
    delta_set = (
        DeltaSet.from_iterable(
            (_schema_delta("legacy", create=False), _schema_delta("app", create=True))
        )
        if realistic
        else DeltaSet()
    )
    result = SchemaComparisonResult(
        source=Database(name="current"),
        target=Database(name="desired"),
        deltas=delta_set,
    )
    return from_comparison(result, assess_deltas(delta_set), generated_at=GENERATED_AT)


def _bundle(*, hostile: str = "") -> ValidatedBundle:
    def value(default: str) -> str:
        return hostile or default

    return ValidatedBundle(
        format_version=1,
        tool_version=value("0.1.0"),
        id=value("bundle-123"),
        slug=value("release-1"),
        created_at=value("2026-10-26T12:00:00Z"),
        source_fingerprint=None,
        target_fingerprint=None,
        delta_count=1,
        overall_max_risk=RiskLevel.DANGEROUS,
        assessments=(
            BundleAssessment(
                delta_id=value("d0001"),
                kind=value("create_schema"),
                target=value("public.app"),
                level=RiskLevel.DANGEROUS,
                reason=value("Creates schema."),
                reversible=False,
                reversibility_reason=value("No inverse SQL is generated."),
            ),
        ),
        units=(
            BundleUnit(
                index=0,
                transactional=True,
                start_line=6,
                end_line=6,
                max_risk=RiskLevel.DANGEROUS,
                delta_ids=("d0001",),
                statements=(
                    BundleStatement(
                        delta_id="d0001",
                        start_line=6,
                        end_line=6,
                        sql=value("CREATE SCHEMA app"),
                    ),
                ),
                sql_sha256="a" * 64,
            ),
        ),
        up_sql_sha256="b" * 64,
    )


def test_empty_comparison_report_matches_snapshot(
    snapshot: SnapshotAssertion,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(report_model, "__version__", "0.1.0")
    assert render_report(_comparison_report(realistic=False)) == snapshot


def test_realistic_comparison_report_matches_snapshot(
    snapshot: SnapshotAssertion,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(report_model, "__version__", "0.1.0")
    assert render_report(_comparison_report(realistic=True)) == snapshot


def test_bundle_report_matches_snapshot(snapshot: SnapshotAssertion) -> None:
    model = from_bundle(_bundle(), generated_at=GENERATED_AT)

    assert render_report(model) == snapshot


def test_bundle_report_escapes_all_dynamic_values_and_includes_restrictive_csp() -> None:
    hostile = "'<script>\"&</pre>"
    rendered = render_report(from_bundle(_bundle(hostile=hostile), generated_at=GENERATED_AT))

    assert "&#x27;&lt;script&gt;&quot;&amp;&lt;/pre&gt;" in rendered
    assert hostile not in rendered
    assert "<script" not in rendered.lower()
    assert "&lt;/pre&gt;" in rendered
    assert (
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
    ) in rendered
    assert "dangerous" in rendered


def test_report_rendering_is_deterministic() -> None:
    report = render_report(_comparison_report(realistic=True))

    assert report == render_report(_comparison_report(realistic=True))
