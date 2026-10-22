"""Property tests for diff idempotence and deterministic ordering."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pgschemadiff.application.diff.comparators import (
    ColumnComparator,
    ConstraintComparator,
    SchemaComparator,
    TableComparator,
)
from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.application.diff.engine import DiffEngine
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table

if TYPE_CHECKING:
    from hypothesis.strategies import DrawFn, SearchStrategy

    from pgschemadiff.domain.delta import DeltaSet


_IDENTIFIER: SearchStrategy[str] = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz",
    min_size=1,
    max_size=8,
)


def _database_strategy(*, min_schemas: int = 0) -> SearchStrategy[Database]:
    @st.composite
    def build(draw: DrawFn) -> Database:
        schema_names = draw(st.lists(_IDENTIFIER, min_size=min_schemas, max_size=4, unique=True))
        schemas: list[Schema] = []

        for schema_name in schema_names:
            table_names = draw(st.lists(_IDENTIFIER, min_size=1, max_size=3, unique=True))
            tables: list[Table] = []

            for table_name in table_names:
                column_names = draw(st.lists(_IDENTIFIER, min_size=1, max_size=3, unique=True))
                columns = tuple(
                    Column(
                        name=column_name,
                        position=position,
                        data_type=draw(st.sampled_from(("boolean", "integer", "text"))),
                        nullable=draw(st.booleans()),
                    )
                    for position, column_name in enumerate(column_names, start=1)
                )
                tables.append(
                    Table(
                        ref=ObjectRef(
                            kind=ObjectKind.TABLE,
                            qname=QualifiedName(namespace=schema_name, name=table_name),
                        ),
                        columns=columns,
                    )
                )

            schemas.append(
                Schema(
                    ref=ObjectRef(
                        kind=ObjectKind.SCHEMA,
                        qname=QualifiedName(namespace=schema_name, name=schema_name),
                    ),
                    tables=tuple(tables),
                )
            )

        return Database(name="generated", schemas=tuple(schemas))

    return build()


def _reverse_catalog_order(snapshot: Database) -> Database:
    schemas = tuple(
        schema.model_copy(
            update={
                "tables": tuple(
                    table.model_copy(update={"columns": tuple(reversed(table.columns))})
                    for table in reversed(schema.tables)
                )
            }
        )
        for schema in reversed(snapshot.schemas)
    )
    return snapshot.model_copy(update={"schemas": schemas})


def _change_column_types(snapshot: Database) -> Database:
    schemas = tuple(
        schema.model_copy(
            update={
                "tables": tuple(
                    table.model_copy(
                        update={
                            "columns": tuple(
                                column.model_copy(
                                    update={
                                        "data_type": (
                                            "text" if column.data_type != "text" else "integer"
                                        )
                                    }
                                )
                                for column in table.columns
                            )
                        }
                    )
                    for table in schema.tables
                )
            }
        )
        for schema in snapshot.schemas
    )
    return snapshot.model_copy(update={"schemas": schemas})


def _diff(source: Database, target: Database) -> DeltaSet:
    engine = DiffEngine(
        comparators=(
            SchemaComparator(),
            TableComparator(
                column_comparator=ColumnComparator(),
                constraint_comparator=ConstraintComparator(),
            ),
        )
    )
    return order_deltas(engine.diff(source, target))


@pytest.mark.unit
@settings(max_examples=500)
@given(snapshot=_database_strategy())
def test_diff_of_identical_generated_snapshots_is_empty(snapshot: Database) -> None:
    assert _diff(snapshot, snapshot.model_copy(deep=True)).deltas == ()


@pytest.mark.unit
@settings(max_examples=500)
@given(source=_database_strategy(min_schemas=2))
def test_ordered_diff_is_stable_when_catalog_collections_are_reversed(
    source: Database,
) -> None:
    target = _change_column_types(source)

    original_order = _diff(source, target)
    reversed_order = _diff(_reverse_catalog_order(source), _reverse_catalog_order(target))

    assert len(original_order.deltas) >= 2
    assert reversed_order.deltas == original_order.deltas
