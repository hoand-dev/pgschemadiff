"""Detail panel for the currently selected profile."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Static

from pgschemadiff.domain.models import Profile


class ProfileDetail(Container):
    """Renders profile fields + action buttons. Unused — logic is inlined in HomeScreen."""

    def __init__(self, profile: Profile | None = None) -> None:
        super().__init__(id="detail-pane")
        self._profile = profile

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("loading...", id="detail-title")
            yield Static("loading...", id="field-source", classes="field-row")
            yield Static("loading...", id="field-target", classes="field-row")
            yield Static("loading...", id="field-schemas", classes="field-row")
            yield Static("loading...", id="field-ignore", classes="field-row")
            yield Static("loading...", id="field-mode", classes="field-row")
            with Horizontal(id="detail-actions"):
                yield Button("Compare", id="btn-compare", classes="-primary")
                yield Button("Edit", id="btn-edit")
                yield Button("Test connection", id="btn-test")

    def on_mount(self) -> None:
        self._render()

    def set_profile(self, profile: Profile | None) -> None:
        self._profile = profile
        self._render()

    def _render(self) -> None:
        title = self.query_one("#detail-title", Static)
        if self._profile is None:
            title.update("No profile selected")
            for fid in ("field-source", "field-target", "field-schemas", "field-ignore", "field-mode"):
                self.query_one(f"#{fid}", Static).update(" ")
            return

        p = self._profile
        decor = "─" * max(0, 50 - len(p.name))
        title.update(f"┌─ {p.name} {decor}┐")
        self.query_one("#field-source", Static).update(
            f"[#6c7086]source [/]  [#f9e2af]{p.source.display()}[/]"
        )
        self.query_one("#field-target", Static).update(
            f"[#6c7086]target [/]  [#f9e2af]{p.target.display()}[/]"
        )
        self.query_one("#field-schemas", Static).update(
            f"[#6c7086]schemas[/]  [#cdd6f4]{', '.join(p.schemas)}[/]"
        )
        ignore = ", ".join(p.ignore_patterns) if p.ignore_patterns else "(none)"
        self.query_one("#field-ignore", Static).update(
            f"[#6c7086]ignore [/]  [#cdd6f4]{ignore}[/]"
        )
        self.query_one("#field-mode", Static).update(
            f"[#6c7086]mode   [/]  [#cdd6f4]{p.mode}[/]"
        )
