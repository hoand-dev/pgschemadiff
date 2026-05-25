"""Main composite screen: header / sidebar / tab body / statusbar / cmdbar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import ContentSwitcher, Static, Tree

from pgschemadiff.presentation.tui._mock import CHANGE_SUMMARY
from pgschemadiff.presentation.tui.views import (
    ApplyView,
    ConnectionView,
    DiffView,
    HistoryView,
    MigrationView,
    OverviewView,
    SettingsView,
)
from pgschemadiff.presentation.tui.widgets import (
    Cmdbar,
    HeaderBar,
    Statusbar,
    TabSpec,
    ViewTabs,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

TAB_SPECS: tuple[TabSpec, ...] = (
    TabSpec("connection", "Connection", "gc"),
    TabSpec("overview", "Overview", "go"),
    TabSpec("diff", "Diff", "gd"),
    TabSpec("migration", "Migration", "gm"),
    TabSpec("apply", "Apply", "ga"),
    TabSpec("history", "History", "gh"),
    TabSpec("settings", "Settings", "gs"),
)


def _build_demo_tree(tree: Tree[str]) -> None:
    """Populate the sidebar with a small slice of the mock schema."""
    tree.show_root = False
    root = tree.root
    s = CHANGE_SUMMARY
    public = root.add(
        f"◈ public  [+{s['add']} ~{s['mod']} -{s['del']} !{s['conflict']}]",
        expand=True,
    )
    tables = public.add("▾ tables", expand=True)
    tables.add_leaf("▦ tenants  ~")
    tables.add_leaf("▦ users  ~")
    tables.add_leaf("▦ task_subscriptions  +")
    tables.add_leaf("▦ legacy_invites  -")
    indexes = public.add("▾ indexes")
    indexes.add_leaf("⌘ idx_tasks_due_date  +")
    indexes.add_leaf("⌘ idx_users_email  !")
    public.add("▸ functions")
    public.add("▸ views")
    root.add("◈ billing  [~2]")
    root.add("◈ analytics  [+1]")


class MainScreen(Screen[None]):
    """Top-level screen — composes the entire pgsd chrome."""

    DEFAULT_CSS = """
    MainScreen { layout: vertical; }
    MainScreen > #body {
        height: 1fr;
        layout: horizontal;
    }
    MainScreen #sidebar {
        width: 36;
        background: $surface;
        border-right: solid $surface-lighten-1;
    }
    MainScreen #sidebar .sb-head {
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        text-style: bold;
        border-bottom: solid $surface-lighten-1;
    }
    MainScreen #sidebar .sb-legend {
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        border-top: solid $surface-lighten-1;
    }
    MainScreen #sidebar Tree { background: $surface; }
    MainScreen #main { width: 1fr; }
    MainScreen ContentSwitcher { height: 1fr; background: $background; }
    """

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="hdr")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("  SCHEMA EXPLORER", classes="sb-head")
                yield Tree("schemas", id="schema-tree")
                yield Static(
                    "legend: [$success]+[/] add  [$warning]~[/] mod  "
                    "[$error]-[/] del  [$warning]![/] conflict",
                    classes="sb-legend",
                )
            with Vertical(id="main"):
                yield ViewTabs(TAB_SPECS, initial="overview")
                with ContentSwitcher(initial="overview", id="content"):
                    yield ConnectionView(id="connection")
                    yield OverviewView(id="overview")
                    yield DiffView(id="diff")
                    yield MigrationView(id="migration")
                    yield ApplyView(id="apply")
                    yield HistoryView(id="history")
                    yield SettingsView(id="settings")
        yield Statusbar(id="status")
        yield Cmdbar(id="cmd")

    def on_mount(self) -> None:
        tree = self.query_one("#schema-tree", Tree)
        _build_demo_tree(tree)
        status = self.query_one("#status", Statusbar)
        s = CHANGE_SUMMARY
        status.change_count = sum(s.values())
        status.conflicts = s["conflict"]
