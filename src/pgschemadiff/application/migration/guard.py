"""Verify a bundle's source schema state before applying it."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pgschemadiff.application.diff.fingerprint import schema_fingerprint
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.application.migration.bundle import ValidatedBundle
    from pgschemadiff.application.migration.ports import MigrationHistoryReader
    from pgschemadiff.domain.ports import SchemaInspector


class GuardResult(StrEnum):
    """Outcome of source-state verification."""

    MATCH = "match"
    SKIPPED_LEGACY = "skipped_legacy"
    SKIPPED_RESUME = "skipped_resume"
    SKIPPED_APPLIED = "skipped_applied"


class SourceStateMismatchError(MigrationError):
    """Raised when the inspected source schema differs from the bundle source."""

    def __init__(self, expected_fingerprint: str, found_fingerprint: str) -> None:
        self.expected_short = expected_fingerprint.removeprefix("sha256:")[:12]
        self.found_short = found_fingerprint.removeprefix("sha256:")[:12]
        super().__init__(
            "Database schema does not match the bundle's source state "
            f"(expected {self.expected_short}, found {self.found_short})."
        )


async def verify_source_state(
    bundle: ValidatedBundle,
    inspector: SchemaInspector,
    history: MigrationHistoryReader | None = None,
) -> GuardResult:
    """Verify the database snapshot matches bundle source, allowing safe resumes."""
    if bundle.format_version == 1:
        return GuardResult.SKIPPED_LEGACY

    if history is not None:
        previous_run = next(
            (run for run in await history.list_history() if run.bundle_id == bundle.id),
            None,
        )
        if previous_run is not None:
            return (
                GuardResult.SKIPPED_APPLIED
                if previous_run.status == "applied"
                else GuardResult.SKIPPED_RESUME
            )

    database = await inspector.inspect()
    found_fingerprint = schema_fingerprint(database)
    if found_fingerprint != bundle.source_fingerprint:
        raise SourceStateMismatchError(bundle.source_fingerprint or "", found_fingerprint)
    return GuardResult.MATCH
