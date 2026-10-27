"""Tests for migration source-state verification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from pgschemadiff.application.diff.fingerprint import schema_fingerprint
from pgschemadiff.application.migration.bundle import ValidatedBundle
from pgschemadiff.application.migration.guard import (
    GuardResult,
    SourceStateMismatchError,
    verify_source_state,
)
from pgschemadiff.application.migration.history import MigrationHistoryRun
from pgschemadiff.domain.database import Database


def _bundle(
    fingerprint: str | None,
    *,
    format_version: int = 2,
) -> ValidatedBundle:
    return ValidatedBundle(
        format_version=format_version,
        tool_version="0.1.0",
        id="bundle-id",
        slug="test",
        created_at="2026-10-27T00:00:00Z",
        source_fingerprint=fingerprint,
        target_fingerprint=None,
        delta_count=0,
        overall_max_risk=None,
        assessments=(),
        units=(),
        up_sql_sha256="0" * 64,
        inspected_schemas=("app",),
    )


class FakeInspector:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.calls = 0

    async def inspect(self) -> Database:
        self.calls += 1
        return self.database


class FakeHistory:
    def __init__(self, runs: tuple[MigrationHistoryRun, ...]) -> None:
        self.runs = runs
        self.calls = 0

    async def list_history(self, *, limit: int = 50) -> tuple[MigrationHistoryRun, ...]:
        assert limit == 50
        self.calls += 1
        return self.runs


def _history_run(bundle_id: str, status: str) -> MigrationHistoryRun:
    return MigrationHistoryRun(
        bundle_id=bundle_id,
        status=status,  # type: ignore[arg-type]
        started_at=datetime(2026, 10, 27, tzinfo=UTC),
        finished_at=None,
        up_sql_sha256="0" * 64,
        units=(),
    )


def test_verify_source_state_matches_fingerprint() -> None:
    database = Database(name="target", server_version="18.0")
    inspector = FakeInspector(database)

    result = asyncio.run(
        verify_source_state(
            _bundle(schema_fingerprint(Database(name="source", server_version="18.0"))),
            inspector,
        )
    )

    assert result is GuardResult.MATCH
    assert inspector.calls == 1


def test_verify_source_state_raises_safe_mismatch_with_short_fingerprints() -> None:
    expected = schema_fingerprint(Database(name="source", server_version="17.0"))
    inspector = FakeInspector(Database(name="target", server_version="18.0"))

    with pytest.raises(SourceStateMismatchError) as error:
        asyncio.run(verify_source_state(_bundle(expected), inspector))

    assert error.value.expected_short == expected.removeprefix("sha256:")[:12]
    assert (
        error.value.found_short
        == schema_fingerprint(inspector.database).removeprefix("sha256:")[:12]
    )
    assert "Database schema does not match" in str(error.value)
    assert "postgres" not in str(error.value)


def test_verify_source_state_skips_legacy_bundle() -> None:
    inspector = FakeInspector(Database(name="target"))

    result = asyncio.run(verify_source_state(_bundle(None, format_version=1), inspector))

    assert result is GuardResult.SKIPPED_LEGACY
    assert inspector.calls == 0


@pytest.mark.parametrize("status", ["running", "failed", "cancelled"])
def test_verify_source_state_skips_resume_for_non_applied_run(status: str) -> None:
    inspector = FakeInspector(Database(name="target"))
    history = FakeHistory((_history_run("bundle-id", status),))

    result = asyncio.run(
        verify_source_state(_bundle(schema_fingerprint(inspector.database)), inspector, history)
    )

    assert result is GuardResult.SKIPPED_RESUME
    assert history.calls == 1
    assert inspector.calls == 0


def test_verify_source_state_reports_applied_bundle_without_claiming_match() -> None:
    inspector = FakeInspector(Database(name="target"))
    history = FakeHistory((_history_run("bundle-id", "applied"),))

    result = asyncio.run(verify_source_state(_bundle("sha256:" + "1" * 64), inspector, history))

    assert result is GuardResult.SKIPPED_APPLIED
    assert history.calls == 1
    assert inspector.calls == 0


def test_verify_source_state_inspects_when_history_has_no_matching_bundle() -> None:
    database = Database(name="target")
    inspector = FakeInspector(database)
    history = FakeHistory((_history_run("another-bundle", "failed"),))

    result = asyncio.run(
        verify_source_state(_bundle(schema_fingerprint(database)), inspector, history)
    )

    assert result is GuardResult.MATCH
    assert inspector.calls == 1
