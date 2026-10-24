from collections.abc import Iterable

import pytest
from syrupy.assertion import SnapshotAssertion

from pgschemadiff.application.sql_emit.emitter import SqlStatement
from pgschemadiff.application.sql_emit.schema_emitter import handlers
from pgschemadiff.domain.delta import (
    AlterExtension,
    CreateExtension,
    CreateSchema,
    DeltaBase,
    DropExtension,
    DropSchema,
)
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.shared.errors import MigrationError


def _schema_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )


def _extension_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.EXTENSION,
        qname=QualifiedName(namespace="public", name=name),
    )


def _assert_emitted(
    statements: Iterable[SqlStatement], delta: DeltaBase, count: int
) -> tuple[SqlStatement, ...]:
    result = tuple(statements)
    assert len(result) == count
    assert all(statement.transactional is True for statement in result)
    assert all(statement.new_unit is False for statement in result)
    assert all(statement.delta is delta for statement in result)
    return result


def test_schema_handlers_cover_exact_delta_types() -> None:
    assert set(handlers()) == {
        CreateSchema,
        DropSchema,
        CreateExtension,
        DropExtension,
        AlterExtension,
    }


def test_schema_and_extension_statements(snapshot: SnapshotAssertion) -> None:
    schema_ref = _schema_ref("Accounting Data")
    created_schema = CreateSchema(
        target=schema_ref,
        pg_schema=Schema(
            ref=schema_ref,
            owner="Migration Owner",
            comment="Owner's namespace",
        ),
    )
    dropped_schema_ref = _schema_ref("old")
    dropped_schema = DropSchema(
        target=dropped_schema_ref,
        pg_schema=Schema(ref=dropped_schema_ref),
    )

    extension_ref = _extension_ref('Geo"Tools')
    created_extension = CreateExtension(
        target=extension_ref,
        extension=Extension(
            ref=extension_ref,
            version="3.4'beta",
            installed_schema="Extensions",
            comment="Coordinate's system",
        ),
    )
    dropped_extension_ref = _extension_ref("unused")
    dropped_extension = DropExtension(
        target=dropped_extension_ref,
        extension=Extension(ref=dropped_extension_ref, version="1.0"),
    )
    altered_extension = AlterExtension(
        target=_extension_ref('Ext"Name'),
        new_version="2.0",
        new_schema="app",
    )

    deltas = (
        created_schema,
        dropped_schema,
        created_extension,
        dropped_extension,
        altered_extension,
    )
    statements = tuple(
        statement for delta in deltas for statement in handlers()[type(delta)](delta)
    )

    assert all(statement.transactional is True for statement in statements)
    assert all(statement.new_unit is False for statement in statements)
    assert tuple(statement.delta for statement in statements) == (
        created_schema,
        created_schema,
        dropped_schema,
        created_extension,
        created_extension,
        dropped_extension,
        altered_extension,
        altered_extension,
    )
    assert tuple(statement.sql for statement in statements) == snapshot


def test_create_schema_omits_absent_optional_clauses() -> None:
    ref = _schema_ref("plain")
    delta = CreateSchema(target=ref, pg_schema=Schema(ref=ref))

    (statement,) = _assert_emitted(handlers()[CreateSchema](delta), delta, 1)

    assert statement.sql == 'CREATE SCHEMA "plain"'


def test_create_extension_pins_version_and_omits_absent_optional_clauses() -> None:
    ref = _extension_ref("hstore")
    delta = CreateExtension(
        target=ref,
        extension=Extension(ref=ref, version="1.8"),
    )

    (statement,) = _assert_emitted(handlers()[CreateExtension](delta), delta, 1)

    assert statement.sql == "CREATE EXTENSION \"hstore\" VERSION '1.8'"


@pytest.mark.parametrize(
    ("new_version", "new_schema", "expected"),
    [
        (
            "2.0",
            "target",
            (
                "ALTER EXTENSION \"ext\" UPDATE TO '2.0'",
                'ALTER EXTENSION "ext" SET SCHEMA "target"',
            ),
        ),
        ("2.0", None, ("ALTER EXTENSION \"ext\" UPDATE TO '2.0'",)),
        (None, "target", ('ALTER EXTENSION "ext" SET SCHEMA "target"',)),
    ],
    ids=["update-before-relocate", "update-only", "relocate-only"],
)
def test_alter_extension_emits_only_requested_clauses(
    new_version: str | None,
    new_schema: str | None,
    expected: tuple[str, ...],
) -> None:
    delta = AlterExtension(
        target=_extension_ref("ext"),
        new_version=new_version,
        new_schema=new_schema,
    )

    statements = _assert_emitted(handlers()[AlterExtension](delta), delta, len(expected))

    assert tuple(statement.sql for statement in statements) == expected


def test_alter_extension_rejects_no_clauses() -> None:
    delta = AlterExtension.model_construct(
        target=_extension_ref("ext"),
        new_version=None,
        new_schema=None,
    )

    with pytest.raises(MigrationError, match="no clauses"):
        handlers()[AlterExtension](delta)


@pytest.mark.parametrize(
    ("handler_type", "wrong_delta"),
    [
        (
            CreateSchema,
            DropSchema(target=_schema_ref("s"), pg_schema=Schema(ref=_schema_ref("s"))),
        ),
        (
            DropSchema,
            CreateSchema(target=_schema_ref("s"), pg_schema=Schema(ref=_schema_ref("s"))),
        ),
        (
            CreateExtension,
            DropExtension(
                target=_extension_ref("ext"),
                extension=Extension(ref=_extension_ref("ext"), version="1"),
            ),
        ),
        (
            DropExtension,
            CreateExtension(
                target=_extension_ref("ext"),
                extension=Extension(ref=_extension_ref("ext"), version="1"),
            ),
        ),
        (
            AlterExtension,
            CreateSchema(target=_schema_ref("s"), pg_schema=Schema(ref=_schema_ref("s"))),
        ),
    ],
    ids=["create-schema", "drop-schema", "create-extension", "drop-extension", "alter-extension"],
)
def test_schema_handlers_reject_wrong_delta_type(
    handler_type: type[DeltaBase], wrong_delta: DeltaBase
) -> None:
    with pytest.raises(MigrationError):
        handlers()[handler_type](wrong_delta)
