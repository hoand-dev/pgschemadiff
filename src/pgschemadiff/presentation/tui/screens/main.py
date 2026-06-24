"""Main composite screen: header / sidebar / tab body / statusbar / cmdbar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import ContentSwitcher, Input, Static, Tree

from pgschemadiff.presentation.tui._mock import CHANGE_SUMMARY, DIFFS, TREE, TreeNode
from pgschemadiff.presentation.tui.views import (
    ApplyView,
    ConnectionView,
    DiffView,
    HistoryView,
    MigrationView,
    OverviewView,
    SettingsView,
)
from pgschemadiff.presentation.tui.views._common import DiffRequested
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

_GLYPH = {"add": "+", "mod": "~", "del": "-", "conflict": "!"}
_KIND_ICON = {
    "schema": "◈",
    "group": "▾",
    "table": "▦",
    "view": "◫",
    "func": "ƒ",
    "index": "⌘",
    "trigger": "↯",
    "type": "τ",
}


def _badge(node: TreeNode) -> str:
    if not node.badge:
        return ""
    parts = [f"{_GLYPH[k]}{v}" for k, v in node.badge.items() if k in _GLYPH]
    return f"  [{', '.join(parts)}]" if parts else ""


def _label(node: TreeNode) -> str:
    icon = _KIND_ICON.get(node.kind, "·")
    suffix = f"  {_GLYPH[node.status]}" if node.status in _GLYPH else ""
    return f"{icon} {node.name}{suffix}{_badge(node)}"


def _build_tree(tree: Tree[str], nodes: tuple[TreeNode, ...]) -> None:
    tree.show_root = False
    tree.guide_depth = 2
    for schema in nodes:
        schema_node = tree.root.add(_label(schema), expand=schema.expanded, data=schema.name)
        for group in schema.children:
            group_node = schema_node.add(_label(group), expand=group.expanded, data="")
            for obj in group.children:
                key = f"{schema.name}.{obj.name}"
                group_node.add_leaf(_label(obj), data=key)


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
    MainScreen #sidebar.hidden { display: none; }
    MainScreen #sidebar .sb-head {
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        text-style: bold;
        border-bottom: solid $surface-lighten-1;
    }
    MainScreen #sidebar #sidebar-search {
        border: none;
        height: 1;
        background: $panel;
        margin: 0 1;
    }
    MainScreen #sidebar .sb-legend {
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        border-top: solid $surface-lighten-1;
    }
    MainScreen #sidebar Tree { background: $surface; height: 1fr; }
    MainScreen #main { width: 1fr; }
    MainScreen ContentSwitcher { height: 1fr; background: $background; }
    """

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="hdr")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("  SCHEMA EXPLORER", classes="sb-head")
                yield Input(placeholder="/ filter…", id="sidebar-search")
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
        _build_tree(tree, TREE)
        status = self.query_one("#status", Statusbar)
        s = CHANGE_SUMMARY
        status.change_count = sum(s.values())
        status.conflicts = s["conflict"]

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        key = event.node.data
        if key and key in DIFFS:
            self.post_message(DiffRequested(key))
