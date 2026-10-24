from collections.abc import Iterable

import pytest
from syrupy.assertion import SnapshotAssertion

from pgschemadiff.application.sql_emit.column_emitter import (
    handlers,
    render_column_definition,
)
from pgschemadiff.application.sql_emit.emitter import SqlStatement
from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.delta.base import DeltaBase
from pgschemadiff.domain.delta.column import (
    AddColumn,
    AlterColumnType,
    DropColumn,
    RenameColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.shared.errors import MigrationError


def _table_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="Sales", name='Order"Items'),
    )


def _column_ref(name: str = "display") -> ObjectRef:
    parent = _table_ref()
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=parent.qname.namespace, name=name),
        parent=parent,
    )


def _column(
    name: str = "display",
    *,
    nullable: bool = True,
    default_expr: str | None = None,
    collation: str | None = None,
    identity: IdentitySpec | None = None,
    generated_expression: str | None = None,
) -> Column:
    return Column(
        name=name,
        position=1,
        data_type="integer",
        nullable=nullable,
        default_expr=default_expr,
        collation=collation,
        identity=identity,
        generated_expression=generated_expression,
    )


def _assert_emitted(
    statements: Iterable[SqlStatement], delta: DeltaBase, count: int
) -> tuple[SqlStatement, ...]:
    result = tuple(statements)
    assert len(result) == count
    assert all(statement.transactional is True for statement in result)
    assert all(statement.delta is delta for statement in result)
    return result


def test_handlers_cover_exact_column_delta_types() -> None:
    assert set(handlers()) == {
        AddColumn,
        DropColumn,
        AlterColumnType,
        SetColumnDefault,
        SetColumnNullability,
        RenameColumn,
    }


def test_add_column_renders_shared_definition(snapshot: SnapshotAssertion) -> None:
    column = Column(
        name='Display "name',
        position=1,
        data_type="character varying(50)",
        nullable=False,
        default_expr="'it''s'",
        collation='"C"',
    )
    delta = AddColumn(target=_column_ref(column.name), column=column)

    statements = _assert_emitted(handlers()[AddColumn](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_add_identity_column_omits_implicit_not_null_and_default_options(
    snapshot: SnapshotAssertion,
) -> None:
    column = Column(
        name="generated_id",
        position=1,
        data_type="bigint",
        nullable=False,
        identity=IdentitySpec(generated=GeneratedTiming.ALWAYS),
    )
    delta = AddColumn(target=_column_ref(column.name), column=column)

    statements = _assert_emitted(handlers()[AddColumn](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_drop_column(snapshot: SnapshotAssertion) -> None:
    delta = DropColumn(target=_column_ref(), column=_column())

    statements = _assert_emitted(handlers()[DropColumn](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.parametrize(
    ("new_collation", "using_expression"),
    [('"C"', '"display"::bigint'), (None, None)],
    ids=["collation-and-using", "implicit-cast"],
)
def test_alter_column_type(
    new_collation: str | None,
    using_expression: str | None,
    snapshot: SnapshotAssertion,
) -> None:
    delta = AlterColumnType(
        target=_column_ref(),
        new_data_type="bigint",
        new_collation=new_collation,
        using_expression=using_expression,
    )

    statements = _assert_emitted(handlers()[AlterColumnType](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.parametrize(
    "new_default",
    ["'it''s ready'::text", None],
    ids=["set-default", "drop-default"],
)
def test_set_column_default(new_default: str | None, snapshot: SnapshotAssertion) -> None:
    delta = SetColumnDefault(target=_column_ref(), new_default=new_default)

    statements = _assert_emitted(handlers()[SetColumnDefault](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.parametrize("nullable", [False, True], ids=["set-not-null", "drop-not-null"])
def test_set_column_nullability(nullable: bool, snapshot: SnapshotAssertion) -> None:
    delta = SetColumnNullability(target=_column_ref(), nullable=nullable)

    statements = _assert_emitted(handlers()[SetColumnNullability](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_rename_column(snapshot: SnapshotAssertion) -> None:
    delta = RenameColumn(
        target=_column_ref('old"name'),
        old_name='old"name',
        new_name='new"name',
    )

    statements = _assert_emitted(handlers()[RenameColumn](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.parametrize(
    "delta_type",
    [
        AddColumn,
        DropColumn,
        AlterColumnType,
        SetColumnDefault,
        SetColumnNullability,
        RenameColumn,
    ],
)
def test_column_handlers_reject_wrong_delta_types(delta_type: type[DeltaBase]) -> None:
    wrong_delta: DeltaBase
    if delta_type is SetColumnNullability:
        wrong_delta = AddColumn(target=_column_ref(), column=_column())
    else:
        wrong_delta = SetColumnNullability(target=_column_ref(), nullable=False)

    with pytest.raises(MigrationError):
        handlers()[delta_type](wrong_delta)


@pytest.mark.parametrize(
    ("identity", "generated_expression", "default_expr"),
    [
        (IdentitySpec(generated=GeneratedTiming.ALWAYS), None, "1"),
        (IdentitySpec(generated=GeneratedTiming.ALWAYS), "1", None),
        (None, "1", "2"),
    ],
    ids=["identity-and-default", "identity-and-generated", "generated-and-default"],
)
def test_column_renderer_rejects_contradictory_definitions(
    identity: IdentitySpec | None,
    generated_expression: str | None,
    default_expr: str | None,
) -> None:
    column = Column.model_construct(
        name="display",
        position=1,
        data_type="integer",
        identity=identity,
        generated_expression=generated_expression,
        default_expr=default_expr,
    )
    with pytest.raises(MigrationError):
        render_column_definition(column)


@pytest.mark.parametrize(
    "column",
    [
        Column(name="display", position=1, data_type="?"),
        Column(name="display", position=1, data_type="  "),
        Column(name="display", position=1, data_type="text", default_expr="?"),
        Column(name="display", position=1, data_type="text", default_expr="  "),
        Column(
            name="display",
            position=1,
            data_type="text",
            generated_expression="?",
        ),
        Column(
            name="display",
            position=1,
            data_type="text",
            generated_expression="  ",
        ),
    ],
    ids=[
        "type-placeholder",
        "type-blank",
        "default-placeholder",
        "default-blank",
        "generated-placeholder",
        "generated-blank",
    ],
)
def test_add_column_rejects_missing_or_placeholder_fragments(column: Column) -> None:
    delta = AddColumn(target=_column_ref(column.name), column=column)

    with pytest.raises(MigrationError):
        handlers()[AddColumn](delta)


@pytest.mark.parametrize(
    "delta",
    [
        AlterColumnType(target=_column_ref(), new_data_type="?"),
        AlterColumnType(target=_column_ref(), new_data_type="  "),
        AlterColumnType(target=_column_ref(), new_data_type="bigint", using_expression="?"),
        AlterColumnType(target=_column_ref(), new_data_type="bigint", using_expression="  "),
        SetColumnDefault(target=_column_ref(), new_default="?"),
        SetColumnDefault(target=_column_ref(), new_default="  "),
    ],
    ids=[
        "type-placeholder",
        "type-blank",
        "using-placeholder",
        "using-blank",
        "default-placeholder",
        "default-blank",
    ],
)
def test_column_handlers_reject_placeholder_fragments(delta: DeltaBase) -> None:
    delta_type = type(delta)

    with pytest.raises(MigrationError):
        handlers()[delta_type](delta)


def test_column_handler_rejects_invalid_identifier() -> None:
    column = _column("bad\x00name")
    delta = AddColumn(target=_column_ref(column.name), column=column)

    with pytest.raises(MigrationError):
        handlers()[AddColumn](delta)


def test_column_handler_rejects_blank_collation_fragment() -> None:
    column = _column(collation=" ")
    delta = AddColumn(target=_column_ref(), column=column)

    with pytest.raises(MigrationError):
        handlers()[AddColumn](delta)


def test_column_handler_rejects_missing_parent_table() -> None:
    target = ObjectRef.model_construct(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="Sales", name="display"),
        parent=None,
    )
    delta = AddColumn.model_construct(target=target, column=_column())

    with pytest.raises(MigrationError):
        handlers()[AddColumn](delta)
