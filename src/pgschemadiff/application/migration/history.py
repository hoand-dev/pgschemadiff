"""Read-only migration history use case and result records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from datetime import datetime

    from pgschemadiff.application.migration.ports import (
        MigrationHistoryReader,
        RunStatus,
        UnitStatus,
    )


@dataclass(frozen=True)
class MigrationHistoryUnit:
    """Safe persisted metadata for one migration unit."""

    index: int
    status: UnitStatus
    transactional: bool
    started_at: datetime | None
    finished_at: datetime | None
    failed_statement_index: int | None
    error_class: str | None
    sqlstate: str | None


@dataclass(frozen=True)
class MigrationHistoryRun:
    """Safe persisted metadata for one migration run and its ordered units."""

    bundle_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    up_sql_sha256: str
    units: tuple[MigrationHistoryUnit, ...]


class MigrationHistoryUnavailableError(MigrationError):
    """Raised when an existing history schema cannot be read safely."""


async def list_migration_history(
    reader: MigrationHistoryReader,
    *,
    limit: int = 50,
) -> tuple[MigrationHistoryRun, ...]:
    """Return newest-first migration history, bounded by ``limit``."""
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer.")
    return await reader.list_history(limit=limit)
