"""Overview view (``go``) — stat grid, change table, AI review, dep graph."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.presentation.tui._mock import (
    AI_SUGGESTIONS,
    CHANGES,
    DEP_GRAPH,
    DIFFS,
    Change,
)
from pgschemadiff.presentation.tui.views._common import (
    AiRequested,
    DiffRequested,
    Panel,
    SectionHeader,
    op_colour,
    risk_colour,
)

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult


class _ChangeRow(Static):
    """A single clickable change row in the Overview table."""

    def __init__(self, change_id: str, obj: str, markup: str) -> None:
        super().__init__(markup, classes="change-row")
        self._change_id = change_id
        self._obj = obj

    @property
    def diff_key(self) -> str:
        return self._obj


class OverviewView(Widget):
    """Schema-change overview with a clickable change list."""

    DEFAULT_CSS = """
    OverviewView { height: 1fr; }
    OverviewView > VerticalScroll { height: 1fr; padding: 1 2; }
    OverviewView .stat-grid { height: auto; }
    OverviewView .stat {
        width: 1fr;
        height: auto;
        margin: 0 1 1 0;
        padding: 0 1;
        background: $surface;
        border: round $surface-lighten-1;
    }
    OverviewView .lower { height: auto; }
    OverviewView .changes { width: 2fr; margin-right: 1; }
    OverviewView .ai { width: 1fr; }
    OverviewView .change-row { padding: 0 1; }
    OverviewView .change-row:hover { background: $boost; }
    OverviewView .ai-card {
        height: auto;
        background: $boost;
        border-left: thick $primary;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    OverviewView .ai-card:hover { background: $surface-lighten-1; }
    """

    def compose(self) -> ComposeResult:
        crumb = "acme_prod → acme_staging · generated 14:22:08"
        yield SectionHeader("Overview", crumb)
        with VerticalScroll():
            with Horizontal(classes="stat-grid"):
                yield Static(
                    self._stat("added", "+4", "$success", "4 tbl · 5 idx · 2 type · 1 fn"),
                    classes="stat",
                )
                yield Static(
                    self._stat("modified", "~6", "$warning", "5 tbl · 2 fn · 1 type"),
                    classes="stat",
                )
                yield Static(
                    self._stat("dropped", "-2", "$error", "1 tbl · 2 cols — data loss"),
                    classes="stat",
                )
                yield Static(
                    self._stat("conflicts", "!1", "$warning", "1 index — needs resolution"),
                    classes="stat",
                )
            with Horizontal(classes="lower"):
                with Panel(f"Changes ({len(CHANGES)})", id="changes-panel", classes="changes"):
                    yield Static(self._table_header(), classes="change-head")
                    for c in CHANGES:
                        yield _ChangeRow(c.id, c.obj, self._row_markup(c))
                with Panel("AI review", subtitle=f"{len(AI_SUGGESTIONS)} hints", classes="ai"):
                    for i, s in enumerate(AI_SUGGESTIONS):
                        sev_colour = "$error" if s.severity == "high" else "$warning"
                        card = (
                            f"[$primary]✦ {escape(s.title)}[/]  "
                            f"[{sev_colour} on $boost] {s.severity} [/]\n"
                            f"[$text-muted]{escape(s.target)}[/]"
                        )
                        yield Static(card, classes="ai-card", id=f"ai-card-{i}")
            with Panel("Dependency graph", subtitle="topological order · 25 nodes"):
                yield Static(escape(DEP_GRAPH), classes="depgraph")

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _stat(label: str, value: str, colour: str, delta: str) -> str:
        return (
            f"[$text-muted]{label}[/]\n[{colour} bold]{value}[/]\n"
            f"[$text-muted dim]{escape(delta)}[/]"
        )

    @staticmethod
    def _table_header() -> str:
        return (
            f"[$text-muted bold]{'#':<5}{'op':<10}{'kind':<10}{'object':<34}{'detail':<30}risk[/]"
        )

    @staticmethod
    def _row_markup(c: Change) -> str:
        obj_colour = "$primary" if c.obj in DIFFS else "$text"
        detail = c.detail or "—"
        return (
            f"[$text-muted]{c.id:<5}[/]"
            f"[{op_colour(c.op)}]{c.op.lower():<10}[/]"
            f"[$text-muted]{c.kind.lower():<10}[/]"
            f"[{obj_colour}]{escape(c.obj):<34}[/]"
            f"[$text-muted]{escape(detail):<30}[/]"
            f"[{risk_colour(c.risk)}]{c.risk}[/]"
        )

    # ----------------------------------------------------------------- events

    def on_click(self, event: events.Click) -> None:
        node = event.widget
        if isinstance(node, _ChangeRow):
            if node.diff_key in DIFFS:
                self.post_message(DiffRequested(node.diff_key))
            return
        wid = getattr(node, "id", None) or ""
        if wid.startswith("ai-card-"):
            idx = int(wid.removeprefix("ai-card-"))
            self.post_message(AiRequested(AI_SUGGESTIONS[idx].target))
