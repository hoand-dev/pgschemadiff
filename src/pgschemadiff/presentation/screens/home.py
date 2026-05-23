"""Home screen — profile list + detail pane."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListView, Static

from pgschemadiff.domain.models import Profile
from pgschemadiff.presentation.widgets.confirm_dialog import ConfirmDialog
from pgschemadiff.presentation.widgets.profile_item import ProfileListItem


class HomeScreen(Screen):
    BINDINGS = [
        Binding("n", "new_profile", "New", show=True),
        Binding("e", "edit_profile", "Edit", show=True),
        Binding("d", "delete_profile", "Delete", show=True),
        Binding("enter", "compare", "Compare", show=True, priority=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, profiles: list[Profile]) -> None:
        super().__init__()
        self._profiles = profiles

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="home-container"):
            with Vertical(id="profile-list-pane"):
                yield Static("PROFILES", id="profile-list-title")
                yield ListView(
                    *[ProfileListItem(p) for p in self._profiles],
                    id="profile-list",
                )
            with Vertical(id="detail-pane"):
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
        yield Footer()

    def on_mount(self) -> None:
        self.title = "pgschemadiff"
        self.sub_title = f"Home · {len(self._profiles)} profiles loaded"
        if self._profiles:
            self.query_one(ListView).focus()
            self.query_one(ListView).index = 0
            self._render_detail(self._profiles[0])
        else:
            self._render_detail(None)

    def _render_detail(self, profile: Profile | None) -> None:
        title = self.query_one("#detail-title", Static)
        if profile is None:
            title.update("No profile selected")
            for fid in ("field-source", "field-target", "field-schemas", "field-ignore", "field-mode"):
                self.query_one(f"#{fid}", Static).update(" ")
            return

        decor = "─" * max(0, 50 - len(profile.name))
        title.update(f"┌─ {profile.name} {decor}┐")
        self.query_one("#field-source", Static).update(
            f"[#6c7086]source [/]  [#f9e2af]{profile.source.display()}[/]"
        )
        self.query_one("#field-target", Static).update(
            f"[#6c7086]target [/]  [#f9e2af]{profile.target.display()}[/]"
        )
        self.query_one("#field-schemas", Static).update(
            f"[#6c7086]schemas[/]  [#cdd6f4]{', '.join(profile.schemas)}[/]"
        )
        ignore = ", ".join(profile.ignore_patterns) if profile.ignore_patterns else "(none)"
        self.query_one("#field-ignore", Static).update(
            f"[#6c7086]ignore [/]  [#cdd6f4]{ignore}[/]"
        )
        self.query_one("#field-mode", Static).update(
            f"[#6c7086]mode   [/]  [#cdd6f4]{profile.mode}[/]"
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, ProfileListItem):
            self._render_detail(event.item.profile)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ProfileListItem):
            self._start_compare(event.item.profile)

    def action_compare(self) -> None:
        lv = self.query_one(ListView)
        item = lv.highlighted_child
        if isinstance(item, ProfileListItem):
            self._start_compare(item.profile)

    def _start_compare(self, profile: Profile) -> None:
        from pgschemadiff.presentation.screens.comparing import ComparingScreen
        self.app.push_screen(ComparingScreen(profile))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-compare":
            self.action_compare()
        elif event.button.id == "btn-edit":
            self.action_edit_profile()

    def action_new_profile(self) -> None:
        self.notify("New profile dialog not wired yet", severity="warning")

    def action_edit_profile(self) -> None:
        item = self.query_one(ListView).highlighted_child
        if isinstance(item, ProfileListItem):
            self.notify(f"Edit: {item.profile.name}", severity="information")

    def action_delete_profile(self) -> None:
        lv = self.query_one(ListView)
        item = lv.highlighted_child
        if not isinstance(item, ProfileListItem):
            return

        profile = item.profile

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                idx = lv.index or 0
                self._profiles = [p for p in self._profiles if p.name != profile.name]
                lv.remove_items([idx])
                self.sub_title = f"Home · {len(self._profiles)} profiles loaded"
                if self._profiles:
                    new_idx = min(idx, len(self._profiles) - 1)
                    lv.index = new_idx
                    self._render_detail(self._profiles[new_idx])
                else:
                    self._render_detail(None)
                self.notify(f"Deleted profile: {profile.name}", severity="warning")

        self.app.push_screen(
            ConfirmDialog(
                title="Delete profile?",
                body=f"This will permanently delete '{profile.name}'.\nThis action cannot be undone.",
            ),
            on_confirm,
        )

    def action_help(self) -> None:
        self.notify(
            "↑↓ navigate · enter compare · n new · e edit · d delete · q quit",
            title="Key bindings",
            timeout=8,
        )
