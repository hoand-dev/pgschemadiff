"""Shared plain-text and terminal styling for CLI output."""

from __future__ import annotations

from typing import NoReturn

import typer
from rich.console import Console
from rich.text import Text

from pgschemadiff.application.sql_emit.risk import RiskLevel


def stderr_console() -> Console:
    """Create a stderr console with markup and highlighting disabled."""
    return Console(stderr=True, markup=False, highlight=False, emoji=False, soft_wrap=True)


def error(message: str, code: int) -> NoReturn:
    """Print an error to stderr and exit with its stable code."""
    console = stderr_console()
    console.print(Text(message, style="red") if console.is_terminal else message)
    raise typer.Exit(code=code)


def warn(message: str) -> None:
    """Print a warning to stderr, yellow when stderr is a terminal."""
    console = stderr_console()
    console.print(Text(message, style="yellow") if console.is_terminal else message)


def progress(step: int, total: int, label: str) -> None:
    """Print one quiet progress line only when stderr is a terminal."""
    console = stderr_console()
    if console.is_terminal:
        console.print(Text(f"[{step}/{total}] {label}", style="dim"))


def risk_text(level: RiskLevel | None) -> Text:
    """Return a styled risk name for human-readable output."""
    if level is None:
        return Text("none")
    styles = {
        RiskLevel.SAFE: "green",
        RiskLevel.WARNING: "yellow",
        RiskLevel.DANGEROUS: "magenta",
        RiskLevel.DESTRUCTIVE: "red",
        RiskLevel.BLOCKED: "bold red",
    }
    return Text(level.value, style=styles[level])
