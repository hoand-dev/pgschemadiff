"""Risk-gated migration generation, preview, and bundle saving."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Select, Static

from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.presentation.tui.views._common import (
    ApplyRequested,
    Panel,
    SectionHeader,
    markup,
    sql_content,
)

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import ComposeResult

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.application.migration.model import MigrationPlan
    from pgschemadiff.application.migration.render import RenderedBundle
    from pgschemadiff.presentation.tui.session import TuiSession


class GenerateMigrationRequested(Message):
    """Request generation at the selected maximum risk level."""

    def __init__(self, max_risk: RiskLevel) -> None:
        super().__init__()
        self.max_risk = max_risk


class SaveBundleRequested(Message):
    """Request saving the current plan below an existing directory."""

    def __init__(self, output_dir: str) -> None:
        super().__init__()
        self.output_dir = output_dir


class MigrationGenerated(Message):
    """Carry a rendered plan back to the app for session storage."""

    def __init__(
        self,
        comparison: SchemaComparisonResult,
        plan: MigrationPlan,
        bundle: RenderedBundle,
    ) -> None:
        super().__init__()
        self.comparison = comparison
        self.plan = plan
        self.bundle = bundle


class MigrationGenerationFailed(Message):
    """Carry a safe risk-gate detail or fixed generation failure message."""

    def __init__(self, comparison: SchemaComparisonResult, message: str) -> None:
        super().__init__()
        self.comparison = comparison
        self.message = message


class MigrationBundleWritten(Message):
    """Carry the path returned by the injected migration writer."""

    def __init__(self, plan: MigrationPlan, path: Path) -> None:
        super().__init__()
        self.plan = plan
        self.path = path


class MigrationBundleWriteFailed(Message):
    """Signal that bundle saving failed without exposing filesystem details."""

    def __init__(self, plan: MigrationPlan) -> None:
        super().__init__()
        self.plan = plan


class MigrationView(Widget):
    """Render the generated bundle and its plan-owned execution units."""

    show_rollback: reactive[bool] = reactive(False, recompose=True)
    comparison_available: reactive[bool] = reactive(False, recompose=True)
    plan: reactive[MigrationPlan | None] = reactive(None, recompose=True)
    rendered_bundle: reactive[RenderedBundle | None] = reactive(None, recompose=True)
    written_bundle_path: reactive[Path | None] = reactive(None, recompose=True)
    status: reactive[str] = reactive("", recompose=True)
    busy: reactive[bool] = reactive(False, recompose=True)
    max_risk: reactive[str] = reactive(RiskLevel.DANGEROUS.value)
    output_dir: reactive[str] = reactive("./migrations")

    DEFAULT_CSS = """
    MigrationView { height: 1fr; }
    MigrationView > VerticalScroll { height: 1fr; padding: 1 2; }
    MigrationView .toolbar { height: auto; margin-bottom: 1; }
    MigrationView .toolbar > * { margin-right: 1; }
    MigrationView #mig-risk { width: 16; }
    MigrationView #mig-output-dir { width: 24; }
    MigrationView .metadata, MigrationView .status, MigrationView .written-path { height: auto; }
    MigrationView .columns { height: 1fr; }
    MigrationView .script-col { width: 2fr; margin-right: 1; }
    MigrationView .side-col { width: 1fr; }
    MigrationView .tabs { height: auto; }
    MigrationView .script { height: 1fr; min-height: 12; background: $panel; }
    MigrationView .sql-line { height: auto; }
    MigrationView .status.error { color: $error; }
    MigrationView .status.success { color: $success; }
    """

    def update_from_session(self, session: TuiSession) -> None:
        """Refresh the view from the session's comparison and migration state."""
        self.comparison_available = session.last_comparison is not None
        self.plan = session.migration_plan
        self.rendered_bundle = session.rendered_bundle
        self.written_bundle_path = session.written_bundle_path

    def compose(self) -> ComposeResult:
        yield SectionHeader("Migration script")
        with VerticalScroll():
            with Horizontal(classes="toolbar"):
                yield Select(
                    tuple(
                        (risk.name, risk.value)
                        for risk in (
                            RiskLevel.SAFE,
                            RiskLevel.WARNING,
                            RiskLevel.DANGEROUS,
                            RiskLevel.DESTRUCTIVE,
                        )
                    ),
                    value=self.max_risk,
                    allow_blank=False,
                    id="mig-risk",
                )
                yield Button(
                    "Generate",
                    id="mig-generate",
                    variant="primary",
                    disabled=not self.comparison_available or self.busy,
                )
                yield Input(
                    self.output_dir,
                    placeholder="Existing parent directory",
                    id="mig-output-dir",
                )
                yield Button(
                    "Save bundle",
                    id="mig-save",
                    disabled=self.plan is None or self.busy,
                )
                yield Button(
                    "Apply →",
                    id="mig-apply",
                    disabled=self.written_bundle_path is None or self.busy,
                )

            yield Static(
                markup("$metadata", metadata=self._metadata()),
                classes="metadata",
                id="mig-metadata",
            )
            status_content = markup("$status", status=self.status) if self.status else " "
            yield Static(status_content, id="mig-status", classes="status")
            if self.written_bundle_path is None:
                yield Static("Bundle not saved.", classes="written-path", id="mig-written-path")
            else:
                yield Static(
                    markup("Written bundle: $path", path=self.written_bundle_path),
                    classes="written-path",
                    id="mig-written-path",
                )

            with Horizontal(classes="columns"):
                with Vertical(classes="script-col"), Panel("Migration bundle"):
                    with Horizontal(classes="tabs"):
                        yield Button("up.sql", id="mig-fwd")
                        yield Button("Rollback notes — not executable", id="mig-rbk")
                    with VerticalScroll(classes="script"):
                        yield from self._script_content()
                with VerticalScroll(classes="side-col"):
                    with Panel("Execution plan"):
                        yield from self._execution_plan()
                    yield Static("N/A — no lock/row-count estimator.", classes="metadata")

    def _metadata(self) -> str:
        plan = self.plan
        bundle = self.rendered_bundle
        if plan is None or bundle is None:
            return "Generate a plan to preview migration SQL."
        files = dict(bundle.files)
        up_sql = files["up.sql"]
        manifest = json.loads(files["manifest.json"])
        checksum = manifest["checksums"]["up_sql_sha256"]
        line_count = len(up_sql.decode("utf-8").splitlines())
        return (
            f"{plan.created_at.isoformat()} · {len(plan.delta_set)} deltas · "
            f"{line_count} lines · {len(up_sql)} bytes · sha256:{checksum}"
        )

    def _script_content(self) -> ComposeResult:
        bundle = self.rendered_bundle
        if bundle is None:
            yield Static("Generate a plan to preview SQL.", id="mig-no-plan")
            return
        files = dict(bundle.files)
        name = "down.sql" if self.show_rollback else "up.sql"
        sql = files[name].decode("utf-8")
        widget_id = "mig-down-sql" if self.show_rollback else "mig-up-sql"
        yield Static(_numbered_sql(sql), id=widget_id)

    def _execution_plan(self) -> ComposeResult:
        plan = self.plan
        if plan is None:
            yield Static("Generate a plan to inspect execution units.")
            return
        table: DataTable[str] = DataTable(id="mig-units")
        table.add_columns("Unit", "Mode", "Statements", "Delta IDs", "Risk / reason")
        assessments = {record.delta_id: record.assessment for record in plan.assessments}
        for unit in plan.units:
            reasons = "; ".join(
                dict.fromkeys(assessments[delta_id].reason for delta_id in unit.delta_ids)
            )
            table.add_row(
                str(unit.index),
                "transactional" if unit.transaction_unit.transactional else "non-transactional",
                str(len(unit.transaction_unit.statements)),
                ", ".join(unit.delta_ids),
                f"{unit.max_risk.value} — {reasons}",
            )
        yield table

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "mig-generate":
            try:
                max_risk = RiskLevel(self.max_risk)
            except ValueError:
                return
            self.post_message(GenerateMigrationRequested(max_risk))
        elif button_id == "mig-save":
            self.post_message(SaveBundleRequested(self.query_one("#mig-output-dir", Input).value))
        elif button_id == "mig-apply":
            self.post_message(ApplyRequested())
        elif button_id == "mig-fwd":
            self.show_rollback = False
        elif button_id == "mig-rbk":
            self.show_rollback = True
        else:
            return
        event.stop()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "mig-risk" and isinstance(event.value, str):
            self.max_risk = event.value

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "mig-output-dir":
            self.output_dir = event.value


def _numbered_sql(sql: str) -> Content:
    content = Content()
    for line_number, line in enumerate(sql.splitlines(), start=1):
        if line_number > 1:
            content = content.append("\n")
        content = content.append(markup("[$text-muted dim]$line[/] ", line=f"{line_number:>4}"))
        content = content.append(sql_content(line))
    return content
