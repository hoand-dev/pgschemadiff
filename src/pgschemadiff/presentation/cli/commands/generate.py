"""``pgsd generate`` command implementation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psycopg
import psycopg_pool
import typer

from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.infrastructure.config.rename_loader import load_renames
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.presentation.cli.commands.diff import compare_urls
from pgschemadiff.shared.errors import DiffError, InspectionError, MigrationError, RiskGateError

if TYPE_CHECKING:
    from pathlib import Path

    from pgschemadiff.application.sql_emit.risk import RiskLevel


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
    try:
        renames = load_renames(renames_path) if renames_path is not None else None
        delta_set = asyncio.run(compare_urls(source_url, target_url, schemas, renames=renames))
    except (psycopg.Error, psycopg_pool.PoolTimeout):
        typer.echo("Error: Database connection failed.", err=True)
        raise typer.Exit(code=1) from None
    except InspectionError:
        typer.echo("Error: Schema inspection failed.", err=True)
        raise typer.Exit(code=1) from None
    except DiffError:
        typer.echo("Error: Schema comparison failed.", err=True)
        raise typer.Exit(code=1) from None
    except Exception:
        typer.echo("Error: Schema diff failed.", err=True)
        raise typer.Exit(code=1) from None

    if delta_set.is_empty():
        typer.echo("No schema changes.", err=True)
        return

    try:
        plan = generate_migration(delta_set, max_risk=max_risk, slug=name)
    except RiskGateError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    except MigrationError as error:
        # Generation errors describe options and deltas only, never connections.
        typer.echo(f"Error: Migration generation failed: {error}", err=True)
        raise typer.Exit(code=1) from None
    except Exception:
        typer.echo("Error: Migration generation failed.", err=True)
        raise typer.Exit(code=1) from None

    try:
        bundle_path = FilesystemMigrationWriter().write(plan, out_dir)
    except Exception:
        typer.echo("Error: Migration bundle writing failed.", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(str(bundle_path))
    typer.echo(
        f"Generated migration: deltas={len(plan.delta_set)} "
        f"max-risk={plan.overall_max_risk} units={len(plan.units)}",
        err=True,
    )
