"""``pgsd`` CLI entry point.

The ``inspect``, ``diff``, ``generate``, and ``apply`` sub-commands handle
database operations. ``pgsd tui`` (and ``pgsd`` with no sub-command) launches
the interactive Textual TUI implemented in ``pgschemadiff.presentation.tui``.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves Path at runtime
from typing import Literal

import typer

from pgschemadiff import __version__
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.presentation.cli.commands.apply import apply_cmd
from pgschemadiff.presentation.cli.commands.diff import diff_cmd
from pgschemadiff.presentation.cli.commands.generate import generate_cmd
from pgschemadiff.presentation.cli.commands.inspect import inspect_cmd
from pgschemadiff.presentation.cli.commands.report import report_cmd
from pgschemadiff.presentation.cli.commands.tui import launch as launch_tui
from pgschemadiff.shared.logging import configure_logging

app = typer.Typer(
    name="pgsd",
    help="Compare PostgreSQL schemas, generate safe migrations.",
    epilog=(
        "Exit codes:\n\n"
        "  0  Success (including diff with changes and no gate)\n\n"
        "  1  Runtime failure (connection, inspection, comparison, writing)\n\n"
        "  2  Usage or policy failure (bad option/file, risk gate, invalid bundle, "
        "unapproved destructive or BLOCKED bundle)\n\n"
        "  3  Apply failed or cancelled after it started"
    ),
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
    output_format: Literal["json", "summary", "html"] = typer.Option(
        "json",
        "--format",
        help="Diff output format (json, summary, or html).",
    ),
    max_risk: RiskLevel | None = typer.Option(  # noqa: B008
        None,
        "--max-risk",
        help="Fail if any change exceeds this risk level.",
    ),
) -> None:
    """Compare two PostgreSQL databases and print schema changes."""
    diff_cmd(
        source_url=source_url,
        target_url=target_url,
        schemas=schemas,
        renames_path=renames,
        output_format=output_format,
        max_risk=max_risk,
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


@app.command("report")
def report(
    bundle_dir: Path = typer.Argument(  # noqa: B008
        ...,
        metavar="BUNDLE_DIR",
        help="Directory containing a validated migration bundle.",
    ),
    out_file: Path | None = typer.Option(  # noqa: B008
        None,
        "--out",
        help="Write the HTML report to a new file instead of stdout.",
    ),
) -> None:
    """Render a saved migration bundle as an offline HTML report."""
    report_cmd(bundle_dir, out_file)


@app.command("apply")
def apply(
    bundle_dir: Path = typer.Argument(  # noqa: B008
        ...,
        metavar="BUNDLE_DIR",
        help="Directory containing manifest.json and up.sql.",
    ),
    db_url: str = typer.Argument(
        ...,
        metavar="DB_URL",
        help="Target PostgreSQL connection URL.",
    ),
    lock_timeout: str = typer.Option(
        "5s",
        "--lock-timeout",
        help="Maximum time to wait for the migration lock (0, ms, s, or min).",
    ),
    statement_timeout: str = typer.Option(
        "0",
        "--statement-timeout",
        help="Maximum statement execution time (0, ms, s, or min).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and check connectivity only.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Approve destructive migration units.",
    ),
    skip_source_check: bool = typer.Option(
        False,
        "--skip-source-check",
        help="Skip verification that the database matches the bundle source state.",
    ),
) -> None:
    """Apply a migration bundle after validation and risk confirmation."""
    apply_cmd(
        bundle_dir,
        db_url,
        lock_timeout=lock_timeout,
        statement_timeout=statement_timeout,
        dry_run=dry_run,
        yes=yes,
        skip_source_check=skip_source_check,
    )


@app.command("tui")
def tui_cmd() -> None:
    """Launch the interactive TUI."""
    launch_tui()


if __name__ == "__main__":  # pragma: no cover
    app()
