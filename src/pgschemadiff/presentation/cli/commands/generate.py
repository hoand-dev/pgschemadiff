"""``pgsd generate`` command implementation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psycopg
import psycopg_pool
import typer

from pgschemadiff.application.diff.fingerprint import schema_fingerprint
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.infrastructure.config.rename_loader import load_renames
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.presentation import composition
from pgschemadiff.presentation.cli import output
from pgschemadiff.presentation.i18n import t
from pgschemadiff.shared.errors import DiffError, InspectionError, MigrationError, RiskGateError

if TYPE_CHECKING:
    from pathlib import Path


def _validate_generate_options(out_dir: Path, max_risk: RiskLevel) -> None:
    if max_risk is RiskLevel.BLOCKED:
        output.error(t("generate.error.blocked_max_risk"), 2)
    if not out_dir.is_dir():
        output.error(t("generate.error.output_directory"), 2)


def generate_cmd(
    source_url: str,
    target_url: str,
    out_dir: Path,
    schemas: list[str] | None,
    renames_path: Path | None,
    max_risk: RiskLevel,
    name: str,
) -> None:
    """Compare schemas, then generate and write a risk-gated bundle."""
    _validate_generate_options(out_dir, max_risk)

    try:
        renames = load_renames(renames_path) if renames_path is not None else None
    except DiffError as error:
        output.error(t("diff.error.invalid_renames", error=error), 2)

    phase_steps = {
        "inspect-source": (1, "diff.progress.inspect_source"),
        "inspect-target": (2, "diff.progress.inspect_target"),
        "compare": (3, "diff.progress.compare"),
    }

    def on_phase(phase: str) -> None:
        step, key = phase_steps[phase]
        output.progress(step, 5, t(key))

    try:
        comparison = asyncio.run(
            composition.compare_conninfo(
                source_url,
                target_url,
                schemas,
                renames=renames,
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

    if comparison.deltas.is_empty():
        typer.echo(t("generate.no_changes"), err=True)
        return

    output.progress(4, 5, t("generate.progress.migration"))
    try:
        plan = generate_migration(
            comparison.deltas,
            max_risk=max_risk,
            slug=name,
            source_fingerprint=schema_fingerprint(comparison.source),
            target_fingerprint=schema_fingerprint(comparison.target),
            inspected_schemas=schemas,
        )
    except RiskGateError as error:
        output.error(t("generate.error.risk_gate", detail=str(error)), 2)
    except MigrationError as error:
        # Generation errors describe options and deltas only, never connections.
        output.error(t("generate.error.migration", error=error), 1)
    except Exception:
        output.error(t("generate.error.migration_failed"), 1)

    output.progress(5, 5, t("generate.progress.bundle"))
    try:
        bundle_path = FilesystemMigrationWriter().write(plan, out_dir)
    except Exception:
        output.error(t("generate.error.bundle_write"), 1)

    typer.echo(str(bundle_path))
    counts: dict[RiskLevel, int] = dict.fromkeys(
        (level for level in RiskLevel if level is not RiskLevel.BLOCKED), 0
    )
    for record in plan.assessments:
        counts[record.assessment.level] += 1
    typer.echo(
        t(
            "generate.success.summary",
            count=len(plan.delta_set),
            max_risk=plan.overall_max_risk,
            units=len(plan.units),
            safe=counts[RiskLevel.SAFE],
            warning=counts[RiskLevel.WARNING],
            dangerous=counts[RiskLevel.DANGEROUS],
            destructive=counts[RiskLevel.DESTRUCTIVE],
        ),
        err=True,
    )
