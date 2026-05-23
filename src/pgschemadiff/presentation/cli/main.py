"""``pgsd`` CLI entry point.

Phase 0 stub — sub-commands (``inspect``, ``diff``, ``generate``, ``apply``)
are added in later phases. For now ``pgsd --version`` and ``pgsd --help`` work.
"""

from __future__ import annotations

import typer

from pgschemadiff import __version__
from pgschemadiff.shared.logging import configure_logging

app = typer.Typer(
    name="pgsd",
    help="Compare PostgreSQL schemas, generate safe migrations.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pgschemadiff {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    *,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        envvar="PGSD_LOG_LEVEL",
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    ),
) -> None:
    """Configure logging once for all sub-commands."""
    _ = version
    configure_logging(level=log_level)


if __name__ == "__main__":  # pragma: no cover
    app()
