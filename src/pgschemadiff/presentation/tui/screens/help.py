"""Vim-style ``?`` help modal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from pgschemadiff.presentation.tui.views._common import markup

if TYPE_CHECKING:
    from textual.app import ComposeResult

_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Commands",
        (
            (":o/:overview", "open Overview"),
            (":d/:diff [qualified-name]", "select matching delta"),
            (":m/:migration", "open Migration"),
            (":a/:apply [--dry-run]", "open Apply; --dry-run starts check"),
            (":h/:history", "open History"),
            (":c/:conn/:connection", "open Connection"),
            (":conn switch <profile>", "select profile by name"),
            (":rollback <id>", "select run; rollback unavailable"),
            (":set bg=mocha|latte", "set theme"),
            (":s/:settings", "open Settings"),
            (":help/?", "show this help"),
            (":q/:quit", "quit"),
        ),
    ),
)


class HelpScreen(ModalScreen[None]):
    """Modal listing the supported palette commands."""

    BINDINGS = [  # noqa: RUF012 — Textual's base class types this as a mutable list
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("?", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > Container {
        background: $surface;
        border: solid $primary;
        padding: 1 2;
        width: 80%;
        height: 80%;
        max-width: 100;
    }
    HelpScreen .title { color: $primary; text-style: bold; padding: 0 0 1 0; }
    HelpScreen .group-title {
        color: $text-muted;
        text-style: bold;
        padding: 1 0 0 0;
    }
    HelpScreen .kb { color: $warning; text-style: bold; }
    HelpScreen .desc { color: $text; }
    HelpScreen .foot { color: $text-muted; padding: 1 0 0 0; }
    """

    def compose(self) -> ComposeResult:
        with Container(), Vertical():
            yield Static("Command palette — pgschemadiff", classes="title")
            for title, rows in _GROUPS:
                yield Static(f"── {title} ──", classes="group-title")
                for key, desc in rows:
                    yield Static(markup("  [$warning]$key[/] [$text]$desc[/]", key=key, desc=desc))
