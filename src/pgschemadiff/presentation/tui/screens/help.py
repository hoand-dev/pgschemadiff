"""Vim-style ``?`` help modal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Navigation",
        (
            ("j / k", "down / up in lists"),
            ("h / l", "collapse / expand tree node"),
            ("gg / G", "top / bottom"),
            ("/", "search / filter"),
            ("Ctrl+b", "toggle sidebar"),
        ),
    ),
    (
        "Views",
        (
            ("gc", "Connection"),
            ("go", "Overview"),
            ("gd", "Diff detail"),
            ("gm", "Migration script"),
            ("ga", "Apply migration"),
            ("gh", "History"),
            ("gs", "Settings"),
        ),
    ),
    (
        "Actions",
        (
            (":", "command palette"),
            ("space a", "accept change"),
            ("space s", "skip change"),
            ("space i", "AI suggest"),
            ("gT", "cycle theme"),
            ("ZZ", "quit"),
        ),
    ),
    (
        "Commands ( : )",
        (
            (":diff <name>", "show diff for object"),
            (":apply [--dry-run]", "execute migration"),
            (":rollback <id>", "rollback past run"),
            (":set bg=mocha|latte", "theme"),
            (":conn switch <name>", "change source/target"),
        ),
    ),
)


class HelpScreen(ModalScreen[None]):
    """Modal listing every keybinding and command."""

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
            yield Static("Keyboard help — pgschemadiff", classes="title")
            for title, rows in _GROUPS:
                yield Static(f"── {title} ──", classes="group-title")
                for key, desc in rows:
                    yield Static(f"  [$warning]{key:<22}[/] [$text]{desc}[/]")
            yield Static("[esc] close", classes="foot")
