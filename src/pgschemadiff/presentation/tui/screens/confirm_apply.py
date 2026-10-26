"""Explicit confirmation gate for every real migration apply."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.presentation.tui.views._common import markup

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from pgschemadiff.application.migration.bundle import (
        BundleAssessment,
        BundleUnit,
        ValidatedBundle,
    )
    from pgschemadiff.domain.models import Profile


class ConfirmApplyModal(ModalScreen[bool | None]):
    """Require explicit per-run approval; blocked bundles cannot proceed."""

    BINDINGS = [  # noqa: RUF012 — Textual types this as a mutable list
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfirmApplyModal { align: center middle; }
    ConfirmApplyModal > Container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: round $warning;
        padding: 1 2;
    }
    ConfirmApplyModal .title { color: $primary; text-style: bold; padding-bottom: 1; }
    ConfirmApplyModal .target, ConfirmApplyModal .summary { height: auto; padding-bottom: 1; }
    ConfirmApplyModal .risk-item { height: auto; padding: 0 1; }
    ConfirmApplyModal .blocked { color: $error; text-style: bold; }
    ConfirmApplyModal .actions { height: auto; padding-top: 1; }
    ConfirmApplyModal .actions > * { margin-right: 1; }
    """

    def __init__(self, profile: Profile, bundle: ValidatedBundle) -> None:
        super().__init__()
        self._profile_name = profile.name
        self._database = profile.target.database
        self._bundle = bundle
        self._blocked = any(unit.max_risk is RiskLevel.BLOCKED for unit in bundle.units)
        self._destructive = any(unit.max_risk is RiskLevel.DESTRUCTIVE for unit in bundle.units)

    def compose(self) -> ComposeResult:
        assessments = {assessment.delta_id: assessment for assessment in self._bundle.assessments}
        with Container(), Vertical():
            yield Static("Confirm migration apply", classes="title")
            yield Static(
                markup(
                    "Target: $profile · database $database",
                    profile=self._profile_name,
                    database=self._database,
                ),
                classes="target",
            )
            yield Static(
                markup(
                    "$units unit(s) · $deltas delta(s)",
                    units=len(self._bundle.units),
                    deltas=self._bundle.delta_count,
                ),
                classes="summary",
            )
            with VerticalScroll():
                for unit in self._bundle.units:
                    if unit.max_risk is RiskLevel.DESTRUCTIVE:
                        yield _unit_summary(unit, assessments, "DESTRUCTIVE")
                    elif unit.max_risk is RiskLevel.BLOCKED:
                        yield _unit_summary(unit, assessments, "BLOCKED")
            if self._blocked:
                yield Static(
                    "This bundle contains a BLOCKED unit and cannot be applied.",
                    classes="blocked",
                )
            with Horizontal(classes="actions"):
                yield Button("Cancel", id="confirm-cancel")
                if not self._blocked:
                    if self._destructive:
                        yield Button(
                            "Approve destructive apply",
                            id="confirm-destructive",
                            variant="error",
                        )
                    else:
                        yield Button("Confirm apply", id="confirm-apply", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-cancel":
            self.dismiss(None)
        elif event.button.id in {"confirm-apply", "confirm-destructive"} and not self._blocked:
            self.dismiss(True)
        else:
            return
        event.stop()


def _unit_summary(
    unit: BundleUnit,
    assessments: dict[str, BundleAssessment],
    label: str,
) -> Static:
    reasons = "; ".join(dict.fromkeys(assessments[delta_id].reason for delta_id in unit.delta_ids))
    return Static(
        markup(
            "[$warning bold]$label[/] unit index $index · deltas $delta_ids · $reasons",
            label=label,
            index=unit.index,
            delta_ids=", ".join(unit.delta_ids),
            reasons=reasons,
        ),
        classes="risk-item",
    )
