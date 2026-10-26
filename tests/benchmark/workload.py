"""Shared in-memory and PostgreSQL benchmark workload."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import CheckConstraint, PrimaryKeyConstraint
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.function import Function
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import Table
from pgschemadiff.domain.view import View

BenchSide = Literal["source", "target"]
_COLUMN_TYPES = ("integer", "text", "timestamp with time zone", "numeric", "boolean")


@dataclass(frozen=True)
class BenchWorkload:
    """Counts and schema name shared by both benchmark builders."""

    schema: str = "bench"
    tables: int = 800
    columns_per_table: int = 10
    views: int = 80
    functions: int = 80
    sequences: int = 80

    @property
    def added_tables(self) -> int:
        """Number of source-only tables (also the target-only table count)."""
        return self.tables // 20

    @property
    def dropped_tables(self) -> int:
        """Number of target-only tables."""
        return self.added_tables

    @property
    def added_columns(self) -> int:
        """Number of shared tables receiving a source-only column."""
        return self.tables // 4

    @property
    def widened_columns(self) -> int:
        """Number of shared integer columns widened to bigint in source."""
        return self.tables // 8

    @property
    def changed_indexes(self) -> int:
        """Number of shared secondary indexes changed in source."""
        return self.tables // 8

    @property
    def changed_views(self) -> int:
        """Number of views whose definitions differ."""
        return self.views // 4

    @property
    def changed_functions(self) -> int:
        """Number of function bodies that differ."""
        return self.functions // 4

    @property
    def delta_window(self) -> tuple[int, int]:
        """Inclusive delta-count bounds; table creates/drops may add up to four deltas each."""
        minimum = (
            self.added_tables
            + self.dropped_tables
            + self.added_columns
            + self.widened_columns
            + self.changed_indexes
            + self.changed_views
            + self.changed_functions
        )
        return minimum, minimum + 4 * (self.added_tables + self.dropped_tables)


def count_objects(database: Database) -> int:
    """Count inspector-returned objects, excluding schemas and extensions."""
    count = 0
    for schema in database.schemas:
        count += (
            len(schema.tables)
            + len(schema.indexes)
            + len(schema.views)
            + len(schema.materialized_views)
            + len(schema.functions)
            + len(schema.procedures)
            + len(schema.sequences)
            + len(schema.enums)
            + len(schema.composite_types)
            + len(schema.domain_types)
        )
        for table in schema.tables:
            count += (
                len(table.columns)
                + len(table.constraints)
                + len(table.triggers)
                + len(table.policies)
            )
    return count


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _qualified_identifier(schema: str, name: str) -> str:
    return f"{_quote_identifier(schema)}.{_quote_identifier(name)}"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _ref(
    kind: ObjectKind,
    schema: str,
    name: str,
    *,
    arg_signature: tuple[str, ...] | None = None,
) -> ObjectRef:
    return ObjectRef(
        kind=kind,
        qname=QualifiedName(namespace=schema, name=name),
        arg_signature=arg_signature,
    )


def _column_type(index: int) -> str:
    return _COLUMN_TYPES[(index - 1) % len(_COLUMN_TYPES)]


def _build_table(
    workload: BenchWorkload,
    index: int,
    side: BenchSide,
) -> tuple[Table, tuple[Index, ...]]:
    schema = workload.schema
    name = f"t{index:04d}"
    table_ref = _ref(ObjectKind.TABLE, schema, name)
    is_shared = workload.added_tables <= index < workload.tables
    widened = (
        side == "source" and is_shared and index < workload.added_tables + workload.widened_columns
    )
    added = (
        side == "source" and is_shared and index < workload.added_tables + workload.added_columns
    )

    columns = [Column(name="id", position=1, data_type="bigint", nullable=False)]
    for column_index in range(1, workload.columns_per_table):
        data_type = "bigint" if column_index == 1 and widened else _column_type(column_index)
        columns.append(
            Column(
                name=f"c{column_index:02d}",
                position=column_index + 1,
                data_type=data_type,
            )
        )
    if added:
        columns.append(
            Column(
                name=f"c{workload.columns_per_table:02d}",
                position=workload.columns_per_table + 1,
                data_type="text",
            )
        )

    primary_key_name = f"{name}_pkey"
    secondary_index_name = f"{name}_idx"
    secondary_column = (
        "c02"
        if side == "source"
        and is_shared
        and index < workload.added_tables + workload.changed_indexes
        else "c01"
    )
    table = Table(
        ref=table_ref,
        columns=tuple(columns),
        constraints=(
            PrimaryKeyConstraint(
                name=primary_key_name,
                definition="PRIMARY KEY (id)",
                columns=("id",),
            ),
            CheckConstraint(
                name=f"{name}_check",
                definition="CHECK (c01 >= 0)",
                expression="c01 >= 0",
            ),
        ),
    )
    indexes = (
        Index(
            ref=_ref(ObjectKind.INDEX, schema, primary_key_name),
            table_ref=table_ref,
            method=IndexMethod.BTREE,
            key_columns=(IndexKeyColumn(column_name="id"),),
            unique=True,
            definition=(
                f"CREATE UNIQUE INDEX {_quote_identifier(primary_key_name)} ON "
                f"{_qualified_identifier(schema, name)} USING btree (id)"
            ),
            constraint_name=primary_key_name,
        ),
        Index(
            ref=_ref(ObjectKind.INDEX, schema, secondary_index_name),
            table_ref=table_ref,
            method=IndexMethod.BTREE,
            key_columns=(IndexKeyColumn(column_name=secondary_column),),
            definition=(
                f"CREATE INDEX {_quote_identifier(secondary_index_name)} ON "
                f"{_qualified_identifier(schema, name)} USING btree "
                f"({_quote_identifier(secondary_column)})"
            ),
        ),
    )
    return table, indexes


def _build_view(workload: BenchWorkload, index: int, side: BenchSide) -> View:
    first_shared_table = workload.added_tables
    shared_tables = workload.tables - first_shared_table
    table_name = f"t{first_shared_table + index % shared_tables:04d}"
    definition = f"SELECT id FROM {_qualified_identifier(workload.schema, table_name)}"
    if side == "source" and index < workload.changed_views:
        definition += " WHERE id >= 0"
    return View(
        ref=_ref(ObjectKind.VIEW, workload.schema, f"v{index:04d}"),
        columns=(("id", "bigint"),),
        definition=definition,
        prerequisites=(_ref(ObjectKind.TABLE, workload.schema, table_name),),
    )


def _build_function(workload: BenchWorkload, index: int, side: BenchSide) -> Function:
    body = "SELECT 2" if side == "source" and index < workload.changed_functions else "SELECT 1"
    name = f"f{index:04d}"
    return Function(
        ref=_ref(ObjectKind.FUNCTION, workload.schema, name, arg_signature=()),
        return_type="integer",
        language="sql",
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=1,
        rows=0,
        body=body,
        definition=(
            f"CREATE OR REPLACE FUNCTION {_qualified_identifier(workload.schema, name)}() "
            f"RETURNS integer LANGUAGE sql IMMUTABLE AS $$ {body} $$"
        ),
    )


def _build_sequence(workload: BenchWorkload, index: int) -> Sequence:
    return Sequence(
        ref=_ref(ObjectKind.SEQUENCE, workload.schema, f"s{index:04d}"),
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=9_223_372_036_854_775_807,
        cache=1,
        cycle=False,
    )


def build_snapshots(workload: BenchWorkload) -> tuple[Database, Database]:
    """Build source and target snapshots with the workload's configured changes."""
    snapshots: list[Database] = []
    for side in ("source", "target"):
        if side == "source":
            table_range = range(workload.tables)
        else:
            table_range = range(workload.added_tables, workload.tables + workload.dropped_tables)
        tables: list[Table] = []
        indexes: list[Index] = []
        for index in table_range:
            table, table_indexes = _build_table(workload, index, side)
            tables.append(table)
            indexes.extend(table_indexes)

        schema = Schema(
            ref=_ref(ObjectKind.SCHEMA, workload.schema, workload.schema),
            tables=tuple(tables),
            indexes=tuple(indexes),
            views=tuple(_build_view(workload, index, side) for index in range(workload.views)),
            functions=tuple(
                _build_function(workload, index, side) for index in range(workload.functions)
            ),
            sequences=tuple(
                _build_sequence(workload, index) for index in range(workload.sequences)
            ),
        )
        snapshots.append(Database(name="bench", schemas=(schema,)))
    return snapshots[0], snapshots[1]


def seed_sql(workload: BenchWorkload, side: BenchSide) -> str:
    """Return one server-side seeding script for one PostgreSQL database."""
    is_source = side == "source"
    table_start = 0 if is_source else workload.added_tables
    table_stop = workload.tables if is_source else workload.tables + workload.dropped_tables
    payload_columns = [
        f"c{index:02d} {'%s' if index == 1 else _column_type(index)}"
        for index in range(1, workload.columns_per_table)
    ]
    table_format = (
        "CREATE TABLE %I.%I ("
        + ", ".join(("id bigint PRIMARY KEY", *payload_columns))
        + "%s, CONSTRAINT %I CHECK (c01 >= 0))"
    )

    source_table_changes = ""
    if is_source:
        widened_stop = workload.added_tables + workload.widened_columns
        added_stop = workload.added_tables + workload.added_columns
        changed_index_stop = workload.added_tables + workload.changed_indexes
        source_table_changes = f"""
        IF i >= {workload.added_tables} AND i < {widened_stop} THEN
            c01_type := 'bigint';
        END IF;
        IF i >= {workload.added_tables} AND i < {added_stop} THEN
            extra_column := ', c{workload.columns_per_table:02d} text';
        END IF;
        IF i >= {workload.added_tables} AND i < {changed_index_stop} THEN
            index_column := 'c02';
        END IF;
"""

    source_view_change = ""
    if is_source:
        source_view_change = f"""
        IF i < {workload.changed_views} THEN
            view_filter := ' WHERE id >= 0';
        END IF;
"""

    source_function_change = ""
    if is_source:
        source_function_change = f"""
        IF i < {workload.changed_functions} THEN
            function_body := 'SELECT 2';
        END IF;
"""

    schema_literal = _sql_literal(workload.schema)
    schema_identifier = _quote_identifier(workload.schema)
    table_format_literal = _sql_literal(table_format)
    shared_start = workload.added_tables
    shared_count = workload.tables - shared_start
    return f"""CREATE SCHEMA IF NOT EXISTS {schema_identifier};
DO $pgschemadiff_bench$
DECLARE
    schema_name text := {schema_literal};
    i integer;
    table_name text;
    c01_type text;
    extra_column text;
    index_column text;
    view_name text;
    view_table_name text;
    view_filter text;
    function_name text;
    function_body text;
BEGIN
    FOR i IN {table_start}..{table_stop - 1} LOOP
        table_name := 't' || lpad(i::text, 4, '0');
        c01_type := 'integer';
        extra_column := '';
        index_column := 'c01';
{source_table_changes}
        EXECUTE format(
            {table_format_literal},
            schema_name,
            table_name,
            c01_type,
            extra_column,
            table_name || '_check'
        );
        EXECUTE format(
            'CREATE INDEX %I ON %I.%I USING btree (%I)',
            table_name || '_idx',
            schema_name,
            table_name,
            index_column
        );
    END LOOP;

    FOR i IN 0..{workload.sequences - 1} LOOP
        EXECUTE format('CREATE SEQUENCE %I.%I', schema_name, 's' || lpad(i::text, 4, '0'));
    END LOOP;

    FOR i IN 0..{workload.views - 1} LOOP
        view_name := 'v' || lpad(i::text, 4, '0');
        view_table_name := 't' || lpad(({shared_start} + i % {shared_count})::text, 4, '0');
        view_filter := '';
{source_view_change}
        EXECUTE format(
            'CREATE VIEW %I.%I AS SELECT id FROM %I.%I%s',
            schema_name,
            view_name,
            schema_name,
            view_table_name,
            view_filter
        );
    END LOOP;

    FOR i IN 0..{workload.functions - 1} LOOP
        function_name := 'f' || lpad(i::text, 4, '0');
        function_body := 'SELECT 1';
{source_function_change}
        EXECUTE format(
            'CREATE OR REPLACE FUNCTION %I.%I() RETURNS integer LANGUAGE sql IMMUTABLE AS %L',
            schema_name,
            function_name,
            function_body
        );
    END LOOP;
END
$pgschemadiff_bench$;
"""
