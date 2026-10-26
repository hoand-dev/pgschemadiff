"""Apply a validated saved bundle to the selected profile's target."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, ProgressBar, Static

from pgschemadiff.application.migration.apply import (
    ApplyEvent,
    ApplyResult,
    RunCancelled,
    RunFinished,
    RunStarted,
    StatementFinished,
    StatementStarted,
    UnitFailed,
    UnitFinished,
    UnitStarted,
)
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.presentation.tui.views._common import Panel, SectionHeader, markup

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.content import Content

    from pgschemadiff.application.migration.bundle import ValidatedBundle
    from pgschemadiff.presentation.tui.session import TuiSession


class ApplyOperationRequested(Message):
    """Request a dry-run connectivity check or confirmed apply."""

    def __init__(self, *, dry_run: bool, lock_timeout: str, statement_timeout: str) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.lock_timeout = lock_timeout
        self.statement_timeout = statement_timeout


class CancelApplyRequested(Message):
    """Cancel the active apply worker."""


class ApplyView(Widget):
    """Show the saved bundle, apply options, event progress, and result."""

    DEFAULT_CSS = """
    ApplyView { height: 1fr; }
    ApplyView > VerticalScroll { height: 1fr; padding: 1 2; }
    ApplyView .toolbar { height: auto; margin-bottom: 1; }
    ApplyView .toolbar > * { margin-right: 1; }
    ApplyView Input { width: 15; }
    ApplyView #apply-target, ApplyView #apply-bundle, ApplyView #apply-summary,
    ApplyView #apply-warning, ApplyView #apply-status, ApplyView #apply-result,
    ApplyView #apply-progress-label { height: auto; }
    ApplyView #apply-warning { color: $warning; }
    ApplyView #apply-status.error { color: $error; }
    ApplyView #apply-result { color: $success; }
    ApplyView #apply-log { height: auto; min-height: 8; background: $panel; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        yield SectionHeader("Apply migration")
        with VerticalScroll():
            yield Static("No profile selected.", id="apply-target")
            yield Static("No saved bundle.", id="apply-bundle")
            yield Static(
                "Load a saved migration bundle to inspect its validated contents.",
                id="apply-summary",
            )
            yield Static(" ", id="apply-warning")
            with Panel("Apply options"):
                with Horizontal(classes="toolbar"):
                    yield Static("Lock timeout (ms or s/min)")
                    yield Input("5000ms", id="apply-lock-timeout")
                    yield Static("Statement timeout (0 = unlimited)")
                    yield Input("0", id="apply-statement-timeout")
                with Horizontal(classes="toolbar"):
                    yield Button("Dry run — connectivity only", id="apply-dry-run")
                    yield Button("Apply…", id="apply-start", variant="primary")
                    yield Button("Cancel run", id="apply-cancel", variant="error")
            yield Static("", id="apply-status", classes="status")
            yield Static("", id="apply-result")
            with Panel("Progress"):
                yield ProgressBar(total=1, show_eta=False, id="apply-bar")
                yield Static("No apply events yet.", id="apply-progress-label")
            with Panel("Apply event log"):
                yield Static("", id="apply-log")

    def update_from_session(self, session: TuiSession) -> None:
        """Render session state without exposing DSNs, SQL, or driver text."""
        profile = session.selected_profile
        if profile is None:
            target_content = markup("No profile selected.")
        else:
            target_content = markup(
                "Target: $profile · database $database",
                profile=profile.name,
                database=profile.target.database,
            )
        self.query_one("#apply-target", Static).update(target_content)

        path = session.written_bundle_path
        if path is None:
            self.query_one("#apply-bundle", Static).update(
                "No saved bundle. Save a bundle in Migration before applying."
            )
        else:
            self.query_one("#apply-bundle", Static).update(markup("Bundle path: $path", path=path))

        bundle = session.validated_bundle
        if bundle is None:
            summary = (
                "Bundle not loaded."
                if path is None
                else "Bundle is loading or could not be validated."
            )
            self.query_one("#apply-summary", Static).update(markup("$summary", summary=summary))
            warning_content = markup(" ")
            unit_count = 0
        else:
            risk = bundle.overall_max_risk.value if bundle.overall_max_risk is not None else "none"
            summary = (
                f"{bundle.delta_count} delta(s) · {len(bundle.units)} unit(s) · highest risk {risk}"
            )
            self.query_one("#apply-summary", Static).update(markup("$summary", summary=summary))
            warning_content = _risk_warning(bundle)
            unit_count = len(bundle.units)

        self.query_one("#apply-warning", Static).update(warning_content)
        status_widget = self.query_one("#apply-status", Static)
        status_widget.update(
            markup("$status", status=session.apply_status) if session.apply_status else " "
        )
        status_widget.set_class(
            session.apply_status
            in {
                "Could not load migration bundle.",
                "Database connection failed.",
                "Migration apply failed.",
            }
            or session.apply_status.startswith("Error:"),
            "error",
        )

        result_content = _result_summary(session.apply_result)
        self.query_one("#apply-result", Static).update(result_content)

        total = max(1, unit_count)
        completed_units = sum(isinstance(event, UnitFinished) for event in session.apply_events)
        if session.apply_result is not None:
            completed_units = session.apply_result.applied_unit_count
        bar = self.query_one("#apply-bar", ProgressBar)
        bar.update(total=total, progress=min(completed_units, total))
        progress_text = _progress_label(session.apply_events, unit_count)
        self.query_one("#apply-progress-label", Static).update(
            markup("$progress", progress=progress_text)
        )

        log = self.query_one("#apply-log", Static)
        log.update(_event_log_content(session.apply_event_timestamps, session.apply_events))

        busy = session.apply_operation in {"loading", "dry-run", "apply"}
        ready = bundle is not None and path is not None and profile is not None
        self.query_one("#apply-dry-run", Button).disabled = busy or not ready
        self.query_one("#apply-start", Button).disabled = busy or not ready
        cancel = self.query_one("#apply-cancel", Button)
        cancel.display = session.apply_operation == "apply"
        cancel.disabled = session.apply_operation != "apply"
        self.query_one("#apply-lock-timeout", Input).disabled = busy
        self.query_one("#apply-statement-timeout", Input).disabled = busy

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id in {"apply-dry-run", "apply-start"}:
            self.post_message(
                ApplyOperationRequested(
                    dry_run=button_id == "apply-dry-run",
                    lock_timeout=self.query_one("#apply-lock-timeout", Input).value.strip(),
                    statement_timeout=self.query_one(
                        "#apply-statement-timeout", Input
                    ).value.strip(),
                )
            )
        elif button_id == "apply-cancel":
            self.post_message(CancelApplyRequested())
        else:
            return
        event.stop()


def _risk_warning(bundle: ValidatedBundle) -> Content:
    assessments = {assessment.delta_id: assessment for assessment in bundle.assessments}
    lines = []
    for unit in bundle.units:
        if unit.max_risk not in {RiskLevel.DESTRUCTIVE, RiskLevel.BLOCKED}:
            continue
        reasons = "; ".join(
            dict.fromkeys(assessments[delta_id].reason for delta_id in unit.delta_ids)
        )
        label = "BLOCKED" if unit.max_risk is RiskLevel.BLOCKED else "DESTRUCTIVE"
        lines.append(
            markup(
                "[$warning bold]$label[/] unit $index · deltas $delta_ids · $reasons",
                label=label,
                index=unit.index,
                delta_ids=", ".join(unit.delta_ids),
                reasons=reasons,
            )
        )
    if not lines:
        return markup("No destructive or blocked units.")
    content = markup(" ")
    for line in lines:
        if content.plain.strip():
            content = content.append("\n")
        content = content.append(line)
    if any(unit.max_risk is RiskLevel.DESTRUCTIVE for unit in bundle.units):
        content = content.append("\n").append(
            markup(
                "Dry-run executes no migration SQL; destructive apply requires explicit approval."
            )
        )
    return content


def _progress_label(events: list[ApplyEvent], unit_count: int) -> str:
    if not events:
        return "No apply events yet."
    event = events[-1]
    if isinstance(event, UnitStarted | UnitFinished | UnitFailed):
        return f"Unit {event.unit_index + 1}/{event.unit_count} · elapsed {event.elapsed:.2f}s"
    if isinstance(event, StatementStarted | StatementFinished):
        return (
            f"Unit {event.unit_index + 1}/{event.unit_count} · "
            f"statement {event.statement_index + 1}/{event.statement_count} · "
            f"delta {event.delta_id} · elapsed {event.elapsed:.2f}s"
        )
    if isinstance(event, RunStarted):
        return f"Run started · {unit_count} unit(s) · elapsed {event.elapsed:.2f}s"
    if isinstance(event, RunFinished):
        return (
            f"Run {event.status} · {event.applied_unit_count}/{event.unit_count} units · "
            f"elapsed {event.elapsed:.2f}s"
        )
    if isinstance(event, RunCancelled):
        return f"Run cancelled · elapsed {event.elapsed:.2f}s"


def _event_log_content(timestamps: list[str], events: list[ApplyEvent]) -> Content:
    rendered_log = markup("")
    for timestamp, event in zip(timestamps, events, strict=False):
        kind, details = _event_log_parts(event)
        if rendered_log.plain:
            rendered_log = rendered_log.append("\n")
        rendered_log = rendered_log.append(
            markup(
                "[$text-muted]$time[/] [$primary]$kind[/] $details",
                time=timestamp,
                kind=kind,
                details=details,
            )
        )
    return rendered_log


def _event_log_parts(event: ApplyEvent) -> tuple[str, str]:
    if isinstance(event, RunStarted):
        return (
            "RunStarted",
            f"units={event.unit_count} resumed={str(event.resumed).lower()} "
            f"elapsed={event.elapsed:.2f}s",
        )
    if isinstance(event, UnitStarted):
        return (
            "UnitStarted",
            f"unit={event.unit_index + 1}/{event.unit_count} statements={event.statement_count} "
            f"deltas={','.join(event.delta_ids)} elapsed={event.elapsed:.2f}s",
        )
    if isinstance(event, (StatementStarted, StatementFinished)):
        return (
            type(event).__name__,
            f"unit={event.unit_index + 1}/{event.unit_count} "
            f"statement={event.statement_index + 1}/{event.statement_count} "
            f"delta={event.delta_id} elapsed={event.elapsed:.2f}s",
        )
    if isinstance(event, UnitFinished):
        return (
            "UnitFinished",
            f"unit={event.unit_index + 1}/{event.unit_count} status=applied "
            f"deltas={','.join(event.delta_ids)} elapsed={event.elapsed:.2f}s",
        )
    if isinstance(event, UnitFailed):
        return (
            "UnitFailed",
            f"unit={event.unit_index + 1}/{event.unit_count} "
            f"statement={event.statement_index + 1}/{event.statement_count} "
            f"delta={event.delta_id} error={event.error_class} "
            f"SQLSTATE={event.sqlstate or 'unknown'} elapsed={event.elapsed:.2f}s",
        )
    if isinstance(event, RunFinished):
        return (
            "RunFinished",
            f"status={event.status} units={event.applied_unit_count}/{event.unit_count} "
            f"elapsed={event.elapsed:.2f}s",
        )
    if isinstance(event, RunCancelled):
        current_unit = (
            "unknown" if event.current_unit_index is None else str(event.current_unit_index)
        )
        current_statement = (
            "unknown"
            if event.current_statement_index is None
            else str(event.current_statement_index)
        )
        return (
            "RunCancelled",
            f"unit_index={current_unit} statement_index={current_statement} "
            f"elapsed={event.elapsed:.2f}s",
        )


def _result_summary(result: ApplyResult | None) -> Content | str:
    if result is None:
        return " "
    content = markup(
        "Result: status=$status · units=$applied/$total · resumed=$resumed · elapsed=$elapsed",
        status=result.status,
        applied=result.applied_unit_count,
        total=result.unit_count,
        resumed="yes" if result.resumed else "no",
        elapsed=f"{result.elapsed:.2f}s",
    )
    if result.failed_unit_index is not None:
        content = content.append("\n").append(
            markup(
                "Failure: unit_index=$unit · statement_index=$statement · delta=$delta · "
                "error=$error · SQLSTATE=$sqlstate",
                unit=result.failed_unit_index,
                statement=result.failed_statement_index,
                delta=result.delta_id or "unknown",
                error=result.error_class or "unknown",
                sqlstate=result.sqlstate or "unknown",
            )
        )
        if result.manual_inspection_required:
            content = content.append("\n").append(markup("Manual inspection required."))
    return content
