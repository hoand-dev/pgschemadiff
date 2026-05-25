"""Vim-style modeline at the bottom of the screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class Statusbar(Widget):
    """Single-line status bar matching the vim modeline aesthetic."""

    DEFAULT_CSS = """
    Statusbar {
        height: 1;
        background: $primary;
        color: $background;
        text-style: bold;
    }
    Statusbar Horizontal { height: 1; }
    Statusbar Label { padding: 0 1; }
    Statusbar .pill { background: $primary-darken-2; color: $background; }
    Statusbar .right { dock: right; }
    """

    mode: reactive[str] = reactive("normal")
    view: reactive[str] = reactive("overview")
    selected: reactive[str] = reactive("—")
    change_count: reactive[int] = reactive(0)
    conflicts: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("NORMAL", id="sb-mode", classes="pill")
            yield Label("pgschemadiff/overview", id="sb-path")
            yield Label("—", id="sb-selected")
            yield Label("0c", id="sb-counts", classes="pill right")

    def _refresh(self) -> None:
        try:
            self.query_one("#sb-mode", Label).update(self.mode.upper())
            self.query_one("#sb-path", Label).update(f"pgschemadiff/{self.view}")
            self.query_one("#sb-selected", Label).update(self.selected)
            label = f"{self.change_count}c"
            if self.conflicts:
                label = f"⚠ {self.conflicts} conflict · " + label
            self.query_one("#sb-counts", Label).update(label)
        except Exception:
            return

    def watch_mode(self, _: str) -> None:
        self._refresh()

    def watch_view(self, _: str) -> None:
        self._refresh()

    def watch_selected(self, _: str) -> None:
        self._refresh()

    def watch_change_count(self, _: int) -> None:
        self._refresh()

    def watch_conflicts(self, _: int) -> None:
        self._refresh()
