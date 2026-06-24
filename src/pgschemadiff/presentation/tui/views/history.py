"""History view (``gh``) — past runs list + run detail + timeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.presentation.tui._mock import HISTORY, HistoryEntry
from pgschemadiff.presentation.tui.views._common import Panel, SectionHeader

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult

_STATUS = {
    "applied": ("● applied", "$success"),
    "applied (dry)": ("○ dry-run", "$secondary"),
    "pending": ("◐ pending", "$warning"),
    "failed": ("✗ failed", "$error"),
    "rolled-back": ("↶ rolled back", "$primary"),
}


def _status_markup(status: str) -> str:
    text, colour = _STATUS.get(status, (status, "$text-muted"))
    return f"[{colour}]{text}[/]"


class _RunRow(Static):
    def __init__(self, run_id: str, markup: str, *, selected: bool) -> None:
        cls = "run-row selected" if selected else "run-row"
        super().__init__(markup, classes=cls)
        self.run_id = run_id


class HistoryView(Widget):
    """Reverse-chronological run list with a detail/timeline drill-down."""

    selected_id: reactive[str] = reactive(HISTORY[1].id, recompose=True)

    DEFAULT_CSS = """
    HistoryView { height: 1fr; }
    HistoryView > VerticalScroll { height: 1fr; padding: 1 2; }
    HistoryView .run-row { padding: 0 1; height: 1; }
    HistoryView .run-row:hover { background: $boost; }
    HistoryView .run-row.selected { background: $primary 25%; }
    HistoryView .detail-cols { height: auto; }
    HistoryView .detail-cols .detail { width: 1fr; margin-right: 1; }
    HistoryView .detail-cols .timeline { width: 1fr; }
    """

    def _entry(self) -> HistoryEntry:
        for h in HISTORY:
            if h.id == self.selected_id:
                return h
        return HISTORY[0]

    def compose(self) -> ComposeResult:
        yield SectionHeader("History", f"~/.pgsd/state/runs.db · {len(HISTORY)} runs")
        with VerticalScroll():
            with Panel("Runs"):
                yield Static(
                    f"[$text-muted bold]{'id':<7}{'when':<21}{'route':<28}"
                    f"{'author':<13}{'chg':<5}{'dur':<8}status[/]"
                )
                for h in HISTORY:
                    yield _RunRow(h.id, self._row_markup(h), selected=h.id == self.selected_id)
            with Horizontal(classes="detail-cols"):
                row = self._entry()
                with Panel(f"Run detail · {row.id}", classes="detail"):
                    yield Static(self._detail_markup(row))
                with Panel("Timeline", classes="timeline"):
                    yield Static(self._timeline_markup(row))

    @staticmethod
    def _row_markup(h: HistoryEntry) -> str:
        route = f"{h.src} → {h.tgt}"
        return (
            f"[$text-muted]{h.id:<7}{h.when:<21}[/]"
            f"[$secondary]{escape(route):<28}[/]"
            f"[$text]{h.author:<13}[/][$text-muted]{h.changes:<5}{h.duration:<8}[/]"
            f"{_status_markup(h.status)}"
        )

    @staticmethod
    def _detail_markup(h: HistoryEntry) -> str:
        rollback = "available ✓" if h.status == "applied" else "—"
        rows = (
            ("when", h.when),
            ("source", h.src),
            ("target", h.tgt),
            ("author", h.author),
            ("changes", f"{h.changes} (4 add · 6 mod · 2 del · 1 conflict)"),
            ("duration", h.duration),
            ("status", h.status),
            ("checksum", "sha256:b71f6a91…ce4a"),
            ("snapshot", f"db-stage_{h.id}.dump (8.2 GB)"),
            ("rollback", rollback),
        )
        return "\n".join(f"[$text-muted]{k:<10}[/] [$text]{escape(str(v))}[/]" for k, v in rows)

    @staticmethod
    def _timeline_markup(h: HistoryEntry) -> str:
        day = h.when[:10]
        info = r"[$secondary]\[info][/]"
        ok = r"[$success]\[ ok ][/]"
        warn = r"[$warning]\[warn][/]"
        lines = (
            rf"[$text-muted]{day} 10:31:42[/] {info} pgsd v0.4.2 · {h.author}",
            rf"[$text-muted]{day} 10:31:43[/] {info} diff {h.src} → {h.tgt} → {h.changes} changes",
            rf"[$text-muted]{day} 10:31:50[/] {info} snapshot taken (8.2 GB)",
            rf"[$text-muted]{day} 10:31:51[/] {info} BEGIN;",
            rf"[$text-muted]{day} 10:31:51[/] {ok} \[c01] CREATE TYPE · 0.31s",
            rf"[$text-muted]{day} 10:31:52[/] {ok} \[c04] ALTER tenants · 0.42s",
            rf"[$text-muted]{day} 10:33:10[/] {warn} \[c05] users email rewrite ~78s",
            rf"[$text-muted]{day} 10:33:11[/] {ok} \[c05] complete · 38,214,902 rows",
            rf"[$text-muted]{day} 10:33:14[/] {ok} CREATE INDEX CONCURRENTLY (x5)",
            rf"[$text-muted]{day} 10:33:24[/] {ok} COMMIT; · checksum verified",
            "[$text-muted dim]— end of run —[/]",
        )
        return "\n".join(lines)

    # ----------------------------------------------------------------- events

    def on_click(self, event: events.Click) -> None:
        node = event.widget
        if isinstance(node, _RunRow):
            self.selected_id = node.run_id
