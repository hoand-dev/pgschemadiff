"""``pgsd`` CLI entry point.

Phase 0 stub — ``inspect``, ``diff``, ``generate``, ``apply`` sub-commands
arrive in later phases.  ``pgsd tui`` (and ``pgsd`` with no sub-command)
launches the interactive Textual TUI implemented in
``pgschemadiff.presentation.tui``.
"""

from __future__ import annotations

import typer

from pgschemadiff import __version__
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


@app.command("tui")
def tui_cmd() -> None:
    """Launch the interactive TUI."""
    launch_tui()


if __name__ == "__main__":  # pragma: no cover
    app()
