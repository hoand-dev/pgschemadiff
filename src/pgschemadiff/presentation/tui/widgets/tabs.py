"""Custom tab bar — labelled tabs with chord-key hint chips.

Textual's built-in :class:`textual.widgets.Tabs` doesn't render the ``gc`` /
``go`` chord hints from the design, so we roll a thin wrapper around a
``ContentSwitcher`` and a row of :class:`Label`-style buttons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult


@dataclass(frozen=True)
class TabSpec:
    """One entry in the tab bar."""

    view_id: str
    label: str
    chord: str  # e.g. "gc", "go"


class TabActivated(Message):
    """Emitted when the user clicks (or programmatically activates) a tab."""

    def __init__(self, view_id: str) -> None:
        super().__init__()
        self.view_id = view_id


class ViewTabs(Widget):
    """Horizontal tab bar driven by a tuple of :class:`TabSpec` entries."""

    DEFAULT_CSS = """
    ViewTabs { height: 1; background: $surface; }
    ViewTabs Horizontal { height: 1; }
    ViewTabs Static.tab {
        padding: 0 2;
        color: $text-muted;
        border-right: solid $surface-lighten-1;
    }
    ViewTabs Static.tab:hover { background: $boost; color: $text; }
    ViewTabs Static.tab.active {
        background: $background;
        color: $text;
        text-style: bold;
        border-bottom: heavy $primary;
    }
    ViewTabs Static.tab .chord { color: $text-muted 50%; }
    """

    active: reactive[str] = reactive("overview")

    def __init__(self, tabs: tuple[TabSpec, ...], *, initial: str = "overview") -> None:
        super().__init__()
        self._tabs = tabs
        self.active = initial

    def compose(self) -> ComposeResult:
        with Horizontal():
            for tab in self._tabs:
                cls = "tab" + (" active" if tab.view_id == self.active else "")
                yield Static(
                    f"{tab.label}  [dim]{tab.chord}[/dim]",
                    id=f"tab-{tab.view_id}",
                    classes=cls,
                )

    def watch_active(self, view_id: str) -> None:
        for tab in self._tabs:
            try:
                widget = self.query_one(f"#tab-{tab.view_id}", Static)
            except Exception:
                continue
            widget.set_class(tab.view_id == view_id, "active")

    def on_click(self, event: events.Click) -> None:
        widget = getattr(event, "widget", None)
        if not isinstance(widget, Static):
            return
        target_id = widget.id or ""
        if target_id.startswith("tab-"):
            self.post_message(TabActivated(view_id=target_id.removeprefix("tab-")))
