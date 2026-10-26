"""PG18 schema-diff/apply round trips across MVP-A DDL families."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

from pgschemadiff.application.migration.apply import ApplyResult, apply_migration
from pgschemadiff.application.migration.bundle import load_bundle
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.sql_emit.risk import RiskLevel, classify_risk
from pgschemadiff.domain.delta import (
    AlterSequenceOptions,
    CreateIndex,
    CreateSequence,
    CreateTable,
    DropIndex,
    ReplaceMaterializedView,
    ReplaceView,
)
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.infrastructure.postgres.applier import open_executor
from pgschemadiff.presentation.cli.commands.diff import compare_urls
from pgschemadiff.shared.errors import ApplyMigrationError, RiskGateError

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
                'CREATE TYPE app.event_payload AS ("inner" app.inner_payload, label text)',
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
            "create-domain-and-use",
            [_APP],
            [
                _APP,
                "CREATE DOMAIN app.positive AS integer CHECK (VALUE > 0)",
                "CREATE TABLE app.domain_values (value app.positive)",
            ],
        ),
        pytest.param(
            "set-domain-default",
            [_APP, "CREATE DOMAIN app.positive AS integer"],
            [_APP, "CREATE DOMAIN app.positive AS integer DEFAULT 7"],
        ),
        pytest.param(
            "drop-domain-default",
            [_APP, "CREATE DOMAIN app.positive AS integer DEFAULT 7"],
            [_APP, "CREATE DOMAIN app.positive AS integer"],
        ),
        pytest.param(
            "set-domain-not-null",
            [_APP, "CREATE DOMAIN app.positive AS integer"],
            [_APP, "CREATE DOMAIN app.positive AS integer NOT NULL"],
        ),
        pytest.param(
            "drop-domain-not-null",
            [_APP, "CREATE DOMAIN app.positive AS integer NOT NULL"],
            [_APP, "CREATE DOMAIN app.positive AS integer"],
        ),
        pytest.param(
            "add-domain-check",
            [_APP, "CREATE DOMAIN app.positive AS integer"],
            [_APP, "CREATE DOMAIN app.positive AS integer CHECK (VALUE > 0)"],
        ),
        pytest.param(
            "validate-domain-check",
            [
                _APP,
                "CREATE DOMAIN app.positive AS integer",
                (
                    "ALTER DOMAIN app.positive ADD CONSTRAINT positive_check "
                    "CHECK (VALUE > 0) NOT VALID"
                ),
            ],
            [_APP, "CREATE DOMAIN app.positive AS integer CHECK (VALUE > 0)"],
        ),
        pytest.param(
            "drop-domain-check",
            [_APP, "CREATE DOMAIN app.positive AS integer CHECK (VALUE > 0)"],
            [_APP, "CREATE DOMAIN app.positive AS integer"],
        ),
        pytest.param(
            "drop-domain",
            [_APP, "CREATE DOMAIN app.positive AS integer"],
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
            "create-sequence",
            [_APP],
            [
                _APP,
                "CREATE SEQUENCE app.event_id_seq AS bigint START WITH 5 INCREMENT BY 2 "
                "MINVALUE 1 MAXVALUE 1000 CACHE 8 CYCLE",
            ],
        ),
        pytest.param(
            "alter-sequence-options",
            [
                _APP,
                "CREATE SEQUENCE app.counter_seq AS integer START WITH 1 INCREMENT BY 1 "
                "MINVALUE 0 MAXVALUE 1000 CACHE 1 NO CYCLE",
            ],
            [
                _APP,
                "CREATE SEQUENCE app.counter_seq AS integer START WITH 11 INCREMENT BY 2 "
                "MINVALUE 0 MAXVALUE 1000 CACHE 5 CYCLE",
            ],
        ),
        pytest.param(
            "drop-standalone-sequence",
            [
                _APP,
                "CREATE SEQUENCE app.standalone_seq AS bigint START WITH 1 INCREMENT BY 1",
            ],
            [_APP],
        ),
        pytest.param(
            "create-serial-style-sequence",
            [_APP],
            [_APP, "CREATE TABLE app.orders (id serial PRIMARY KEY)"],
        ),
        pytest.param(
            "drop-table-with-serial-style-sequence",
            [_APP, "CREATE TABLE app.orders (id serial PRIMARY KEY)"],
            [_APP],
        ),
        pytest.param(
            "identity-backing-sequence",
            [_APP],
            [
                _APP,
                "CREATE TABLE app.identity_rows ("
                "id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY)",
            ],
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
            "create-zero-arg-overloaded-sql-and-plpgsql-functions",
            [_APP],
            [
                _APP,
                "CREATE FUNCTION app.current_version() RETURNS integer LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT 18 $$",
                "CREATE FUNCTION app.echo(value integer) RETURNS integer LANGUAGE plpgsql "
                "IMMUTABLE AS $$ BEGIN RETURN value; END $$",
                "CREATE FUNCTION app.echo(value text) RETURNS text LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value $$",
            ],
        ),
        pytest.param(
            # Functions are created before tables; the applier disables
            # check_function_bodies so this body may reference a new table.
            "sql-function-reading-a-new-table",
            [_APP],
            [
                _APP,
                "CREATE TABLE app.counters (value integer)",
                "CREATE FUNCTION app.counter_total() RETURNS bigint LANGUAGE sql "
                "STABLE AS $$ SELECT count(*) FROM app.counters $$",
            ],
        ),
        pytest.param(
            "replace-function-body-and-default",
            [
                _APP,
                "CREATE FUNCTION app.decorate(value integer, suffix text DEFAULT '!') "
                "RETURNS text LANGUAGE sql IMMUTABLE AS $$ "
                "SELECT value::text || suffix $$",
            ],
            [
                _APP,
                "CREATE FUNCTION app.decorate(value integer, suffix text DEFAULT '?') "
                "RETURNS text LANGUAGE sql IMMUTABLE AS $$ "
                "SELECT upper(value::text) || suffix $$",
            ],
        ),
        pytest.param(
            "drop-exact-function-overload",
            [
                _APP,
                "CREATE FUNCTION app.pick(value integer) RETURNS text LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value::text $$",
                "CREATE FUNCTION app.pick(value text) RETURNS text LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value $$",
            ],
            [
                _APP,
                "CREATE FUNCTION app.pick(value text) RETURNS text LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value $$",
            ],
        ),
        pytest.param(
            "input-type-change-is-overload-add-drop",
            [
                _APP,
                "CREATE FUNCTION app.convert_value(value integer) RETURNS text LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value::text $$",
            ],
            [
                _APP,
                "CREATE FUNCTION app.convert_value(value text) RETURNS text LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value $$",
            ],
        ),
        pytest.param(
            "quoted-function-and-custom-type-prerequisite",
            [_APP],
            [
                _APP,
                "CREATE TYPE app.\"Mood Type\" AS ENUM ('calm', 'bold')",
                'CREATE FUNCTION app."Echo Mood"(value app."Mood Type") '
                'RETURNS app."Mood Type" LANGUAGE sql IMMUTABLE AS $$ SELECT $1 $$',
            ],
        ),
        pytest.param(
            "create-overloaded-sql-and-plpgsql-procedures",
            [_APP],
            [
                _APP,
                "CREATE PROCEDURE app.refresh(value integer) LANGUAGE sql AS $$ SELECT value $$",
                "CREATE PROCEDURE app.refresh(value text) LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE NOTICE '%', value; END $$",
            ],
        ),
        pytest.param(
            # PostgreSQL forbids a function and procedure with the same input
            # signature; same-name routines with distinct signatures coexist.
            "create-function-and-procedure-same-name-different-signatures",
            [_APP],
            [
                _APP,
                "CREATE FUNCTION app.shared(value integer) RETURNS integer LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value $$",
                "CREATE PROCEDURE app.shared(value text) LANGUAGE sql "
                "AS $$ SELECT length(value) $$",
            ],
        ),
        pytest.param(
            "replace-procedure-body-and-default",
            [
                _APP,
                "CREATE PROCEDURE app.decorate(value integer, suffix text DEFAULT '!') "
                "LANGUAGE sql AS $$ SELECT value $$",
            ],
            [
                _APP,
                "CREATE PROCEDURE app.decorate(value integer, suffix text DEFAULT '?') "
                "LANGUAGE sql AS $$ SELECT value + length(suffix) $$",
            ],
        ),
        pytest.param(
            "drop-exact-procedure-overload",
            [
                _APP,
                "CREATE PROCEDURE app.pick(value integer) LANGUAGE sql AS $$ SELECT value $$",
                "CREATE PROCEDURE app.pick(value text) LANGUAGE sql AS $$ SELECT length(value) $$",
            ],
            [
                _APP,
                "CREATE PROCEDURE app.pick(value text) LANGUAGE sql AS $$ SELECT length(value) $$",
            ],
        ),
        pytest.param(
            # With report(IN integer, OUT integer) and report(OUT integer), an unmarked
            # DROP PROCEDURE app.report(integer) matches both; IN markers avoid that.
            "drop-procedure-with-out-parameter",
            [
                _APP,
                "CREATE PROCEDURE app.report(IN v integer, OUT r integer) LANGUAGE plpgsql "
                "AS $$ BEGIN r := v; END $$",
                "CREATE PROCEDURE app.report(OUT r integer) LANGUAGE plpgsql "
                "AS $$ BEGIN r := 1; END $$",
            ],
            [
                _APP,
                "CREATE PROCEDURE app.report(OUT r integer) LANGUAGE plpgsql "
                "AS $$ BEGIN r := 1; END $$",
            ],
        ),
        pytest.param(
            "create-view",
            [_APP, _ITEMS],
            [_APP, _ITEMS, "CREATE VIEW app.active_items AS SELECT id FROM app.items"],
        ),
        pytest.param(
            "replace-view-definition",
            [
                _APP,
                _ITEMS,
                "CREATE VIEW app.active_items AS SELECT id FROM app.items",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE VIEW app.active_items AS SELECT id + 1 AS id FROM app.items",
            ],
        ),
        pytest.param(
            "append-view-output-column",
            [
                _APP,
                _ITEMS,
                "CREATE VIEW app.item_values AS SELECT id FROM app.items",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE VIEW app.item_values AS SELECT id, value FROM app.items",
            ],
        ),
        pytest.param(
            "view-options-and-check-option",
            [_APP, _ITEMS],
            [
                _APP,
                _ITEMS,
                "CREATE VIEW app.positive_items WITH "
                "(security_barrier = true, security_invoker = true) AS "
                "SELECT id FROM app.items WHERE id > 0 WITH LOCAL CHECK OPTION",
            ],
        ),
        pytest.param(
            "drop-dependent-view-chain",
            [
                _APP,
                _ITEMS,
                "CREATE VIEW app.item_ids AS SELECT id FROM app.items",
                "CREATE VIEW app.nested_item_ids AS SELECT id FROM app.item_ids",
            ],
            [_APP, _ITEMS],
        ),
        pytest.param(
            "quoted-mixed-case-view-chain",
            [_APP],
            [
                _APP,
                'CREATE TABLE app."MixedCase" ("select" integer)',
                'CREATE VIEW app."MixedView" AS SELECT "select" FROM app."MixedCase"',
                'CREATE VIEW app."Dependent View" AS SELECT "select" FROM app."MixedView"',
            ],
        ),
        pytest.param(
            "create-materialized-view-over-new-table",
            [_APP],
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals AS "
                "SELECT id, value FROM app.items WITH DATA",
            ],
        ),
        pytest.param(
            "create-materialized-view-over-new-sequence",
            [_APP],
            [
                _APP,
                "CREATE SEQUENCE app.z_source_seq",
                "CREATE MATERIALIZED VIEW app.a_sequence_state AS "
                "SELECT last_value FROM app.z_source_seq WITH DATA",
            ],
        ),
        pytest.param(
            "view-over-materialized-view",
            [_APP, _ITEMS],
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals AS "
                "SELECT id, value FROM app.items WITH DATA",
                "CREATE VIEW app.item_totals_view AS SELECT id, value FROM app.item_totals",
            ],
        ),
        pytest.param(
            "replace-materialized-view-definition",
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals AS "
                "SELECT id, value FROM app.items WITH DATA",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals AS "
                'SELECT id, value + 1 AS "value" FROM app.items WITH DATA',
            ],
        ),
        pytest.param(
            "replace-materialized-view-storage-options",
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals AS "
                "SELECT id, value FROM app.items WITH DATA",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals WITH (fillfactor=80) AS "
                "SELECT id, value FROM app.items WITH DATA",
            ],
        ),
        pytest.param(
            "drop-materialized-view",
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals AS "
                "SELECT id, value FROM app.items WITH DATA",
            ],
            [_APP, _ITEMS],
        ),
        pytest.param(
            "drop-dependent-view-and-materialized-view",
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals AS "
                "SELECT id, value FROM app.items WITH DATA",
                "CREATE VIEW app.item_totals_view AS SELECT id, value FROM app.item_totals",
            ],
            [_APP, _ITEMS],
        ),
        pytest.param(
            "detach-view-before-dropping-materialized-view",
            [
                _APP,
                _ITEMS,
                "CREATE MATERIALIZED VIEW app.item_totals AS "
                "SELECT id, value FROM app.items WITH DATA",
                "CREATE VIEW app.item_totals_view AS SELECT id, value FROM app.item_totals",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE VIEW app.item_totals_view AS SELECT id, value FROM app.items",
            ],
        ),
        pytest.param(
            "create-before-after-row-and-statement-triggers",
            [_APP],
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE FUNCTION app.audit_statement() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NULL; END $$",
                "CREATE TRIGGER items_before_insert BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
                "CREATE TRIGGER items_after_update AFTER UPDATE ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
                "CREATE TRIGGER items_before_delete_statement BEFORE DELETE ON app.items "
                "FOR EACH STATEMENT EXECUTE FUNCTION app.audit_statement()",
                "CREATE TRIGGER items_after_truncate_statement AFTER TRUNCATE ON app.items "
                "FOR EACH STATEMENT EXECUTE FUNCTION app.audit_statement()",
            ],
        ),
        pytest.param(
            "create-update-of-when-trigger",
            [_APP],
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_update_changed BEFORE UPDATE OF value, name ON app.items "
                "FOR EACH ROW WHEN (NEW.value IS DISTINCT FROM OLD.value) "
                "EXECUTE FUNCTION app.audit_row()",
            ],
        ),
        pytest.param(
            "replace-regular-trigger-definition",
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit AFTER INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
            ],
        ),
        pytest.param(
            "replace-deferrable-constraint-trigger",
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE CONSTRAINT TRIGGER items_constraint_audit AFTER INSERT ON app.items "
                "DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW "
                "EXECUTE FUNCTION app.audit_row()",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE CONSTRAINT TRIGGER items_constraint_audit AFTER INSERT ON app.items "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                "EXECUTE FUNCTION app.audit_row()",
            ],
        ),
        pytest.param(
            "create-constraint-trigger-from-referenced-table",
            [_APP],
            [
                _APP,
                "CREATE TABLE app.parents (id integer PRIMARY KEY)",
                "CREATE TABLE app.children (id integer, parent_id integer "
                "REFERENCES app.parents (id))",
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE CONSTRAINT TRIGGER children_parent_audit AFTER INSERT ON app.children "
                "FROM app.parents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                "EXECUTE FUNCTION app.audit_row()",
            ],
        ),
        pytest.param(
            "disable-trigger",
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
                "ALTER TABLE app.items DISABLE TRIGGER items_audit",
            ],
        ),
        pytest.param(
            "enable-origin-trigger",
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
                "ALTER TABLE app.items DISABLE TRIGGER items_audit",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
            ],
        ),
        pytest.param(
            "enable-replica-trigger",
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
                "ALTER TABLE app.items ENABLE REPLICA TRIGGER items_audit",
            ],
        ),
        pytest.param(
            "enable-always-trigger",
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
            ],
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
                "ALTER TABLE app.items ENABLE ALWAYS TRIGGER items_audit",
            ],
        ),
        pytest.param(
            "drop-trigger-before-function",
            [
                _APP,
                _ITEMS,
                "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN NEW; END $$",
                "CREATE TRIGGER items_audit BEFORE INSERT ON app.items "
                "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
            ],
            [_APP, _ITEMS],
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


@pytest.mark.integration
async def test_internal_foreign_key_triggers_produce_no_deltas(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    current_sql = [
        _APP,
        "CREATE TABLE app.parents (id integer PRIMARY KEY)",
        "CREATE TABLE app.children (parent_id integer REFERENCES app.parents(id))",
    ]
    desired_sql = [*current_sql, "ALTER TABLE app.children DISABLE TRIGGER ALL"]
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, desired_sql)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    assert delta_set.is_empty()


@pytest.mark.integration
async def test_partition_trigger_clones_do_not_produce_trigger_deltas(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    common_sql = [
        _APP,
        "CREATE FUNCTION app.audit_row() RETURNS trigger LANGUAGE plpgsql "
        "AS $$ BEGIN RETURN NEW; END $$",
        "CREATE TABLE app.events (id integer) PARTITION BY RANGE (id)",
        "CREATE TRIGGER events_audit AFTER INSERT ON app.events "
        "FOR EACH ROW EXECUTE FUNCTION app.audit_row()",
    ]
    _seed(pg_test_dsn, common_sql)
    _seed(
        pg_test_dsn2,
        [
            *common_sql,
            "CREATE TABLE app.events_2026 PARTITION OF app.events FOR VALUES FROM (2026) TO (2027)",
        ],
    )

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    assert not delta_set.is_empty()
    assert not any(delta.target.kind.value == "trigger" for delta in delta_set)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("current_sql", "desired_sql"),
    [
        pytest.param(
            [_APP],
            [
                _APP,
                "CREATE FUNCTION app.private_value() RETURNS integer LANGUAGE sql "
                "SECURITY DEFINER AS $$ SELECT 1 $$",
            ],
            id="new-security-definer",
        ),
        pytest.param(
            [
                _APP,
                "CREATE FUNCTION app.change_result(value integer) RETURNS integer LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value $$",
            ],
            [
                _APP,
                "CREATE FUNCTION app.change_result(value integer) RETURNS text LANGUAGE sql "
                "IMMUTABLE AS $$ SELECT value::text $$",
            ],
            id="changed-return-type",
        ),
    ],
)
async def test_unsupported_function_changes_fail_risk_gate_before_emission(
    current_sql: list[str],
    desired_sql: list[str],
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, desired_sql)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    assert any(classify_risk(delta).level is RiskLevel.BLOCKED for delta in delta_set)
    with pytest.raises(RiskGateError):
        generate_migration(delta_set, max_risk=RiskLevel.DESTRUCTIVE)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("current_sql", "desired_sql"),
    [
        pytest.param(
            [_APP],
            [
                _APP,
                "CREATE PROCEDURE app.private_run() LANGUAGE sql SECURITY DEFINER "
                "AS $$ SELECT 1 $$",
            ],
            id="new-security-definer",
        ),
        pytest.param(
            [
                _APP,
                "CREATE PROCEDURE app.rename_value(value integer) LANGUAGE sql "
                "AS $$ SELECT value $$",
            ],
            [
                _APP,
                "CREATE PROCEDURE app.rename_value(renamed integer) LANGUAGE sql "
                "AS $$ SELECT renamed $$",
            ],
            id="renamed-input-parameter",
        ),
    ],
)
async def test_unsupported_procedure_changes_fail_risk_gate_before_emission(
    current_sql: list[str],
    desired_sql: list[str],
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, desired_sql)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    assert any(classify_risk(delta).level is RiskLevel.BLOCKED for delta in delta_set)
    with pytest.raises(RiskGateError):
        generate_migration(delta_set, max_risk=RiskLevel.DESTRUCTIVE)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("current_view", "desired_view"),
    [
        pytest.param(
            "CREATE VIEW app.item_view AS SELECT id, value FROM app.items",
            "CREATE VIEW app.item_view AS SELECT id, value AS label FROM app.items",
            id="renamed-output-column",
        ),
        pytest.param(
            "CREATE VIEW app.item_view AS SELECT id, value FROM app.items",
            "CREATE VIEW app.item_view AS SELECT value, id FROM app.items",
            id="reordered-output-columns",
        ),
        pytest.param(
            "CREATE VIEW app.item_view AS SELECT id FROM app.items",
            "CREATE VIEW app.item_view AS SELECT id::text AS id FROM app.items",
            id="changed-output-type",
        ),
    ],
)
async def test_incompatible_view_changes_fail_risk_gate_before_emission(
    current_view: str,
    desired_view: str,
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    common = [_APP, _ITEMS]
    _seed(pg_test_dsn, [*common, current_view])
    _seed(pg_test_dsn2, [*common, desired_view])

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    assert any(isinstance(delta, ReplaceView) and delta.incompatible for delta in delta_set)
    with pytest.raises(RiskGateError):
        generate_migration(delta_set, max_risk=RiskLevel.DESTRUCTIVE)


@pytest.mark.integration
async def test_indexed_materialized_view_definition_change_fails_risk_gate(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    common = [_APP, _ITEMS]
    current = [
        *common,
        "CREATE MATERIALIZED VIEW app.item_totals AS SELECT id, value FROM app.items WITH DATA",
        "CREATE INDEX item_totals_id_idx ON app.item_totals (id)",
    ]
    desired = [
        *common,
        "CREATE MATERIALIZED VIEW app.item_totals AS "
        'SELECT id, value + 1 AS "value" FROM app.items WITH DATA',
        "CREATE INDEX item_totals_id_idx ON app.item_totals (id)",
    ]
    _seed(pg_test_dsn, current)
    _seed(pg_test_dsn2, desired)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    assert tuple(type(delta) for delta in delta_set) == (ReplaceMaterializedView,)
    assert not any(isinstance(delta, (CreateIndex, DropIndex)) for delta in delta_set)
    assert classify_risk(delta_set.deltas[0]).level is RiskLevel.BLOCKED
    with pytest.raises(RiskGateError):
        generate_migration(delta_set, max_risk=RiskLevel.DESTRUCTIVE)


@pytest.mark.integration
async def test_materialized_view_population_state_is_not_compared(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    common = [_APP, _ITEMS]
    definition = "CREATE MATERIALIZED VIEW app.item_totals AS SELECT id, value FROM app.items"
    _seed(pg_test_dsn, [*common, f"{definition} WITH DATA"])
    _seed(pg_test_dsn2, [*common, f"{definition} WITH NO DATA"])

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    assert delta_set.is_empty()


@pytest.mark.integration
async def test_sequence_option_migration_preserves_runtime_state(
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    current_sql = [
        _APP,
        "CREATE SEQUENCE app.runtime_seq AS bigint START WITH 1 INCREMENT BY 1 "
        "MINVALUE 1 MAXVALUE 100 CACHE 1 NO CYCLE",
        "SELECT pg_catalog.setval('app.runtime_seq'::regclass, 42, true)",
    ]
    desired_sql = [
        _APP,
        "CREATE SEQUENCE app.runtime_seq AS bigint START WITH 5 INCREMENT BY 3 "
        "MINVALUE 1 MAXVALUE 200 CACHE 4 CYCLE",
    ]
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, desired_sql)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)
    assert any(isinstance(delta, AlterSequenceOptions) for delta in delta_set)
    plan = generate_migration(
        delta_set,
        max_risk=RiskLevel.DESTRUCTIVE,
        clock=lambda: datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
        id_factory=lambda: "pg18-corpus-sequence-runtime-state",
    )
    bundle_dir = FilesystemMigrationWriter().write(plan, tmp_path)
    manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    bundle = load_bundle(manifest_bytes, up_sql_bytes)

    async with open_executor(pg_test_dsn) as executor:
        result = await apply_migration(bundle, executor, approve_destructive=True)
    assert result.status == "applied"
    with psycopg.connect(pg_test_dsn) as connection:
        state = connection.execute("SELECT last_value, is_called FROM app.runtime_seq").fetchone()
    assert state == (42, True)
    assert (await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)).is_empty()


@pytest.mark.integration
async def test_sequence_owner_transition_precedes_owned_by_change_for_pg18(
    pg_admin_dsn: str,
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    old_owner = "pgsd_sequence_old_owner"
    with psycopg.connect(pg_admin_dsn, autocommit=True) as connection:
        connection.execute(f"CREATE ROLE {old_owner}")

    common = [
        _APP,
        "CREATE SEQUENCE app.transfer_seq AS bigint START WITH 1 INCREMENT BY 1",
    ]
    current_sql = [
        *common,
        f"ALTER SEQUENCE app.transfer_seq OWNER TO {old_owner}",
        "CREATE TABLE app.old_owner_table "
        "(id bigint DEFAULT nextval('app.transfer_seq'::regclass))",
        f"ALTER TABLE app.old_owner_table OWNER TO {old_owner}",
        "ALTER SEQUENCE app.transfer_seq OWNED BY app.old_owner_table.id",
    ]
    desired_sql = [
        *common,
        "CREATE TABLE app.new_owner_table "
        "(id bigint DEFAULT nextval('app.transfer_seq'::regclass))",
        "ALTER SEQUENCE app.transfer_seq OWNED BY app.new_owner_table.id",
    ]
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, desired_sql)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)
    plan = generate_migration(
        delta_set,
        max_risk=RiskLevel.DESTRUCTIVE,
        clock=lambda: datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
        id_factory=lambda: "pg18-corpus-sequence-owner-transition",
    )
    bundle_dir = FilesystemMigrationWriter().write(plan, tmp_path)
    manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    bundle = load_bundle(manifest_bytes, up_sql_bytes)

    async with open_executor(pg_test_dsn) as executor:
        result = await apply_migration(bundle, executor, approve_destructive=True)
    assert result.status == "applied"
    assert (await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)).is_empty()


@pytest.mark.integration
async def test_sequence_owner_follows_table_owner_change_for_pg18(
    pg_admin_dsn: str,
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    old_owner = "pgsd_sequence_table_owner"
    with psycopg.connect(pg_admin_dsn, autocommit=True) as connection:
        connection.execute(f"CREATE ROLE {old_owner}")

    common = [
        _APP,
        "CREATE SEQUENCE app.stable_seq AS bigint START WITH 1 INCREMENT BY 1",
        "CREATE TABLE app.stable_owner_table "
        "(id bigint DEFAULT nextval('app.stable_seq'::regclass))",
        "ALTER SEQUENCE app.stable_seq OWNED BY app.stable_owner_table.id",
    ]
    current_sql = [*common, f"ALTER TABLE app.stable_owner_table OWNER TO {old_owner}"]
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, common)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)
    plan = generate_migration(
        delta_set,
        max_risk=RiskLevel.DESTRUCTIVE,
        clock=lambda: datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
        id_factory=lambda: "pg18-corpus-sequence-table-owner-change",
    )
    bundle_dir = FilesystemMigrationWriter().write(plan, tmp_path)
    manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    bundle = load_bundle(manifest_bytes, up_sql_bytes)

    assert 'ALTER SEQUENCE "app"."stable_seq" OWNER TO' not in up_sql_bytes.decode("utf-8")
    async with open_executor(pg_test_dsn) as executor:
        result = await apply_migration(bundle, executor, approve_destructive=True)
    assert result.status == "applied"
    assert (await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)).is_empty()


@pytest.mark.integration
async def test_identity_backing_sequence_is_not_compared(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    _seed(pg_test_dsn, [_APP])
    _seed(
        pg_test_dsn2,
        [
            _APP,
            "CREATE TABLE app.identity_rows (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY)",
        ],
    )

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    assert any(isinstance(delta, CreateTable) for delta in delta_set)
    assert not any(isinstance(delta, CreateSequence) for delta in delta_set)


@pytest.mark.integration
async def test_invalid_domain_check_validation_keeps_applied_unit_history(
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    current_sql = [
        _APP,
        "CREATE DOMAIN app.positive AS integer",
        "CREATE TABLE app.domain_values (value app.positive)",
        "INSERT INTO app.domain_values VALUES (-1)",
    ]
    desired_sql = [
        _APP,
        "CREATE DOMAIN app.positive AS integer CHECK (VALUE > 0)",
        "CREATE TABLE app.domain_values (value app.positive)",
    ]
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, desired_sql)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)
    plan = generate_migration(
        delta_set,
        max_risk=RiskLevel.DESTRUCTIVE,
        clock=lambda: datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
        id_factory=lambda: "pg18-corpus-domain-validation-failure",
    )
    bundle_dir = FilesystemMigrationWriter().write(plan, tmp_path)
    manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    bundle = load_bundle(manifest_bytes, up_sql_bytes)

    async with open_executor(pg_test_dsn) as executor:
        with pytest.raises(ApplyMigrationError) as failure:
            await apply_migration(bundle, executor, approve_destructive=True)
        result = failure.value.result
        assert isinstance(result, ApplyResult)
        assert result.status == "failed"
        # Units: ADD CONSTRAINT ... NOT VALID, transaction drain, VALIDATE.
        assert result.applied_unit_count == 2
        assert result.failed_unit_index == 2
        assert result.sqlstate == "23514"
        history = await executor.load_history(bundle.id)

    assert history is not None
    assert history.status == "failed"
    assert tuple(unit.status for unit in history.units) == ("applied", "applied", "failed")
    with psycopg.connect(pg_test_dsn) as connection:
        row = connection.execute(
            "SELECT convalidated FROM pg_catalog.pg_constraint "
            "WHERE contypid = 'app.positive'::regtype AND conname = 'positive_check'"
        ).fetchone()
    assert row == (False,)


@pytest.mark.integration
async def test_domain_check_inside_array_composite_or_range_is_blocked(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    current_sql = [
        _APP,
        "CREATE DOMAIN app.positive AS integer",
        "CREATE TYPE app.positive_record AS (value app.positive)",
        "CREATE TYPE app.positive_range AS RANGE (subtype = app.positive)",
        "CREATE TABLE app.domain_containers ("
        "array_values app.positive[], record_value app.positive_record, "
        "range_value app.positive_range)",
    ]
    desired_sql = [
        _APP,
        "CREATE DOMAIN app.positive AS integer CHECK (VALUE > 0)",
        "CREATE TYPE app.positive_record AS (value app.positive)",
        "CREATE TYPE app.positive_range AS RANGE (subtype = app.positive)",
        "CREATE TABLE app.domain_containers ("
        "array_values app.positive[], record_value app.positive_record, "
        "range_value app.positive_range)",
    ]
    _seed(pg_test_dsn, current_sql)
    _seed(pg_test_dsn2, desired_sql)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    with pytest.raises(RiskGateError, match="Domain checks used inside"):
        generate_migration(delta_set, max_risk=RiskLevel.DESTRUCTIVE)


@pytest.mark.integration
async def test_domain_base_type_change_is_blocked(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    _seed(pg_test_dsn, [_APP, "CREATE DOMAIN app.positive AS integer"])
    _seed(pg_test_dsn2, [_APP, "CREATE DOMAIN app.positive AS text"])

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)

    with pytest.raises(RiskGateError, match="base type or collation"):
        generate_migration(delta_set, max_risk=RiskLevel.DESTRUCTIVE)
