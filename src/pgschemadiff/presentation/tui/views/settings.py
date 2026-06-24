"""Settings view (``gs``) — preference groups + live config.toml preview."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.presentation.tui._mock import (
    CONFIG_TOML,
    SETTINGS_GROUPS,
    SettingField,
    SettingGroup,
)
from pgschemadiff.presentation.tui.views._common import Panel, SectionHeader

if TYPE_CHECKING:
    from textual.app import ComposeResult


def _field_markup(f: SettingField) -> str:
    if f.toggle:
        sw = "[$success]● on[/]" if f.on else "[$text-muted]○ off[/]"
        value = sw
    else:
        value = f"[$text]{escape(f.value)}[/]"
    line = f"[$text-muted]{f.label:<24}[/] {value}"
    if f.help:
        line += f"   [$text-muted dim]{escape(f.help)}[/]"
    return line


class SettingsView(Widget):
    """Grouped preferences with a read-only config.toml preview."""

    DEFAULT_CSS = """
    SettingsView { height: 1fr; }
    SettingsView > VerticalScroll { height: 1fr; padding: 1 2; }
    SettingsView .grid { height: auto; }
    SettingsView .grid .col { width: 1fr; }
    SettingsView .grid .col.left { margin-right: 1; }
    SettingsView .theme-row { padding: 0 1; }
    SettingsView .config { background: $panel; }
    """

    def compose(self) -> ComposeResult:
        yield SectionHeader("Settings", "~/.config/pgschemadiff/config.toml")
        with VerticalScroll():
            yield Static(self._theme_picker(), classes="theme-row")
            groups = list(SETTINGS_GROUPS)
            with Horizontal(classes="grid"):
                with VerticalScroll(classes="col left"):
                    for g in groups[0::2]:
                        yield from self._group_panel(g)
                with VerticalScroll(classes="col"):
                    for g in groups[1::2]:
                        yield from self._group_panel(g)
            with Panel("config.toml", subtitle="preview · read-only"):
                yield Static(escape(CONFIG_TOML), classes="config")

    @staticmethod
    def _group_panel(group: SettingGroup) -> ComposeResult:
        with Panel(group.title, subtitle=group.badge):
            for f in group.fields:
                yield Static(_field_markup(f))

    def _theme_picker(self) -> str:
        current = "latte" if self.app.theme == "catppuccin-latte" else "mocha"
        mocha_on = "$primary bold" if current == "mocha" else "$text-muted"
        latte_on = "$primary bold" if current == "latte" else "$text-muted"
        mocha = f"[{mocha_on}]◐ Catppuccin Mocha[/]"
        latte = f"[{latte_on}]◑ Catppuccin Latte[/]"
        return f"[$text-muted]theme:[/]  {mocha}    {latte}    [$text-muted dim](gT toggle)[/]"
