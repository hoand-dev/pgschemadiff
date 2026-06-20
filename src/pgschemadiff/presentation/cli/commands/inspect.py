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

import typer

from pgschemadiff.application.inspect.inspect_schema import inspect_schema
from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool
from pgschemadiff.shared.errors import InspectionError


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
        is raised so the process terminates with a non-zero exit code.
    """

    async def _run() -> str:
        async with Pool(conn_url) as pool:
            inspector = PgCatalogInspector(pool, schemas=schemas or None)
            return await inspect_schema(inspector)

    try:
        json_output = asyncio.run(_run())
    except InspectionError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(json_output, file=sys.stdout)
