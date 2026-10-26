"""PostgreSQL fixtures re-exported for benchmark tests."""

from tests.integration.conftest import (
    pg_admin_dsn,
    pg_test_dsn,
    pg_test_dsn2,
    postgres_container,
)

__all__ = ["pg_admin_dsn", "pg_test_dsn", "pg_test_dsn2", "postgres_container"]
