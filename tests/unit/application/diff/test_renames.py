"""Tests for the typed rename annotation contract."""

from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.column import ColumnComparator
from pgschemadiff.application.diff.comparators.constraint import ConstraintComparator
from pgschemadiff.application.diff.comparators.index import IndexComparator
from pgschemadiff.application.diff.comparators.table import TableComparator
from pgschemadiff.application.diff.engine import DiffEngine
from pgschemadiff.application.diff.renames import RenameAnnotations
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import UniqueConstraint
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import (
    AlterColumnType,
    CreateTable,
    DropTable,
    RenameColumn,
    RenameTable,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import PartitionOf, Table
from pgschemadiff.shared.errors import DiffError


def _document(*entries: dict[str, str]) -> dict[str, object]:
    return {"renames": list(entries)}


def _table(
    name: str,
    *columns: str,
    data_type: str = "text",
    constraints: tuple[UniqueConstraint, ...] = (),
    partition_of: PartitionOf | None = None,
) -> Table:
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name=name),
    )
    return Table(
        ref=table_ref,
        columns=tuple(
            Column(name=column, position=position, data_type=data_type, nullable=False)
            for position, column in enumerate(columns, start=1)
        ),
        constraints=constraints,
        partition_of=partition_of,
    )


def _database(*tables: Table, indexes: tuple[Index, ...] = ()) -> Database:
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    return Database(
        name="test",
        schemas=(Schema(ref=schema_ref, tables=tuple(tables), indexes=indexes),),
    )


def test_parse_table_and_column_annotations() -> None:
    annotations = RenameAnnotations.from_document(
        _document(
            {"kind": "table", "from": "public.user_account", "to": "public.users"},
            {
                "kind": "column",
                "from": "public.users.email_addr",
                "to": "public.users.email",
            },
        )
    )

    assert annotations.tables[0].source == QualifiedName(namespace="public", name="user_account")
    assert annotations.tables[0].target == QualifiedName(namespace="public", name="users")
    assert annotations.columns[0].source_table == QualifiedName(namespace="public", name="users")
    assert annotations.columns[0].source_name == "email_addr"
    assert annotations.columns[0].target_name == "email"


def test_parse_quoted_identifiers_with_dots_and_escaped_quotes() -> None:
    annotations = RenameAnnotations.from_document(
        _document(
            {
                "kind": "column",
                "from": '"Sales.Region"."User.Table"."Email""Address"',
                "to": '"Sales.Region"."User.Table"."Email"',
            }
        )
    )

    rename = annotations.columns[0]
    assert rename.source_table == QualifiedName(namespace="Sales.Region", name="User.Table")
    assert rename.source_name == 'Email"Address'
    assert rename.target_name == "Email"


def test_unquoted_identifiers_follow_postgres_lowercase_folding() -> None:
    annotations = RenameAnnotations.from_document(
        _document({"kind": "table", "from": "Public.OldName", "to": "Public.NewName"})
    )

    assert annotations.tables[0].source == QualifiedName(namespace="public", name="oldname")
    assert annotations.tables[0].target == QualifiedName(namespace="public", name="newname")


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"renames": {}},
        {"renames": [{"kind": "view", "from": "public.old", "to": "public.new"}]},
        {"renames": [{"kind": "table", "from": "public.old", "to": "public.new", "x": 1}]},
        {"renames": [{"kind": "table", "from": "public.old", "to": "public"}]},
        {"renames": [{"kind": "table", "from": "public.bad-name", "to": "public.new"}]},
        {"renames": [{"kind": "table", "from": "public.1bad", "to": "public.new"}]},
        {"renames": [{"kind": "table", "from": "public.old", "to": "public.old"}]},
        {
            "renames": [
                {"kind": "table", "from": "public.a", "to": "public.c"},
                {"kind": "table", "from": "public.b", "to": "public.c"},
            ]
        },
        {
            "renames": [
                {"kind": "table", "from": "public.a", "to": "public.b"},
                {"kind": "table", "from": "public.b", "to": "public.a"},
            ]
        },
    ],
)
def test_reject_invalid_annotation_documents(document: dict[str, object]) -> None:
    with pytest.raises(DiffError):
        RenameAnnotations.from_document(document)


def test_reject_duplicate_column_sources() -> None:
    with pytest.raises(DiffError):
        RenameAnnotations.from_document(
            _document(
                {"kind": "column", "from": "public.t.a", "to": "public.t.b"},
                {"kind": "column", "from": "public.t.a", "to": "public.t.c"},
            )
        )


def test_diff_pairs_explicit_table_and_column_renames() -> None:
    source = _database(_table("user_account", "email_addr"))
    target = _database(_table("users", "email", data_type="varchar"))
    annotations = RenameAnnotations.from_document(
        _document(
            {"kind": "table", "from": "public.user_account", "to": "public.users"},
            {
                "kind": "column",
                "from": "public.user_account.email_addr",
                "to": "public.users.email",
            },
        )
    )
    engine = DiffEngine([TableComparator(column_comparator=ColumnComparator())])

    result = engine.diff(source, target, renames=annotations)

    table_delta = next(delta for delta in result if isinstance(delta, RenameTable))
    column_delta = next(delta for delta in result if isinstance(delta, RenameColumn))
    assert table_delta.old_name == QualifiedName(namespace="public", name="user_account")
    assert table_delta.new_name == QualifiedName(namespace="public", name="users")
    assert column_delta.target.parent == table_delta.target
    assert column_delta.old_name == "email_addr"
    assert column_delta.new_name == "email"
    type_delta = next(delta for delta in result if isinstance(delta, AlterColumnType))
    assert type_delta.target.parent is not None
    assert type_delta.target.parent.qname == QualifiedName(namespace="public", name="users")
    assert type_delta.target.qname.name == "email"
    assert not any(isinstance(delta, (CreateTable, DropTable)) for delta in result)


def test_diff_without_annotations_keeps_create_drop_behavior() -> None:
    source = _database(_table("user_account", "email_addr"))
    target = _database(_table("users", "email"))
    engine = DiffEngine([TableComparator(column_comparator=ColumnComparator())])

    result = engine.diff(source, target)

    assert {type(delta) for delta in result} == {CreateTable, DropTable}


def test_diff_rejects_rename_endpoint_missing_from_snapshot() -> None:
    source = _database()
    target = _database(_table("users", "email"))
    annotations = RenameAnnotations.from_document(
        _document({"kind": "table", "from": "public.user_account", "to": "public.users"})
    )
    engine = DiffEngine([TableComparator(column_comparator=ColumnComparator())])

    with pytest.raises(DiffError, match="source table"):
        engine.diff(source, target, renames=annotations)


def test_diff_rejects_destination_table_collision() -> None:
    source = _database(_table("user_account", "email_addr"), _table("users", "id"))
    target = _database(_table("users", "email"))
    annotations = RenameAnnotations.from_document(
        _document({"kind": "table", "from": "public.user_account", "to": "public.users"})
    )
    engine = DiffEngine([TableComparator(column_comparator=ColumnComparator())])

    with pytest.raises(DiffError, match="already exists in source"):
        engine.diff(source, target, renames=annotations)


def test_diff_rejects_missing_column_endpoint() -> None:
    source = _database(_table("users", "email_addr"))
    target = _database(_table("users", "email"))
    annotations = RenameAnnotations.from_document(
        _document(
            {
                "kind": "column",
                "from": "public.users.missing",
                "to": "public.users.email",
            }
        )
    )
    engine = DiffEngine([TableComparator(column_comparator=ColumnComparator())])

    with pytest.raises(DiffError, match="source column"):
        engine.diff(source, target, renames=annotations)


def test_diff_rejects_column_destination_collision() -> None:
    source = _database(_table("users", "email_addr", "email"))
    target = _database(_table("users", "email"))
    annotations = RenameAnnotations.from_document(
        _document(
            {
                "kind": "column",
                "from": "public.users.email_addr",
                "to": "public.users.email",
            }
        )
    )
    engine = DiffEngine([TableComparator(column_comparator=ColumnComparator())])

    with pytest.raises(DiffError, match="already exists in source"):
        engine.diff(source, target, renames=annotations)


def test_column_rename_does_not_replace_dependent_index_or_unique_constraint() -> None:
    source_table = _table(
        "users",
        "email_addr",
        constraints=(UniqueConstraint(name="users_email_key", columns=("email_addr",)),),
    )
    target_table = _table(
        "users",
        "email",
        constraints=(UniqueConstraint(name="users_email_key", columns=("email",)),),
    )
    index_ref = ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace="public", name="users_email_idx"),
    )
    source_index = Index(
        ref=index_ref,
        table_ref=source_table.ref,
        key_columns=(IndexKeyColumn(column_name="email_addr"),),
    )
    target_index = Index(
        ref=index_ref,
        table_ref=target_table.ref,
        key_columns=(IndexKeyColumn(column_name="email"),),
    )
    source = _database(source_table, indexes=(source_index,))
    target = _database(target_table, indexes=(target_index,))
    annotations = RenameAnnotations.from_document(
        _document(
            {
                "kind": "column",
                "from": "public.users.email_addr",
                "to": "public.users.email",
            }
        )
    )
    engine = DiffEngine(
        [
            IndexComparator(),  # type: ignore[list-item]
            TableComparator(
                column_comparator=ColumnComparator(),
                constraint_comparator=ConstraintComparator(),
            ),
        ]
    )

    result = engine.diff(source, target, renames=annotations)

    deltas = tuple(result)
    assert len(deltas) == 1
    assert isinstance(deltas[0], RenameColumn)


def test_table_rename_normalizes_partition_parent_reference() -> None:
    source_parent = _table("old_parent", "id")
    target_parent = _table("new_parent", "id")
    source_child = _table(
        "child",
        "id",
        partition_of=PartitionOf(parent_namespace="public", parent_name="old_parent"),
    )
    target_child = _table(
        "child",
        "id",
        partition_of=PartitionOf(parent_namespace="public", parent_name="new_parent"),
    )
    annotations = RenameAnnotations.from_document(
        _document({"kind": "table", "from": "public.old_parent", "to": "public.new_parent"})
    )
    engine = DiffEngine(
        [
            TableComparator(
                column_comparator=ColumnComparator(),
                constraint_comparator=ConstraintComparator(),
            )
        ]
    )

    result = engine.diff(
        _database(source_parent, source_child),
        _database(target_parent, target_child),
        renames=annotations,
    )

    deltas = tuple(result)
    assert len(deltas) == 1
    assert isinstance(deltas[0], RenameTable)


def test_table_rename_pairs_indexes_by_explicit_parent_mapping() -> None:
    source_table = _table("old_parent", "old_id")
    target_table = _table("new_parent", "id")
    index_name = "parent_key_idx"
    index_ref = ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace="public", name=index_name),
    )
    source_index = Index(
        ref=index_ref,
        table_ref=source_table.ref,
        key_columns=(IndexKeyColumn(column_name="old_id"),),
    )
    target_index = Index(
        ref=index_ref,
        table_ref=target_table.ref,
        key_columns=(IndexKeyColumn(column_name="id"),),
    )
    annotations = RenameAnnotations.from_document(
        _document(
            {"kind": "table", "from": "public.old_parent", "to": "public.new_parent"},
            {
                "kind": "column",
                "from": "public.old_parent.old_id",
                "to": "public.new_parent.id",
            },
        )
    )
    engine = DiffEngine(
        [
            IndexComparator(),  # type: ignore[list-item]
            TableComparator(
                column_comparator=ColumnComparator(),
                constraint_comparator=ConstraintComparator(),
            ),
        ]
    )

    result = engine.diff(
        _database(source_table, indexes=(source_index,)),
        _database(target_table, indexes=(target_index,)),
        renames=annotations,
    )

    deltas = tuple(result)
    assert len(deltas) == 2
    assert sum(isinstance(delta, RenameTable) for delta in deltas) == 1
    assert sum(isinstance(delta, RenameColumn) for delta in deltas) == 1
