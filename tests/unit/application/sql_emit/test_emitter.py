from dataclasses import FrozenInstanceError

import pytest

from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlStatement
from pgschemadiff.domain.delta import (
    CreateSchema,
    DeltaBase,
    DeltaSet,
    DropSchema,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.shared.errors import MigrationError


def _schema_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )


_CREATE_REF = _schema_ref("created")
_DROP_REF = _schema_ref("removed")
_CREATE = CreateSchema(target=_CREATE_REF, pg_schema=Schema(ref=_CREATE_REF))
_DROP = DropSchema(target=_DROP_REF, pg_schema=Schema(ref=_DROP_REF))


def _emit_create(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    return (
        SqlStatement(sql="statement-z", transactional=True, delta=delta),
        SqlStatement(sql="statement-a", transactional=False, delta=delta),
    )


def _emit_drop(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    return (SqlStatement(sql="statement-c", transactional=True, delta=delta),)


def _emit_nothing(_delta: DeltaBase) -> tuple[SqlStatement, ...]:
    return ()


def _emit_wrong_provenance(_delta: DeltaBase) -> tuple[SqlStatement, ...]:
    return (SqlStatement(sql="SELECT 1;", transactional=True, delta=_DROP),)


def test_emitter_preserves_delta_and_statement_order() -> None:
    deltas = DeltaSet.from_iterable((_DROP, _CREATE))
    emitter = SqlEmitter({CreateSchema: _emit_create, DropSchema: _emit_drop})

    statements = emitter.emit(deltas)

    assert tuple(statement.sql for statement in statements) == (
        "statement-c",
        "statement-z",
        "statement-a",
    )
    assert tuple(statement.transactional for statement in statements) == (True, True, False)
    assert tuple(statement.delta for statement in statements) == (_DROP, _CREATE, _CREATE)
    assert statements[0].delta is _DROP
    assert deltas.deltas == (_DROP, _CREATE)


def test_empty_delta_set_emits_no_statements() -> None:
    assert SqlEmitter({}).emit(DeltaSet()) == ()


def test_missing_handler_raises_migration_error() -> None:
    with pytest.raises(MigrationError, match="CreateSchema"):
        SqlEmitter({}).emit(DeltaSet.from_iterable((_CREATE,)))


class DerivedCreateSchema(CreateSchema):
    pass


def test_subclass_does_not_fall_back_to_parent_handler() -> None:
    derived = DerivedCreateSchema(target=_CREATE.target, pg_schema=_CREATE.pg_schema)
    emitter = SqlEmitter({CreateSchema: _emit_create})

    with pytest.raises(MigrationError, match="DerivedCreateSchema"):
        emitter.emit(DeltaSet.from_iterable((derived,)))


def test_handler_must_emit_at_least_one_statement() -> None:
    with pytest.raises(MigrationError, match="no statements"):
        SqlEmitter({CreateSchema: _emit_nothing}).emit(DeltaSet.from_iterable((_CREATE,)))


def test_handler_cannot_attribute_statement_to_another_delta() -> None:
    with pytest.raises(MigrationError, match="provenance"):
        SqlEmitter({CreateSchema: _emit_wrong_provenance}).emit(DeltaSet.from_iterable((_CREATE,)))


def test_statement_rejects_blank_sql_and_is_frozen() -> None:
    with pytest.raises(MigrationError, match="blank"):
        SqlStatement(sql="  ", transactional=True, delta=_CREATE)

    statement = SqlStatement(sql="SELECT 1;", transactional=True, delta=_CREATE)
    with pytest.raises(FrozenInstanceError):
        statement.sql = "SELECT 2;"  # type: ignore[misc]


def test_statement_new_unit_defaults_false_and_survives_dispatch() -> None:
    default_statement = SqlStatement(sql="SELECT 1;", transactional=True, delta=_CREATE)
    assert default_statement.new_unit is False

    def emit_new_unit(delta: DeltaBase) -> tuple[SqlStatement, ...]:
        return (
            SqlStatement(sql="VALIDATE CONSTRAINT", transactional=True, delta=delta, new_unit=True),
        )

    statement = SqlEmitter({CreateSchema: emit_new_unit}).emit(DeltaSet.from_iterable((_CREATE,)))[
        0
    ]

    assert statement.new_unit is True
