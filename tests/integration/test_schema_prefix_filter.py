"""PG18 inspection must not treat schemas that merely resemble ``pg_`` as system schemas."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psycopg
import pytest

from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool

if TYPE_CHECKING:
    from pgschemadiff.domain.database import Database


@pytest.mark.integration
def test_inspector_keeps_schema_whose_name_starts_with_pg_like_letters(pg_test_dsn: str) -> None:
    # LIKE 'pg_%' would match "pga_app" because _ is a wildcard.
    with psycopg.connect(pg_test_dsn) as conn:
        conn.execute("CREATE SCHEMA pga_app")
        conn.execute("CREATE TABLE pga_app.items (id integer)")

    async def inspect() -> Database:
        async with Pool(pg_test_dsn) as pool:
            return await PgCatalogInspector(pool).inspect()

    database = asyncio.run(inspect())

    assert "pga_app" in {schema.ref.qname.name for schema in database.schemas}
    assert "items" in {table.ref.qname.name for table in database.all_tables()}
