"""AI suggestion modal — opened from Overview / Diff / Migration actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from pgschemadiff.presentation.tui.views._common import sql_markup

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from pgschemadiff.presentation.tui._mock import AiSuggestion


class AiModal(ModalScreen[None]):
    """Shows one :class:`AiSuggestion` — title, rationale, proposed patch."""

    BINDINGS = [  # noqa: RUF012 — Textual types this as a mutable list
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    AiModal { align: center middle; }
    AiModal > Container {
        width: 80%;
        max-width: 90;
        height: 80%;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    AiModal .title { color: $primary; text-style: bold; padding: 0 0 1 0; }
    AiModal .meta { padding: 0 0 1 0; }
    AiModal .body {
        background: $panel;
        padding: 1;
        margin: 0 0 1 0;
        height: auto;
    }
    AiModal .patch-title { color: $text-muted; text-style: bold; padding: 1 0 0 0; }
    AiModal .patch { background: $panel; padding: 1; height: auto; }
    AiModal .foot { color: $text-muted; padding: 1 0 0 0; }
    """

    def __init__(self, suggestion: AiSuggestion) -> None:
        super().__init__()
        self._s = suggestion

    def compose(self) -> ComposeResult:
        s = self._s
        sev_colour = "$error" if s.severity == "high" else "$warning"
        with Container(), VerticalScroll():
            yield Static(f"AI suggestion · {escape(s.target)}", classes="title")
            yield Static(
                f"[$primary on $boost] ✦ claude-haiku-4-5 [/]  "
                f"[{sev_colour} on $boost] {s.severity} risk [/]  "
                f"[$text-muted on $boost] change {s.change} [/]",
                classes="meta",
            )
            yield Static(f"[$text bold]{escape(s.title)}[/]")
            yield Static("\n".join(escape(line) for line in s.body), classes="body")
            if s.patch:
                yield Static("Proposed patch", classes="patch-title")
                yield Static(
                    "\n".join(sql_markup(line) for line in s.patch.splitlines()),
                    classes="patch",
                )
            yield Static(
                f"[esc] dismiss   ·   [$success]{escape(s.accept_label)}[/]",
                classes="foot",
            )
