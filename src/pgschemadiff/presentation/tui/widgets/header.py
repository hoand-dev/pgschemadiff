"""Top header strip — brand, mode badge, source→target pills."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from pgschemadiff.presentation.tui._mock import SOURCE, TARGET

if TYPE_CHECKING:
    from textual.app import ComposeResult


class HeaderBar(Widget):
    """The top header bar (brand, mode, connection pills)."""

    DEFAULT_CSS = """
    HeaderBar {
        height: 1;
        background: $surface;
        color: $text;
    }
    HeaderBar Horizontal { height: 1; }
    HeaderBar .brand { color: $primary; text-style: bold; padding: 0 1; }
    HeaderBar .mode { background: $success; color: $background; padding: 0 1; text-style: bold; }
    HeaderBar .mode.command { background: $warning; }
    HeaderBar .mode.insert { background: $accent 50%; }
    HeaderBar .pill { background: $boost; color: $text-muted; padding: 0 1; }
    HeaderBar .pill .src { color: $secondary; }
    HeaderBar .pill .tgt { color: $warning; }
    HeaderBar .right { padding: 0 1; color: $text-muted; }
    """

    mode: reactive[str] = reactive("normal")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("◈ pgschemadiff v0.0.0", classes="brand")
            yield Label(self.mode.upper(), id="mode-badge", classes="mode")
            yield Label(
                f"src → [b]{SOURCE.label}[/b] tgt → [b]{TARGET.label}[/b]",
                classes="pill",
            )
            yield Label("  branch [green]main[/green]  :cmd", classes="right")

    def watch_mode(self, mode: str) -> None:
        try:
            badge = self.query_one("#mode-badge", Label)
        except Exception:
            return
        badge.update(mode.upper())
        badge.set_class(mode == "command", "command")
        badge.set_class(mode == "insert", "insert")
