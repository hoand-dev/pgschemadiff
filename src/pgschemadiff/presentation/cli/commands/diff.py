"""``pgsd diff`` command implementation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psycopg
import psycopg_pool
import typer

from pgschemadiff.infrastructure.config.rename_loader import load_renames
from pgschemadiff.presentation import composition
from pgschemadiff.shared.errors import DiffError, InspectionError

if TYPE_CHECKING:
    from pathlib import Path

    from pgschemadiff.application.diff.renames import RenameAnnotations
    from pgschemadiff.domain.delta.base import DeltaSet


async def compare_urls(
    source_url: str,
    target_url: str,
    schemas: list[str] | None,
    *,
    renames: RenameAnnotations | None = None,
) -> DeltaSet:
    """Open both databases and compare their inspected schemas."""
    result = await composition.compare_conninfo(
        source_url,
        target_url,
        schemas,
        renames=renames,
    )
    return result.deltas


def diff_cmd(
    source_url: str,
    target_url: str,
    schemas: list[str] | None,
    renames_path: Path | None,
) -> None:
    """Compare two PostgreSQL databases and print typed schema deltas.

    Connection URLs and driver exception messages are never included in CLI
    output or logs.
    """

    try:
        rename_annotations = load_renames(renames_path) if renames_path is not None else None
        delta_set = asyncio.run(
            compare_urls(source_url, target_url, schemas, renames=rename_annotations)
        )
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

    typer.echo(delta_set.model_dump_json(indent=2))
