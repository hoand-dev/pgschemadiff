"""Vim-style modeline at the bottom of the screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from pgschemadiff.application.migration.generate import assess_deltas
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.presentation.tui.views._common import markup

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult


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
    blocked_count: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("NORMAL", id="sb-mode", classes="pill")
            yield Label("pgschemadiff/overview", id="sb-path")
            yield Label("—", id="sb-selected")
            yield Label("0 changes", id="sb-counts", classes="pill right")

    def update_selected(self, selected: str | None) -> None:
        """Set the selected tree node label, or clear selection."""
        self.selected = selected or "—"

    def update_comparison(self, comparison: SchemaComparisonResult | None) -> None:
        """Derive change and blocked counts from the current typed deltas."""
        if comparison is None:
            self.change_count = 0
            self.blocked_count = 0
            return
        self.change_count = len(comparison.deltas)
        self.blocked_count = sum(
            assessment.level is RiskLevel.BLOCKED
            for _delta_id, assessment in assess_deltas(comparison.deltas)
        )

    def _refresh(self) -> None:
        try:
            self.query_one("#sb-mode", Label).update(self.mode.upper())
            self.query_one("#sb-path", Label).update(f"pgschemadiff/{self.view}")
            self.query_one("#sb-selected", Label).update(
                markup("$selected", selected=self.selected)
            )
            label = f"{self.change_count} changes"
            if self.blocked_count:
                label = f"{self.blocked_count} blocked · {label}"
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

    def watch_blocked_count(self, _: int) -> None:
        self._refresh()
