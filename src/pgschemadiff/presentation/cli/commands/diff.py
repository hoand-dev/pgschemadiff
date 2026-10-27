"""``pgsd diff`` command implementation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import psycopg_pool
import typer
from rich.console import Console
from rich.text import Text

from pgschemadiff.application.migration.generate import assess_deltas
from pgschemadiff.application.migration.render import target_label
from pgschemadiff.application.sql_emit.risk import RiskAssessment, RiskLevel
from pgschemadiff.infrastructure.config.rename_loader import load_renames
from pgschemadiff.presentation import composition
from pgschemadiff.presentation.cli import output
from pgschemadiff.presentation.i18n import t
from pgschemadiff.presentation.report.html import render_report
from pgschemadiff.presentation.report.model import from_comparison
from pgschemadiff.shared.errors import DiffError, InspectionError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.application.diff.renames import RenameAnnotations
    from pgschemadiff.domain.delta.base import DeltaSet


async def compare_urls(
    source_url: str,
    target_url: str,
    schemas: list[str] | None,
    *,
    renames: RenameAnnotations | None = None,
    on_phase: Callable[[str], None] | None = None,
) -> DeltaSet:
    """Open both databases and compare their inspected schemas."""
    result = await composition.compare_conninfo(
        source_url,
        target_url,
        schemas,
        renames=renames,
        on_phase=on_phase,
    )
    return result.deltas


def diff_cmd(
    source_url: str,
    target_url: str,
    schemas: list[str] | None,
    renames_path: Path | None,
    output_format: str = "json",
    max_risk: RiskLevel | None = None,
) -> None:
    """Compare two PostgreSQL databases and print typed schema deltas.

    Connection URLs and driver exception messages are never included in CLI
    output or logs.
    """

    try:
        rename_annotations = load_renames(renames_path) if renames_path is not None else None
    except DiffError as error:
        output.error(t("diff.error.invalid_renames", error=error), 2)

    phase_steps = {
        "inspect-source": (1, "diff.progress.inspect_source"),
        "inspect-target": (2, "diff.progress.inspect_target"),
        "compare": (3, "diff.progress.compare"),
    }

    def on_phase(phase: str) -> None:
        step, key = phase_steps[phase]
        output.progress(step, 3, t(key))

    comparison_result: SchemaComparisonResult | None = None
    try:
        if output_format == "html":
            comparison_result = asyncio.run(
                composition.compare_conninfo(
                    source_url,
                    target_url,
                    schemas,
                    renames=rename_annotations,
                    on_phase=on_phase,
                )
            )
            delta_set = comparison_result.deltas
        else:
            delta_set = asyncio.run(
                compare_urls(
                    source_url,
                    target_url,
                    schemas,
                    renames=rename_annotations,
                    on_phase=on_phase,
                )
            )
    except (psycopg.Error, psycopg_pool.PoolTimeout):
        output.error(t("cli.error.connection_failed"), 1)
    except InspectionError:
        output.error(t("cli.error.schema_inspection_failed"), 1)
    except DiffError:
        output.error(t("cli.error.schema_comparison_failed"), 1)
    except Exception:
        output.error(t("cli.error.schema_diff_failed"), 1)

    # Assessment re-orders the deltas; skip it for plain JSON without a gate.
    needs_assessment = output_format in {"summary", "html"} or max_risk is not None
    assessments = assess_deltas(delta_set) if needs_assessment else ()
    if output_format == "html":
        assert comparison_result is not None
        model = from_comparison(
            comparison_result,
            assessments,
            generated_at=datetime.now(UTC),
        )
        typer.echo(render_report(model))
    elif output_format == "summary":
        _print_summary(assessments)
    else:
        typer.echo(delta_set.model_dump_json(indent=2))

    if max_risk is not None:
        risk_order = tuple(RiskLevel)
        max_index = risk_order.index(max_risk)
        exceeded = sum(
            risk_order.index(assessment.level) > max_index for _delta_id, assessment in assessments
        )
        if exceeded:
            output.error(
                t(
                    "diff.error.risk_gate",
                    count=exceeded,
                    level=max_risk.value,
                ),
                2,
            )


def _print_summary(
    assessments: tuple[tuple[str, RiskAssessment], ...],
) -> None:
    if not assessments:
        typer.echo("No schema changes.")
        return

    console = Console(markup=False, highlight=False, emoji=False, soft_wrap=True)
    counts = dict.fromkeys(RiskLevel, 0)
    for delta_id, assessment in assessments:
        counts[assessment.level] += 1
        line = Text(f"{delta_id}  ")
        line.append_text(output.risk_text(assessment.level))
        line.append(" " * (11 - len(assessment.level.value)))
        kind = assessment.delta.model_dump()["kind"]
        line.append(f"  {kind:<16}  {target_label(assessment.delta)}   {assessment.reason}")
        console.print(line)

    totals = " ".join(f"{level.value}={counts[level]}" for level in RiskLevel)
    console.print(f"{len(assessments)} changes: {totals}")
