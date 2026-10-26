"""``pgsd tui`` — launch the interactive Textual TUI."""

from __future__ import annotations

import typer

from pgschemadiff.presentation.composition import create_tui_dependencies
from pgschemadiff.presentation.tui import PgsdApp

tui_command = typer.Typer(help="Launch the interactive TUI.")


def launch() -> None:
    """Instantiate :class:`PgsdApp` and hand control to Textual's event loop."""
    PgsdApp(dependencies=create_tui_dependencies()).run()
