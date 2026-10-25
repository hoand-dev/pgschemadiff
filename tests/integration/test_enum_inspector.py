"""PostgreSQL 18 inspection coverage for enum models and column prerequisites."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psycopg
import pytest

from pgschemadiff.domain.identity import QualifiedName
from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool

if TYPE_CHECKING:
    from pgschemadiff.domain.database import Database


@pytest.mark.integration
def test_inspector_maps_enum_and_array_column_prerequisite(pg_test_dsn: str) -> None:
    with psycopg.connect(pg_test_dsn) as conn:
        conn.execute("CREATE SCHEMA enum_types")
        conn.execute("CREATE TYPE enum_types.mood AS ENUM ('sad', 'ok', 'happy')")
        conn.execute("CREATE TYPE enum_types.empty AS ENUM ()")
        conn.execute(
            "CREATE TABLE public.enum_users (mood enum_types.mood, moods enum_types.mood[])"
        )

    async def inspect() -> Database:
        async with Pool(pg_test_dsn) as pool:
            return await PgCatalogInspector(pool).inspect()

    database = asyncio.run(inspect())
    enums = {item.ref.qname.name: item for item in database.all_enums()}
    assert enums["empty"].labels == ()
    enum = enums["mood"]
    assert enum.ref.qname == QualifiedName(namespace="enum_types", name="mood")
    assert enum.labels == ("sad", "ok", "happy")

    table = database.table_by_qname(QualifiedName(namespace="public", name="enum_users"))
    assert table is not None
    assert table.type_prerequisites == (enum.ref,)
