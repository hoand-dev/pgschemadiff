"""History view (``gh``) — target database runs and persisted unit timeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static

from pgschemadiff.presentation.tui.views._common import Panel, SectionHeader, markup

if TYPE_CHECKING:
    from datetime import datetime

    from textual import events
    from textual.app import ComposeResult
    from textual.content import Content

    from pgschemadiff.application.migration.history import (
        MigrationHistoryRun,
        MigrationHistoryUnit,
    )
    from pgschemadiff.application.migration.ports import RunStatus
    from pgschemadiff.presentation.tui.session import TuiSession

_STATUS: dict[RunStatus, tuple[str, str]] = {
    "running": ("◐ running", "$warning"),
    "applied": ("● applied", "$success"),
    "failed": ("✗ failed", "$error"),
    "cancelled": ("○ cancelled", "$secondary"),
}


class HistoryRefreshRequested(Message):
    """Request a fresh read of the selected profile's target history."""


class HistoryRunSelected(Message):
    """Select one persisted run without carrying other database metadata."""

    def __init__(self, bundle_id: str) -> None:
        super().__init__()
        self.bundle_id = bundle_id


class _RunRow(Static):
    def __init__(self, bundle_id: str, content: Content, *, selected: bool, row_id: str) -> None:
        classes = "run-row selected" if selected else "run-row"
        super().__init__(content, classes=classes, id=row_id)
        self.bundle_id = bundle_id


def _status_content(status: RunStatus) -> Content:
    text, colour = _STATUS[status]
    return markup(f"[{colour}]$status[/]", status=text)


def _timestamp(value: datetime | None) -> str:
    return "n/a" if value is None else value.isoformat(sep=" ", timespec="seconds")


def _duration(started_at: datetime | None, finished_at: datetime | None) -> str:
    if started_at is None or finished_at is None:
        return "n/a"
    return f"{(finished_at - started_at).total_seconds():.2f}s"


def _failure(unit: MigrationHistoryUnit) -> str:
    details = []
    if unit.failed_statement_index is not None:
        details.append(f"statement index {unit.failed_statement_index}")
    if unit.error_class is not None:
        details.append(f"error class {unit.error_class}")
    if unit.sqlstate is not None:
        details.append(f"SQLSTATE {unit.sqlstate}")
    return "; ".join(details) if details else "n/a"


class HistoryView(Widget):
    """Reverse-chronological run list with persisted unit details."""

    runs: reactive[tuple[MigrationHistoryRun, ...]] = reactive((), recompose=True)
    status: reactive[str] = reactive("", recompose=True)
    selected_id: reactive[str] = reactive("", recompose=True)

    DEFAULT_CSS = """
    HistoryView { height: 1fr; }
    HistoryView > VerticalScroll { height: 1fr; padding: 1 2; }
    HistoryView .toolbar { height: auto; margin: 0 2 1 2; }
    HistoryView .toolbar > * { margin-right: 1; }
    HistoryView #history-status { height: auto; color: $warning; }
    HistoryView .run-row { padding: 0 1; height: auto; }
    HistoryView .run-row:hover { background: $boost; }
    HistoryView .run-row.selected { background: $primary 25%; }
    HistoryView .detail-cols { height: auto; }
    HistoryView .detail-cols .detail { width: 1fr; margin-right: 1; }
    HistoryView .detail-cols .timeline { width: 1fr; }
    """

    def update_from_session(self, session: TuiSession) -> None:
        """Render the history state held by the shared TUI session."""
        self.runs = session.history_runs
        self.status = session.history_status
        self.selected_id = session.selected_history_bundle_id or (
            session.history_runs[0].bundle_id if session.history_runs else ""
        )

    def _entry(self) -> MigrationHistoryRun | None:
        return next((run for run in self.runs if run.bundle_id == self.selected_id), None)

    def compose(self) -> ComposeResult:
        yield SectionHeader("History", "Selected target · persisted runs")
        with Horizontal(classes="toolbar"):
            yield Button("Refresh history", id="history-refresh")
            status = markup("$status", status=self.status) if self.status else " "
            yield Static(status, id="history-status")
        with VerticalScroll():
            with Panel("Runs", id="history-runs"):
                yield Static(markup("bundle id     started                 duration  status"))
                if self.runs:
                    for index, history_run in enumerate(self.runs):
                        yield _RunRow(
                            history_run.bundle_id,
                            self._row_content(history_run),
                            selected=history_run.bundle_id == self.selected_id,
                            row_id=f"history-run-{index}",
                        )
                else:
                    empty_state = self.status or "No migration history found."
                    yield Static(markup("$message", message=empty_state), id="history-empty")
            with Horizontal(classes="detail-cols"):
                run = self._entry()
                with Panel("Run detail", classes="detail"):
                    yield Static(
                        self._detail_content(run)
                        if run is not None
                        else markup("Select a history run to view its details."),
                        id="history-detail",
                    )
                with Panel("Unit timeline", classes="timeline"):
                    yield Static(
                        self._timeline_content(run)
                        if run is not None
                        else markup("No run selected."),
                        id="history-timeline",
                    )

    @staticmethod
    def _row_content(run: MigrationHistoryRun) -> Content:
        row = markup(
            "[$text-muted]$bundle_id[/]  $started  $duration  ",
            bundle_id=run.bundle_id,
            started=_timestamp(run.started_at),
            duration=_duration(run.started_at, run.finished_at),
        )
        return row.append(_status_content(run.status))

    @staticmethod
    def _detail_content(run: MigrationHistoryRun) -> Content:
        detail = markup(
            "[$text-muted]bundle id[/]  [$text]$bundle_id[/]\n"
            "[$text-muted]started[/]    [$text]$started[/]\n"
            "[$text-muted]finished[/]   [$text]$finished[/]\n"
            "[$text-muted]duration[/]   [$text]$duration[/]\n"
            "[$text-muted]checksum[/]   [$text]sha256:$checksum…[/]\n"
            "[$text-muted]status[/]     ",
            bundle_id=run.bundle_id,
            started=_timestamp(run.started_at),
            finished=_timestamp(run.finished_at),
            duration=_duration(run.started_at, run.finished_at),
            checksum=run.up_sql_sha256[:12],
        )
        return detail.append(_status_content(run.status))

    @staticmethod
    def _timeline_content(run: MigrationHistoryRun) -> Content:
        if not run.units:
            return markup("No unit history available.")
        timeline = markup("")
        for unit in run.units:
            if timeline.plain:
                timeline = timeline.append("\n")
            timeline = timeline.append(
                markup(
                    "[$primary]unit $index[/] · status: $status · transactional: $transactional\n"
                    "started: $started · finished: $finished · duration: $duration\n"
                    "failure: $failure",
                    index=unit.index,
                    status=unit.status,
                    transactional="yes" if unit.transactional else "no",
                    started=_timestamp(unit.started_at),
                    finished=_timestamp(unit.finished_at),
                    duration=_duration(unit.started_at, unit.finished_at),
                    failure=_failure(unit),
                )
            )
        return timeline

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "history-refresh":
            self.post_message(HistoryRefreshRequested())
            event.stop()

    def on_click(self, event: events.Click) -> None:
        if isinstance(event.widget, _RunRow):
            self.post_message(HistoryRunSelected(event.widget.bundle_id))
