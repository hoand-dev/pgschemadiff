"""``pgsd generate`` command implementation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psycopg
import psycopg_pool
import typer

from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.infrastructure.config.rename_loader import load_renames
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.presentation.cli import output
from pgschemadiff.presentation.cli.commands.diff import compare_urls
from pgschemadiff.shared.errors import DiffError, InspectionError, MigrationError, RiskGateError

if TYPE_CHECKING:
    from pathlib import Path


def _validate_generate_options(out_dir: Path, max_risk: RiskLevel) -> None:
    if max_risk is RiskLevel.BLOCKED:
        output.error(
            "Error: --max-risk blocked is not allowed; BLOCKED changes are never generated.",
            2,
        )
    if not out_dir.is_dir():
        output.error("Error: --out must be an existing directory.", 2)


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
        output.error(f"Error: Invalid renames file: {error}", 2)

    phase_steps = {
        "inspect-source": (1, "Inspecting source"),
        "inspect-target": (2, "Inspecting target"),
        "compare": (3, "Comparing"),
    }

    def on_phase(phase: str) -> None:
        step, label = phase_steps[phase]
        output.progress(step, 5, label)

    try:
        delta_set = asyncio.run(
            compare_urls(
                source_url,
                target_url,
                schemas,
                renames=renames,
                on_phase=on_phase,
            )
        )
    except (psycopg.Error, psycopg_pool.PoolTimeout):
        output.error("Error: Database connection failed.", 1)
    except InspectionError:
        output.error("Error: Schema inspection failed.", 1)
    except DiffError:
        output.error("Error: Schema comparison failed.", 1)
    except Exception:
        output.error("Error: Schema diff failed.", 1)

    if delta_set.is_empty():
        typer.echo("No schema changes.", err=True)
        return

    output.progress(4, 5, "Generating migration")
    try:
        plan = generate_migration(delta_set, max_risk=max_risk, slug=name)
    except RiskGateError as error:
        output.error(str(error), 2)
    except MigrationError as error:
        # Generation errors describe options and deltas only, never connections.
        output.error(f"Error: Migration generation failed: {error}", 1)
    except Exception:
        output.error("Error: Migration generation failed.", 1)

    output.progress(5, 5, "Writing bundle")
    try:
        bundle_path = FilesystemMigrationWriter().write(plan, out_dir)
    except Exception:
        output.error("Error: Migration bundle writing failed.", 1)

    typer.echo(str(bundle_path))
    counts: dict[RiskLevel, int] = dict.fromkeys(
        (level for level in RiskLevel if level is not RiskLevel.BLOCKED), 0
    )
    for record in plan.assessments:
        counts[record.assessment.level] += 1
    typer.echo(
        f"Generated migration: deltas={len(plan.delta_set)} "
        f"max-risk={plan.overall_max_risk} units={len(plan.units)} "
        f"(safe={counts[RiskLevel.SAFE]} warning={counts[RiskLevel.WARNING]} "
        f"dangerous={counts[RiskLevel.DANGEROUS]} "
        f"destructive={counts[RiskLevel.DESTRUCTIVE]})",
        err=True,
    )
