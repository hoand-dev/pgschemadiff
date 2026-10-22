"""``pgsd diff`` command implementation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psycopg
import psycopg_pool
import typer

from pgschemadiff.application.diff.compare_schemas import compare_schemas
from pgschemadiff.infrastructure.config.rename_loader import load_renames
from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool
from pgschemadiff.shared.errors import DiffError, InspectionError

if TYPE_CHECKING:
    from pathlib import Path

    from pgschemadiff.application.diff.renames import RenameAnnotations
    from pgschemadiff.domain.delta.base import DeltaSet

_POOL_OPEN_TIMEOUT: float = 5.0


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

    async def _run(renames: RenameAnnotations | None) -> DeltaSet:
        async with Pool(source_url, open_timeout=_POOL_OPEN_TIMEOUT) as source_pool:
            source_inspector = PgCatalogInspector(source_pool, schemas=schemas)
            async with Pool(target_url, open_timeout=_POOL_OPEN_TIMEOUT) as target_pool:
                target_inspector = PgCatalogInspector(target_pool, schemas=schemas)
                return await compare_schemas(
                    source_inspector,
                    target_inspector,
                    renames=renames,
                )

    try:
        rename_annotations = load_renames(renames_path) if renames_path is not None else None
        delta_set = asyncio.run(_run(rename_annotations))
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
