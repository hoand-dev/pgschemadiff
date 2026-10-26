"""Tests for the migration history use case."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pgschemadiff.application.migration.history import (
    MigrationHistoryRun,
    MigrationHistoryUnit,
    list_migration_history,
)


class FakeHistoryReader:
    def __init__(self, runs: tuple[MigrationHistoryRun, ...] = ()) -> None:
        self.runs = runs
        self.limits: list[int] = []

    async def list_history(self, *, limit: int = 50) -> tuple[MigrationHistoryRun, ...]:
        self.limits.append(limit)
        return self.runs[:limit]


def _run(bundle_id: str, started_at: datetime) -> MigrationHistoryRun:
    return MigrationHistoryRun(
        bundle_id=bundle_id,
        status="applied",
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1),
        up_sql_sha256="a" * 64,
        units=(
            MigrationHistoryUnit(
                index=0,
                status="applied",
                transactional=True,
                started_at=started_at,
                finished_at=started_at + timedelta(seconds=1),
                failed_statement_index=None,
                error_class=None,
                sqlstate=None,
            ),
        ),
    )


async def test_list_migration_history_preserves_newest_first_reader_order() -> None:
    now = datetime(2026, 10, 26, tzinfo=UTC)
    newest = _run("newest", now)
    oldest = _run("oldest", now - timedelta(days=1))
    reader = FakeHistoryReader((newest, oldest))

    result = await list_migration_history(reader)

    assert result == (newest, oldest)
    assert reader.limits == [50]


async def test_list_migration_history_passes_requested_limit() -> None:
    now = datetime(2026, 10, 26, tzinfo=UTC)
    runs = tuple(_run(f"bundle-{index}", now - timedelta(seconds=index)) for index in range(3))
    reader = FakeHistoryReader(runs)

    result = await list_migration_history(reader, limit=2)

    assert result == runs[:2]
    assert reader.limits == [2]


async def test_list_migration_history_returns_empty_reader_result() -> None:
    reader = FakeHistoryReader()

    result = await list_migration_history(reader)

    assert result == ()


@pytest.mark.parametrize("limit", [0, -1, True])
async def test_list_migration_history_rejects_invalid_limit(limit: int) -> None:
    reader = FakeHistoryReader()

    with pytest.raises(ValueError, match="positive integer"):
        await list_migration_history(reader, limit=limit)

    assert reader.limits == []
