"""PostgreSQL 18 inspection coverage for enum and composite type prerequisites."""

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
def test_inspector_maps_enum_composite_and_array_prerequisites(pg_test_dsn: str) -> None:
    with psycopg.connect(pg_test_dsn) as conn:
        conn.execute("CREATE SCHEMA enum_types")
        conn.execute("CREATE TYPE enum_types.mood AS ENUM ('sad', 'ok', 'happy')")
        conn.execute("CREATE TYPE enum_types.empty AS ENUM ()")
        conn.execute(
            "CREATE TYPE enum_types.inner_payload AS "
            "(mood enum_types.mood, moods enum_types.mood[])"
        )
        conn.execute(
            "CREATE TYPE enum_types.outer_payload AS (inner enum_types.inner_payload, label text)"
        )
        conn.execute(
            "CREATE TABLE public.enum_users "
            "(mood enum_types.mood, moods enum_types.mood[], payload enum_types.outer_payload)"
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

    composites = {item.ref.qname.name: item for item in database.all_composite_types()}
    inner = composites["inner_payload"]
    outer = composites["outer_payload"]
    assert tuple(attribute.name for attribute in inner.attributes) == ("mood", "moods")
    assert inner.type_prerequisites == (enum.ref,)
    assert tuple(attribute.name for attribute in outer.attributes) == ("inner", "label")
    assert outer.type_prerequisites == (inner.ref,)

    table = database.table_by_qname(QualifiedName(namespace="public", name="enum_users"))
    assert table is not None
    assert table.type_prerequisites == (enum.ref, outer.ref)
