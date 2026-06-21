"""``pgsd inspect`` — implementation of the inspect command (task P1-CLI-01).

This module exposes ``inspect_cmd``, a plain Python callable that:

1. Constructs the infrastructure objects (``Pool`` + ``PgCatalogInspector``).
2. Calls the application use case ``inspect_schema``.
3. Prints the resulting JSON to stdout and exits non-zero on error.

The Typer parameter definitions live in ``presentation.cli.main`` so that
the ``@app.command`` decorator is not duplicated here.  This keeps the
composition root in one place.
"""

from __future__ import annotations

import asyncio
import sys

import psycopg
import psycopg_pool
import typer

from pgschemadiff.application.inspect.inspect_schema import inspect_schema
from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool
from pgschemadiff.shared.errors import InspectionError

# Timeout (seconds) for opening the connection pool.  A short value ensures
# that a bad/unreachable DSN fails quickly instead of hanging for ~30 s.
_POOL_OPEN_TIMEOUT: float = 5.0


def inspect_cmd(conn_url: str, schemas: list[str] | None) -> None:
    """Connect to *conn_url*, inspect the schema, and print JSON to stdout.

    Parameters
    ----------
    conn_url:
        A libpq connection URL, e.g. ``postgresql://user:pass@host/db``.
    schemas:
        Optional list of schema names to restrict introspection to.
        Pass ``None`` to inspect all user schemas.

    Raises
    ------
    typer.Exit
        With code 1 when an :class:`~pgschemadiff.shared.errors.InspectionError`
        is raised, or when the underlying connection cannot be established
        (``psycopg.OperationalError`` / ``psycopg_pool.PoolTimeout``), so the
        process terminates with a non-zero exit code.
    """

    async def _run() -> str:
        async with Pool(conn_url, open_timeout=_POOL_OPEN_TIMEOUT) as pool:
            inspector = PgCatalogInspector(pool, schemas=schemas or None)
            return await inspect_schema(inspector)

    try:
        json_output = asyncio.run(_run())
    except InspectionError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (psycopg.Error, psycopg_pool.PoolTimeout) as exc:
        # Pool.__aenter__ raises these when the DSN is unreachable or auth fails.
        # Wrap as InspectionError so callers see a consistent error type.
        inspection_exc = InspectionError(f"Connection failed: {exc}")
        inspection_exc.__cause__ = exc
        typer.echo(f"Error: {inspection_exc}", err=True)
        raise typer.Exit(code=1) from inspection_exc

    typer.echo(json_output, file=sys.stdout)
