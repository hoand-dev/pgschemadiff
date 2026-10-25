"""Integration test fixtures — ADR-0010 strategy 3.

One session-scoped ``postgres:18-alpine`` container is started once for the
entire test session.  Each individual test gets a fresh ``test_<uuid>``
database via the function-scoped ``pg_test_dsn`` fixture, which drops the
database (with FORCE) in teardown.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[Any]:
    """Start a ``postgres:18-alpine`` container once for the entire session."""
    with PostgresContainer("postgres:18-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def pg_admin_dsn(postgres_container: Any) -> str:
    """DSN for admin-level connections (used to CREATE / DROP databases).

    ``testcontainers`` returns a SQLAlchemy-style URL
    (``postgresql+psycopg2://…``).  We normalise it to a plain
    ``postgresql://…`` URL that psycopg 3 accepts.
    """
    url: str = postgres_container.get_connection_url()
    # Strip any driver suffix: postgresql+psycopg2:// → postgresql://
    if "+psycopg2" in url:
        url = url.replace("+psycopg2", "", 1)
    elif "+psycopg" in url:
        url = url.replace("+psycopg", "", 1)
    return url


def _fresh_pg_test_dsn(pg_admin_dsn: str) -> Iterator[str]:
    """Create a fresh test database and drop it after yielding its DSN."""
    db_name = f"test_{uuid.uuid4().hex[:12]}"

    base, _, _old_db = pg_admin_dsn.rpartition("/")
    test_dsn = f"{base}/{db_name}"

    # CREATE / DROP DATABASE must run outside a transaction.
    with psycopg.connect(pg_admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db_name}"')

    try:
        yield test_dsn
    finally:
        with psycopg.connect(pg_admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')


@pytest.fixture
def pg_test_dsn(pg_admin_dsn: str) -> Iterator[str]:
    """Create one fresh test database for this test."""
    yield from _fresh_pg_test_dsn(pg_admin_dsn)


@pytest.fixture
def pg_test_dsn2(pg_admin_dsn: str) -> Iterator[str]:
    """Create a second fresh test database for two-database round trips."""
    yield from _fresh_pg_test_dsn(pg_admin_dsn)
