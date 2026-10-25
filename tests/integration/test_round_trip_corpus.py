"""PG18 schema-diff/apply round trips across MVP-A DDL families."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

from pgschemadiff.application.migration.apply import apply_migration
from pgschemadiff.application.migration.bundle import load_bundle
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.infrastructure.postgres.applier import open_executor
from pgschemadiff.presentation.cli.commands.diff import compare_urls

if TYPE_CHECKING:
    from pathlib import Path

_APP = "CREATE SCHEMA app"
_ITEMS = "CREATE TABLE app.items (id integer, value integer, name text, payload jsonb)"


def _seed(dsn: str, statements: list[str]) -> None:
    with psycopg.connect(dsn) as connection:
        for statement in statements:
            connection.execute(statement)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("scenario", "current_sql", "desired_sql"),
    [
        pytest.param(
            "create-schema-and-extension",
            [],
            ["CREATE SCHEMA app", "CREATE EXTENSION pgcrypto WITH SCHEMA app"],
        ),
        pytest.param(
            "drop-extension",
            [_APP, "CREATE EXTENSION pgcrypto WITH SCHEMA app"],
            [_APP],
        ),
        pytest.param("drop-schema", [_APP], []),
        pytest.param("create-table", [_APP], [_APP, _ITEMS]),
        pytest.param("drop-table", [_APP, _ITEMS], [_APP]),
        pytest.param(
            "create-enum-and-table",
            [_APP],
            [
                _APP,
                "CREATE TYPE app.mood AS ENUM ('sad', 'okay', 'happy')",
                "CREATE TABLE app.status (mood app.mood)",
            ],
        ),
        pytest.param(
            "append-enum-label",
            [_APP, "CREATE TYPE app.mood AS ENUM ('sad', 'okay')"],
            [_APP, "CREATE TYPE app.mood AS ENUM ('sad', 'okay', 'happy')"],
        ),
        pytest.param(
            "insert-enum-label-before",
            [_APP, "CREATE TYPE app.mood AS ENUM ('sad', 'happy')"],
            [_APP, "CREATE TYPE app.mood AS ENUM ('sad', 'okay', 'happy')"],
        ),
        pytest.param(
            "insert-enum-label-after",
            [_APP, "CREATE TYPE app.mood AS ENUM ('sad', 'happy')"],
            [_APP, "CREATE TYPE app.mood AS ENUM ('sad', 'happy', 'great')"],
        ),
        pytest.param(
            "enum-addition-before-column-default",
            [
                _APP,
                "CREATE TYPE app.mood AS ENUM ('sad', 'okay')",
                "CREATE TABLE app.status (mood app.mood)",
            ],
            [
                _APP,
                "CREATE TYPE app.mood AS ENUM ('sad', 'okay', 'happy')",
                "CREATE TABLE app.status (mood app.mood DEFAULT 'happy'::app.mood)",
            ],
        ),
        pytest.param(
            "drop-enum-after-column",
            [
                _APP,
                "CREATE TYPE app.mood AS ENUM ('sad', 'okay')",
                "CREATE TABLE app.status (id integer, mood app.mood)",
            ],
            [_APP, "CREATE TABLE app.status (id integer)"],
        ),
        pytest.param(
            "create-nested-composite-types-and-table",
            [_APP],
            [
                _APP,
                "CREATE TYPE app.mood AS ENUM ('sad', 'happy')",
                "CREATE TYPE app.inner_payload AS (mood app.mood)",
                "CREATE TYPE app.event_payload AS (inner app.inner_payload, label text)",
                "CREATE TABLE app.events (payload app.event_payload)",
            ],
        ),
        pytest.param(
            "append-composite-attribute",
            [_APP, "CREATE TYPE app.payload AS (value integer)"],
            [_APP, "CREATE TYPE app.payload AS (value integer, label text)"],
        ),
        pytest.param(
            "rename-last-composite-attribute",
            [_APP, "CREATE TYPE app.payload AS (id integer, old_label text)"],
            [_APP, "CREATE TYPE app.payload AS (id integer, label text)"],
        ),
        pytest.param(
            "change-composite-attribute-type",
            [_APP, "CREATE TYPE app.payload AS (value integer)"],
            [_APP, "CREATE TYPE app.payload AS (value bigint)"],
        ),
        pytest.param(
            "drop-composite-attribute",
            [_APP, "CREATE TYPE app.payload AS (id integer, obsolete text)"],
            [_APP, "CREATE TYPE app.payload AS (id integer)"],
        ),
        pytest.param(
            "drop-composite-after-dependent-table",
            [
                _APP,
                "CREATE TYPE app.payload AS (value integer)",
                "CREATE TABLE app.events (payload app.payload)",
            ],
            [_APP],
        ),
        pytest.param(
            "partitioned-parent-and-child",
            [_APP],
            [
                _APP,
                "CREATE TABLE app.events (event_date date) PARTITION BY RANGE (event_date)",
                "CREATE TABLE app.events_2026 PARTITION OF app.events "
                "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
            ],
        ),
        pytest.param(
            "add-nullable-column",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "ALTER TABLE app.items ADD COLUMN note text"],
        ),
        pytest.param(
            "add-not-null-column-with-default",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "ALTER TABLE app.items ADD COLUMN status text NOT NULL DEFAULT 'ready'"],
        ),
        pytest.param(
            "add-identity-column",
            [_APP, _ITEMS],
            [
                _APP,
                _ITEMS,
                "ALTER TABLE app.items ADD COLUMN generated_id bigint "
                "GENERATED BY DEFAULT AS IDENTITY",
            ],
        ),
        pytest.param(
            "add-stored-generated-column",
            [_APP, _ITEMS],
            [
                _APP,
                _ITEMS,
                "ALTER TABLE app.items ADD COLUMN doubled integer "
                "GENERATED ALWAYS AS (value * 2) STORED",
            ],
        ),
        pytest.param(
            "drop-column",
            [_APP, _ITEMS, "ALTER TABLE app.items ADD COLUMN obsolete text"],
            [_APP, _ITEMS],
        ),
        pytest.param(
            "change-column-type",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "ALTER TABLE app.items ALTER COLUMN value TYPE bigint"],
        ),
        pytest.param(
            "set-column-default",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "ALTER TABLE app.items ALTER COLUMN value SET DEFAULT 7"],
        ),
        pytest.param(
            "drop-column-default",
            [_APP, _ITEMS, "ALTER TABLE app.items ALTER COLUMN value SET DEFAULT 7"],
            [_APP, _ITEMS],
        ),
        pytest.param(
            "set-not-null",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "ALTER TABLE app.items ALTER COLUMN value SET NOT NULL"],
        ),
        pytest.param(
            "drop-not-null",
            [
                _APP,
                "CREATE TABLE app.items (id integer, value integer NOT NULL, "
                "name text, payload jsonb)",
            ],
            [_APP, _ITEMS],
        ),
        pytest.param(
            "set-column-collation-c",
            [_APP, _ITEMS],
            [_APP, _ITEMS, 'ALTER TABLE app.items ALTER COLUMN name TYPE text COLLATE "C"'],
        ),
        pytest.param(
            "create-plain-index",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "CREATE INDEX items_value_idx ON app.items (value)"],
        ),
        pytest.param(
            "create-unique-index",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "CREATE UNIQUE INDEX items_value_unique_idx ON app.items (value)"],
        ),
        pytest.param(
            "create-partial-index",
            [_APP, _ITEMS],
            [
                _APP,
                _ITEMS,
                "CREATE INDEX items_value_partial_idx ON app.items (value) WHERE value > 0",
            ],
        ),
        pytest.param(
            "create-expression-index",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "CREATE INDEX items_lower_name_idx ON app.items (lower(name))"],
        ),
        pytest.param(
            "create-include-index",
            [_APP, _ITEMS],
            [
                _APP,
                _ITEMS,
                "CREATE INDEX items_value_include_idx ON app.items (value) INCLUDE (name)",
            ],
        ),
        pytest.param(
            "create-gin-index",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "CREATE INDEX items_payload_gin_idx ON app.items USING gin (payload)"],
        ),
        pytest.param(
            "drop-index",
            [_APP, _ITEMS, "CREATE INDEX items_value_idx ON app.items (value)"],
            [_APP, _ITEMS],
        ),
        pytest.param(
            "replace-index-definition",
            [_APP, _ITEMS, "CREATE INDEX items_value_idx ON app.items (value)"],
            [_APP, _ITEMS, "CREATE INDEX items_value_idx ON app.items (value) WHERE value > 0"],
        ),
        pytest.param(
            "index-on-partitioned-table",
            [
                _APP,
                "CREATE TABLE app.events (event_date date) PARTITION BY RANGE (event_date)",
                "CREATE TABLE app.events_2026 PARTITION OF app.events "
                "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
                "CREATE TABLE app.events_2027 PARTITION OF app.events "
                "FOR VALUES FROM ('2027-01-01') TO ('2028-01-01')",
            ],
            [
                _APP,
                "CREATE TABLE app.events (event_date date) PARTITION BY RANGE (event_date)",
                "CREATE TABLE app.events_2026 PARTITION OF app.events "
                "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
                "CREATE TABLE app.events_2027 PARTITION OF app.events "
                "FOR VALUES FROM ('2027-01-01') TO ('2028-01-01')",
                "CREATE INDEX events_date_idx ON app.events (event_date)",
            ],
        ),
        pytest.param(
            "drop-partitioned-index",
            [
                _APP,
                "CREATE TABLE app.events (event_date date) PARTITION BY RANGE (event_date)",
                "CREATE TABLE app.events_2026 PARTITION OF app.events "
                "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
                "CREATE TABLE app.events_2027 PARTITION OF app.events "
                "FOR VALUES FROM ('2027-01-01') TO ('2028-01-01')",
                "CREATE INDEX events_date_idx ON app.events (event_date)",
            ],
            [
                _APP,
                "CREATE TABLE app.events (event_date date) PARTITION BY RANGE (event_date)",
                "CREATE TABLE app.events_2026 PARTITION OF app.events "
                "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
                "CREATE TABLE app.events_2027 PARTITION OF app.events "
                "FOR VALUES FROM ('2027-01-01') TO ('2028-01-01')",
            ],
        ),
        pytest.param(
            "add-partition-to-indexed-parent",
            [
                _APP,
                "CREATE TABLE app.events (event_date date) PARTITION BY RANGE (event_date)",
                "CREATE TABLE app.events_2026 PARTITION OF app.events "
                "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
                "CREATE TABLE app.events_2027 PARTITION OF app.events "
                "FOR VALUES FROM ('2027-01-01') TO ('2028-01-01')",
                "CREATE INDEX events_date_idx ON app.events (event_date)",
            ],
            [
                _APP,
                "CREATE TABLE app.events (event_date date) PARTITION BY RANGE (event_date)",
                "CREATE TABLE app.events_2026 PARTITION OF app.events "
                "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
                "CREATE TABLE app.events_2027 PARTITION OF app.events "
                "FOR VALUES FROM ('2027-01-01') TO ('2028-01-01')",
                "CREATE INDEX events_date_idx ON app.events (event_date)",
                "CREATE TABLE app.events_2028 PARTITION OF app.events "
                "FOR VALUES FROM ('2028-01-01') TO ('2029-01-01')",
            ],
        ),
        pytest.param(
            "add-primary-key",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "ALTER TABLE app.items ADD CONSTRAINT items_pkey PRIMARY KEY (id)"],
        ),
        pytest.param(
            "add-unique-constraint",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "ALTER TABLE app.items ADD CONSTRAINT items_value_key UNIQUE (value)"],
        ),
        pytest.param(
            "add-check-constraint",
            [_APP, _ITEMS],
            [
                _APP,
                _ITEMS,
                "ALTER TABLE app.items ADD CONSTRAINT items_value_check CHECK (value > 0)",
            ],
        ),
        pytest.param(
            "add-cascading-deferrable-foreign-key",
            [
                _APP,
                "CREATE TABLE app.parents (id integer PRIMARY KEY)",
                "CREATE TABLE app.children (parent_id integer)",
            ],
            [
                _APP,
                "CREATE TABLE app.parents (id integer PRIMARY KEY)",
                "CREATE TABLE app.children (parent_id integer)",
                "ALTER TABLE app.children ADD CONSTRAINT children_parent_fk "
                "FOREIGN KEY (parent_id) REFERENCES app.parents (id) "
                "ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED",
            ],
        ),
        pytest.param(
            "add-exclusion-constraint",
            [_APP, "CREATE TABLE app.bookings (during tsrange)"],
            [
                _APP,
                "CREATE TABLE app.bookings (during tsrange)",
                "ALTER TABLE app.bookings ADD CONSTRAINT bookings_no_overlap "
                "EXCLUDE USING gist (during WITH &&)",
            ],
        ),
        pytest.param(
            "drop-constraint",
            [
                _APP,
                "CREATE TABLE app.items (id integer, value integer, "
                "CONSTRAINT items_value_check CHECK (value > 0))",
            ],
            [_APP, "CREATE TABLE app.items (id integer, value integer)"],
        ),
        pytest.param(
            "foreign-key-between-new-tables",
            [_APP],
            [
                _APP,
                "CREATE TABLE app.parents (id integer PRIMARY KEY)",
                "CREATE TABLE app.children (parent_id integer, "
                "CONSTRAINT children_parent_fk FOREIGN KEY (parent_id) "
                "REFERENCES app.parents (id) ON DELETE CASCADE "
                "DEFERRABLE INITIALLY DEFERRED)",
            ],
        ),
        pytest.param(
            "foreign-key-from-new-table-to-existing-table",
            [_APP, "CREATE TABLE app.parents (id integer PRIMARY KEY)"],
            [
                _APP,
                "CREATE TABLE app.parents (id integer PRIMARY KEY)",
                "CREATE TABLE app.children (parent_id integer, "
                "CONSTRAINT children_parent_fk FOREIGN KEY (parent_id) "
                "REFERENCES app.parents (id))",
            ],
        ),
        pytest.param(
            "quoted-mixed-case-and-reserved-identifiers",
            [_APP],
            [_APP, 'CREATE TABLE app."MixedCase" ("select" integer, "MixedColumn" text)'],
        ),
        pytest.param(
            "pg18-virtual-generated-column",
            [_APP, "CREATE TABLE app.virtuals (value integer)"],
            [
                _APP,
                "CREATE TABLE app.virtuals (value integer, doubled integer "
                "GENERATED ALWAYS AS (value * 2) VIRTUAL)",
            ],
        ),
        pytest.param(
            "unlogged-table-persistence",
            [_APP, "CREATE TABLE app.items (id integer)"],
            [
                _APP,
                "CREATE UNLOGGED TABLE app.items (id integer)",
                "CREATE UNLOGGED TABLE app.unlogged_items (id integer)",
            ],
        ),
    ],
)
async def test_pg18_round_trip_corpus(
    scenario: str,
    current_sql: list[str],
    desired_sql: list[str],
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    """Apply each generated migration to current and verify schema convergence."""
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, desired_sql)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)
    assert not delta_set.is_empty(), scenario

    plan = generate_migration(
        delta_set,
        max_risk=RiskLevel.DESTRUCTIVE,
        clock=lambda: datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
        id_factory=lambda: f"pg18-corpus-{scenario}",
    )
    bundle_dir = FilesystemMigrationWriter().write(plan, tmp_path)
    manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    bundle = load_bundle(manifest_bytes, up_sql_bytes)

    async with open_executor(pg_test_dsn) as executor:
        result = await apply_migration(bundle, executor, approve_destructive=True)
    assert result.status == "applied", scenario

    remaining = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)
    assert remaining.is_empty(), scenario
