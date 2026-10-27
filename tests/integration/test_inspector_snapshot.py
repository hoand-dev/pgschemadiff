"""The inspector's catalog transaction really runs at REPEATABLE READ (ADR-0012)."""

from __future__ import annotations

import pytest

from pgschemadiff.infrastructure.postgres.inspector import begin_snapshot
from pgschemadiff.infrastructure.postgres.pool import Pool

pytestmark = pytest.mark.integration


async def test_begin_snapshot_sets_isolation_read_only_and_search_path(pg_test_dsn: str) -> None:
    async with Pool(pg_test_dsn) as pool, pool.acquire() as conn:
        await begin_snapshot(conn)
        try:
            settings = {}
            for name in ("transaction_isolation", "transaction_read_only", "search_path"):
                cursor = await conn.execute(f"SHOW {name}")
                row = await cursor.fetchone()
                assert row is not None
                settings[name] = row[0]
        finally:
            await conn.execute("ROLLBACK")

    assert settings == {
        "transaction_isolation": "repeatable read",
        "transaction_read_only": "on",
        "search_path": "pg_catalog",
    }
