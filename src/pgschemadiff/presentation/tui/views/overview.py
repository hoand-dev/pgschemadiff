"""Overview view (``go``) — comparison summary and contextual risk table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.application.migration.generate import assess_deltas
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.delta.base import DeltaOp
from pgschemadiff.presentation.tui.views._common import (
    DiffRequested,
    Panel,
    SectionHeader,
    op_colour,
)

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.application.sql_emit.risk import RiskAssessment
    from pgschemadiff.domain.identity import ObjectRef

STAT_CARD_BY_OP = {
    DeltaOp.CREATE: "added",
    DeltaOp.ALTER: "modified",
    DeltaOp.RENAME: "modified",
    DeltaOp.REPLACE: "modified",
    DeltaOp.DROP: "dropped",
}


class _ChangeRow(Static):
    """A single clickable change row in the Overview table."""

    def __init__(self, delta_id: str, markup: str) -> None:
        super().__init__(markup, classes="change-row", id=f"change-{delta_id}")
        self._delta_id = delta_id

    @property
    def diff_key(self) -> str:
        return self._delta_id


class OverviewView(Widget):
    """Schema-change overview with a clickable change list."""

    comparison: reactive[SchemaComparisonResult | None] = reactive(None, recompose=True)

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
    OverviewView .changes { width: 1fr; }
    OverviewView .change-row { padding: 0 1; }
    OverviewView .change-row:hover { background: $boost; }
    """

    def compose(self) -> ComposeResult:
        comparison = self.comparison
        crumb = (
            escape(f"{comparison.source.name} → {comparison.target.name}")
            if comparison is not None
            else ""
        )
        yield SectionHeader("Overview", crumb)
        with VerticalScroll():
            if comparison is None:
                yield Static(
                    "No comparison yet. Select a profile and compare schemas.",
                    id="overview-empty",
                )
                return

            assessed = assess_deltas(comparison.deltas)
            counts = dict.fromkeys(("added", "modified", "dropped"), 0)
            for _delta_id, assessment in assessed:
                counts[STAT_CARD_BY_OP[assessment.delta.op]] += 1
            counts["blocked"] = sum(
                assessment.level is RiskLevel.BLOCKED for _delta_id, assessment in assessed
            )

            with Horizontal(classes="stat-grid"):
                for category, label, prefix, colour in (
                    ("added", "added", "+", "$success"),
                    ("modified", "modified", "~", "$warning"),
                    ("dropped", "dropped", "-", "$error"),
                    ("blocked", "blocked", "!", "$warning"),
                ):
                    yield Static(
                        self._stat(label, f"{prefix}{counts[category]}", colour),
                        classes="stat",
                        id=f"stat-{category}",
                    )
            with Panel(f"Changes ({len(assessed)})", id="changes-panel", classes="changes"):
                yield Static(self._table_header(), classes="change-head")
                for delta_id, assessment in assessed:
                    yield _ChangeRow(delta_id, self._row_markup(delta_id, assessment))

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _stat(label: str, value: str, colour: str) -> str:
        return f"[$text-muted]{escape(label)}[/]\n[{colour} bold]{escape(value)}[/]"

    @staticmethod
    def _table_header() -> str:
        columns = (
            f"{'delta ID':<10}{'op':<10}{'kind':<20}{'schema':<16}{'object':<30}{'risk':<12}reason"
        )
        return f"[$text-muted bold]{columns}[/]"

    @staticmethod
    def _row_markup(delta_id: str, assessment: RiskAssessment) -> str:
        delta = assessment.delta
        target = delta.target
        op = delta.op.name
        object_name = _object_name(target)
        return (
            f"[$text-muted]{escape(delta_id):<10}[/]"
            f"[{op_colour(op)}]{escape(op):<10}[/]"
            f"[$text-muted]{escape(target.kind.value):<20}[/]"
            f"[$text-muted]{escape(target.qname.namespace):<16}[/]"
            f"[$primary]{escape(object_name):<30}[/]"
            f"[$text-muted]{escape(assessment.level.value):<12}[/]"
            f"[$text-muted]{escape(assessment.reason)}[/]"
        )

    # ----------------------------------------------------------------- events

    def on_click(self, event: events.Click) -> None:
        node = event.widget
        if isinstance(node, _ChangeRow):
            self.post_message(DiffRequested(node.diff_key))
            return

    def update_comparison(self, comparison: SchemaComparisonResult | None) -> None:
        """Render the current session comparison, or its empty state."""
        self.comparison = comparison


def _object_name(target: ObjectRef) -> str:
    if target.parent is not None:
        return f"{target.parent.qname.name}.{target.qname.name}"
    signature = f"({', '.join(target.arg_signature)})" if target.arg_signature else ""
    return f"{target.qname.name}{signature}"
