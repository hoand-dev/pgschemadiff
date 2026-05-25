"""Placeholder content for each of the 7 tab views.

Each :class:`_BaseView` derivative renders a heading, the task ID that will
fully implement it, and a short bullet list of the planned panels (copied
from ``docs/ui-design.md``).  Replacing a placeholder with the real view is
the deliverable of the corresponding ``P4-TUI-*`` task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.presentation.tui._mock import (
    CHANGE_ROWS,
    CHANGE_SUMMARY,
    SOURCE,
    TARGET,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult


class _BaseView(Widget):
    """Common chrome for placeholder views: header band + bullet list."""

    DEFAULT_CSS = """
    _BaseView { padding: 1 2; }
    _BaseView > Vertical { width: 100%; }
    _BaseView .head {
        background: $surface;
        color: $text;
        padding: 0 1;
        text-style: bold;
        border-bottom: solid $surface-lighten-1;
    }
    _BaseView .crumb { color: $text-muted; padding: 0 1; }
    _BaseView .task-id { color: $warning; text-style: bold; }
    _BaseView .body { padding: 1 0; }
    _BaseView .bullet { padding: 0 1; }
    _BaseView .pill { background: $boost; color: $text-muted; padding: 0 1; }
    """

    TITLE: str = ""
    TASK_ID: str = ""
    BULLETS: tuple[str, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"  {self.TITLE}", classes="head")
            yield Static(
                f"pgschemadiff / {self.TITLE.lower()}   "
                f"[$warning]implementation pending — {self.TASK_ID}[/]",
                classes="crumb",
            )
            yield Static(self._body_text(), classes="body")

    def _body_text(self) -> str:
        lines = ["[b]Planned panels:[/b]"]
        lines.extend(f"  · {b}" for b in self.BULLETS)
        return "\n".join(lines)


class ConnectionView(_BaseView):
    TITLE = "Connection"
    TASK_ID = "P4-TUI-02"
    BULLETS = (
        "two side-by-side profile cards (source / target)",
        "9-field compare-options grid",
        "test-both (^t) and save-profile (^s) actions",
    )

    def _body_text(self) -> str:
        base = super()._body_text()
        snapshot = (
            "\n\n[b]Current mock profiles[/b]\n"
            f"  [$secondary]src[/] {SOURCE.label}  "
            f"{SOURCE.host}  · {SOURCE.table_count} tables · {SOURCE.size}\n"
            f"  [$warning]tgt[/] {TARGET.label}  "
            f"{TARGET.host}  · {TARGET.table_count} tables · {TARGET.size}"
        )
        return base + snapshot


class OverviewView(_BaseView):
    TITLE = "Overview"
    TASK_ID = "P4-TUI-03"
    BULLETS = (
        "stat grid: added / modified / dropped / conflicts",
        "filterable change table → row click jumps to Diff",
        "AI review card (phased migration · archive-before-drop)",
        "ASCII dependency graph for changed objects",
    )

    def _body_text(self) -> str:
        base = super()._body_text()
        s = CHANGE_SUMMARY
        stats = (
            f"\n\n[b]Mock stats[/b]   "
            f"[$success]+{s['add']} added[/]  "
            f"[$warning]~{s['mod']} modified[/]  "
            f"[$error]-{s['del']} dropped[/]  "
            f"[$warning]!{s['conflict']} conflict[/]"
        )
        sample = "\n[b]Sample change rows[/b]\n" + "\n".join(
            f"  {row.op:8} {row.schema}.{row.object}  "
            f"[$warning]{row.risk}[/]  {row.lock}  ~{row.est_ms}ms"
            for row in CHANGE_ROWS[:4]
        )
        return base + stats + sample


class DiffView(_BaseView):
    TITLE = "Diff"
    TASK_ID = "P4-TUI-04"
    BULLETS = (
        "object header (type tag, qualified name, breadcrumb)",
        "view-mode toggle: side / inline / tree (equal width)",
        "syntax-highlighted SQL with add/del/mod/hunk lines",
        "auto-generated rollback snippet",
        "prev/next jump chips",
    )


class MigrationView(_BaseView):
    TITLE = "Migration"
    TASK_ID = "P4-TUI-05"
    BULLETS = (
        "generated SQL pane (topo-sorted DDL, syntax highlighted)",
        "execution plan table (statement / kind / est duration / lock)",
        "lock estimate table per object",
        "forward (up.sql) / rollback (down.sql) tabs",
        "primary action: apply (ga)",
    )


class ApplyView(_BaseView):
    TITLE = "Apply"
    TASK_ID = "P4-TUI-06"
    BULLETS = (
        "pre-flight checklist (ping / lock budget / replica lag / disk / advisory)",
        "animated step-by-step progress",
        "live tail -f log stream",
        "stop / pause / continue / rollback actions",
    )


class HistoryView(_BaseView):
    TITLE = "History"
    TASK_ID = "P4-TUI-07"
    BULLETS = (
        "reverse-chronological runs with status chips",
        "select row → timeline detail (statements, durations, errors)",
        "rollback action with manifest-driven down.sql",
    )


class SettingsView(_BaseView):
    TITLE = "Settings"
    TASK_ID = "P4-TUI-08"
    BULLETS = (
        "appearance: theme, font scale",
        "keymap: vim leader, custom chords",
        "diff & migration: default mode, lock-timeout, max-risk gate",
        "AI / telemetry: enable, redaction rules",
        "live config.toml preview pane",
    )
