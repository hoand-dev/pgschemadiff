"""``pgsd`` CLI entry point.

The ``inspect``, ``diff``, and ``generate`` sub-commands handle database
operations. ``pgsd apply`` arrives in a later phase. ``pgsd tui`` (and
``pgsd`` with no sub-command) launches the interactive Textual TUI implemented
in ``pgschemadiff.presentation.tui``.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves Path at runtime

import typer

from pgschemadiff import __version__
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.presentation.cli.commands.diff import diff_cmd
from pgschemadiff.presentation.cli.commands.generate import generate_cmd
from pgschemadiff.presentation.cli.commands.inspect import inspect_cmd
from pgschemadiff.presentation.cli.commands.tui import launch as launch_tui
from pgschemadiff.shared.logging import configure_logging

app = typer.Typer(
    name="pgsd",
    help="Compare PostgreSQL schemas, generate safe migrations.",
    invoke_without_command=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pgschemadiff {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
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
    """Configure logging once and launch the TUI if no sub-command is given."""
    _ = version
    configure_logging(level=log_level)
    if ctx.invoked_subcommand is None:
        launch_tui()


@app.command("inspect")
def inspect(
    conn_url: str = typer.Argument(
        ...,
        metavar="<conn-url>",
        help="PostgreSQL connection URL.",
    ),
    schemas: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--schema",
        "-s",
        help="Schema(s) to inspect (repeatable).  Default: all user schemas.",
    ),
) -> None:
    """Inspect a PostgreSQL database and print its schema as JSON to stdout."""
    inspect_cmd(conn_url=conn_url, schemas=schemas)


@app.command("diff")
def diff(
    source_url: str = typer.Argument(..., help="Source PostgreSQL connection URL."),
    target_url: str = typer.Argument(..., help="Target PostgreSQL connection URL."),
    schemas: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--schema",
        "-s",
        help="Schema(s) to inspect (repeatable). Default: all user schemas.",
    ),
    renames: Path | None = typer.Option(  # noqa: B008
        None,
        "--renames",
        help="YAML or TOML file with explicit rename annotations.",
    ),
) -> None:
    """Compare two PostgreSQL databases and print schema changes as JSON."""
    diff_cmd(
        source_url=source_url,
        target_url=target_url,
        schemas=schemas,
        renames_path=renames,
    )


@app.command("generate")
def generate(
    source_url: str = typer.Argument(..., help="Source PostgreSQL connection URL."),
    target_url: str = typer.Argument(..., help="Target PostgreSQL connection URL."),
    out_dir: Path = typer.Option(  # noqa: B008
        ...,
        "--out",
        help="Existing directory in which to write the migration bundle.",
    ),
    schemas: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--schema",
        "-s",
        help="Schema(s) to inspect (repeatable). Default: all user schemas.",
    ),
    renames: Path | None = typer.Option(  # noqa: B008
        None,
        "--renames",
        help="YAML or TOML file with explicit rename annotations.",
    ),
    max_risk: RiskLevel = typer.Option(  # noqa: B008
        RiskLevel.DANGEROUS,
        "--max-risk",
        help="Maximum allowed migration risk.",
    ),
    name: str = typer.Option("diff", "--name", help="Migration bundle slug."),
) -> None:
    """Generate and write a risk-gated migration bundle."""
    generate_cmd(
        source_url=source_url,
        target_url=target_url,
        out_dir=out_dir,
        schemas=schemas,
        renames_path=renames,
        max_risk=max_risk,
        name=name,
    )


@app.command("tui")
def tui_cmd() -> None:
    """Launch the interactive TUI."""
    launch_tui()


if __name__ == "__main__":  # pragma: no cover
    app()
