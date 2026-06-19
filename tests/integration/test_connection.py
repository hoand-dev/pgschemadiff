"""Smoke test: can we connect to the container and run a simple query?"""

from __future__ import annotations

import psycopg
import pytest


@pytest.mark.integration
def test_can_connect(pg_test_dsn: str) -> None:
    with psycopg.connect(pg_test_dsn) as conn:
        row = conn.execute("SELECT version()").fetchone()
    assert row is not None
    assert "PostgreSQL 18" in row[0]
