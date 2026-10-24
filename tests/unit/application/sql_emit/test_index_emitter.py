from collections.abc import Iterable

import pytest
from syrupy.assertion import SnapshotAssertion

from pgschemadiff.application.sql_emit.emitter import SqlStatement
from pgschemadiff.application.sql_emit.index_emitter import handlers
from pgschemadiff.domain.delta.base import DeltaBase
from pgschemadiff.domain.delta.index import CreateIndex, DropIndex, ReplaceIndex
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.shared.errors import MigrationError


def _table_ref(namespace: str = "Sales", name: str = 'Order"Items') -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _index(
    name: str = 'Search"Idx',
    *,
    table_ref: ObjectRef | None = None,
    definition: str | None = None,
    unique: bool = False,
    comment: str | None = None,
    constraint_name: str | None = None,
) -> Index:
    table = table_ref or _table_ref()
    return Index(
        ref=ObjectRef(
            kind=ObjectKind.INDEX,
            qname=QualifiedName(namespace=table.qname.namespace, name=name),
        ),
        table_ref=table,
        method=IndexMethod.BTREE,
        key_columns=(IndexKeyColumn(column_name="display"),),
        unique=unique,
        definition=definition,
        comment=comment,
        constraint_name=constraint_name,
    )


def _assert_emitted(
    statements: Iterable[SqlStatement],
    delta: DeltaBase,
    transactional: tuple[bool, ...],
) -> tuple[SqlStatement, ...]:
    result = tuple(statements)
    assert tuple(statement.transactional for statement in result) == transactional
    assert all(statement.delta is delta for statement in result)
    assert all(statement.new_unit is False for statement in result)
    return result


def test_index_handlers_cover_exact_delta_types() -> None:
    assert set(handlers()) == {CreateIndex, DropIndex, ReplaceIndex}


def test_create_partial_include_index_and_comment(snapshot: SnapshotAssertion) -> None:
    index = _index(
        definition=(
            'CREATE INDEX "Search""Idx" ON "Sales"."Order""Items" USING btree '
            '("display" DESC NULLS FIRST) INCLUDE ("cover") WHERE (active = true)'
        ),
        comment="it's ready",
    )
    delta = CreateIndex(target=index.ref, index=index)

    statements = _assert_emitted(handlers()[CreateIndex](delta), delta, (False, True))

    assert tuple(statement.sql for statement in statements) == snapshot


def test_create_unique_index(snapshot: SnapshotAssertion) -> None:
    index = _index(
        name="UniqueEmail",
        definition=(
            'CREATE UNIQUE INDEX "UniqueEmail" ON "Sales"."Order""Items" USING btree ("email")'
        ),
        unique=True,
    )
    delta = CreateIndex(target=index.ref, index=index)

    statements = _assert_emitted(handlers()[CreateIndex](delta), delta, (False,))

    assert tuple(statement.sql for statement in statements) == snapshot


def test_create_index_accepts_unquoted_lowercase_table_reference() -> None:
    table_ref = _table_ref("sales", "orders")
    index = _index(
        "orders_idx",
        table_ref=table_ref,
        definition="CREATE INDEX orders_idx ON sales.orders USING btree (id)",
    )
    delta = CreateIndex(target=index.ref, index=index)

    statements = tuple(handlers()[CreateIndex](delta))

    assert statements[0].sql == (
        "CREATE INDEX CONCURRENTLY orders_idx ON sales.orders USING btree (id)"
    )


def test_create_index_accepts_unquoted_lowercase_unicode_table_reference() -> None:
    table_ref = _table_ref("équipe", "orders")
    index = _index(
        table_ref=table_ref,
        definition="CREATE INDEX orders_idx ON équipe.orders USING btree (id)",
    )
    delta = CreateIndex(target=index.ref, index=index)

    statements = tuple(handlers()[CreateIndex](delta))

    assert statements[0].sql == (
        "CREATE INDEX CONCURRENTLY orders_idx ON équipe.orders USING btree (id)"
    )


def test_create_index_rejects_unquoted_caseful_non_ascii_table_reference() -> None:
    table_ref = _table_ref("Équipe", "Orders")
    index = _index(
        table_ref=table_ref,
        definition='CREATE INDEX "Search""Idx" ON Équipe."Orders" USING btree ("display")',
    )
    delta = CreateIndex(target=index.ref, index=index)

    with pytest.raises(MigrationError):
        handlers()[CreateIndex](delta)


def test_drop_index(snapshot: SnapshotAssertion) -> None:
    index = _index()
    delta = DropIndex(target=index.ref, index=index)

    statements = _assert_emitted(handlers()[DropIndex](delta), delta, (False,))

    assert tuple(statement.sql for statement in statements) == snapshot


def test_replace_index(snapshot: SnapshotAssertion) -> None:
    old_index = _index(
        definition=('CREATE INDEX "Search""Idx" ON "Sales"."Order""Items" USING btree ("display")')
    )
    new_index = old_index.model_copy(
        update={
            "definition": (
                'CREATE INDEX "Search""Idx" ON "Sales"."Order""Items" USING btree ("display" DESC)'
            ),
            "comment": "rebuilt",
        }
    )
    delta = ReplaceIndex(target=new_index.ref, old_index=old_index, new_index=new_index)

    statements = _assert_emitted(handlers()[ReplaceIndex](delta), delta, (False, False, True))

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.parametrize(
    "delta_type",
    [CreateIndex, DropIndex, ReplaceIndex],
    ids=["create", "drop", "replace"],
)
def test_index_handlers_reject_wrong_delta_types(delta_type: type[DeltaBase]) -> None:
    index = _index(
        definition=('CREATE INDEX "Search""Idx" ON "Sales"."Order""Items" USING btree ("display")')
    )
    wrong_delta: DeltaBase = (
        DropIndex(target=index.ref, index=index)
        if delta_type is not DropIndex
        else CreateIndex(target=index.ref, index=index)
    )

    with pytest.raises(MigrationError):
        handlers()[delta_type](wrong_delta)


@pytest.mark.parametrize(
    "definition", [None, "", "  ", "?"], ids=["none", "empty", "blank", "sentinel"]
)
def test_create_index_rejects_missing_definition(definition: str | None) -> None:
    index = _index(definition=definition)
    delta = CreateIndex(target=index.ref, index=index)

    with pytest.raises(MigrationError):
        handlers()[CreateIndex](delta)


@pytest.mark.parametrize(
    "definition",
    [
        'CREATE INDEX "Search""Idx" ON "Order""Items" USING btree ("display")',
        'CREATE INDEX "Search""Idx" ON "Other"."Order""Items" USING btree ("display")',
        'CREATE INDEX "Search""Idx" ON "Sales"."Wrong" USING btree ("display")',
        'CREATE INDEX "Search""Idx" ON Sales."Order""Items" USING btree ("display")',
        'CREATE INDEX "Search""Idx" ON "Sales"."Order""Items"extra USING btree ("display")',
    ],
    ids=[
        "unqualified",
        "wrong-schema",
        "wrong-table",
        "unquoted-case-fold-mismatch",
        "table-name-prefix-collision",
    ],
)
def test_create_index_rejects_unqualified_or_wrong_table_reference(definition: str) -> None:
    index = _index(definition=definition)
    delta = CreateIndex(target=index.ref, index=index)

    with pytest.raises(MigrationError):
        handlers()[CreateIndex](delta)


@pytest.mark.parametrize(
    "definition",
    [
        ' create index "Search""Idx" ON "Sales"."Order""Items" USING btree ("display")',
        'CREATE INDEX CONCURRENTLY "Search""Idx" ON "Sales"."Order""Items" USING btree ("display")',
        (
            'CREATE UNIQUE INDEX CONCURRENTLY "Search""Idx" ON "Sales"."Order""Items" '
            'USING btree ("display")'
        ),
        'ALTER INDEX "Search""Idx" ON "Sales"."Order""Items"',
        "CREATE INDEX ",
    ],
    ids=[
        "leading-space",
        "already-concurrent",
        "unique-already-concurrent",
        "other-prefix",
        "missing-index-name",
    ],
)
def test_create_index_rejects_non_catalog_prefix(definition: str) -> None:
    index = _index(definition=definition)
    delta = CreateIndex(target=index.ref, index=index)

    with pytest.raises(MigrationError):
        handlers()[CreateIndex](delta)


@pytest.mark.parametrize(
    ("delta_type", "old_owned", "new_owned"),
    [
        (CreateIndex, False, True),
        (DropIndex, True, False),
        (ReplaceIndex, True, False),
        (ReplaceIndex, False, True),
    ],
    ids=["create-owned", "drop-owned", "replace-old-owned", "replace-new-owned"],
)
def test_index_handlers_reject_constraint_backed_indexes(
    delta_type: type[DeltaBase], old_owned: bool, new_owned: bool
) -> None:
    definition = 'CREATE INDEX "Search""Idx" ON "Sales"."Order""Items" USING btree ("display")'
    old_index = _index(
        definition=definition,
        constraint_name="pk_orders" if old_owned else None,
    )
    new_index = old_index.model_copy(
        update={
            "definition": definition + " ",
            "constraint_name": "pk_orders" if new_owned else None,
        }
    )
    if delta_type is CreateIndex:
        delta: DeltaBase = CreateIndex(target=new_index.ref, index=new_index)
    elif delta_type is DropIndex:
        delta = DropIndex(target=old_index.ref, index=old_index)
    else:
        delta = ReplaceIndex(target=new_index.ref, old_index=old_index, new_index=new_index)

    with pytest.raises(MigrationError):
        handlers()[delta_type](delta)


def test_create_index_rejects_invalid_comment_literal() -> None:
    index = _index(
        definition=('CREATE INDEX "Search""Idx" ON "Sales"."Order""Items" USING btree ("display")'),
        comment="invalid\x00comment",
    )
    delta = CreateIndex(target=index.ref, index=index)

    with pytest.raises(MigrationError):
        handlers()[CreateIndex](delta)


def test_drop_index_rejects_invalid_identifier() -> None:
    index = _index(name="bad\x00name")
    delta = DropIndex(target=index.ref, index=index)

    with pytest.raises(MigrationError):
        handlers()[DropIndex](delta)
