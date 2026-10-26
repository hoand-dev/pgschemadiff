from __future__ import annotations

from typing import Literal

import pytest

from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlStatement
from pgschemadiff.application.sql_emit.registry import default_handlers
from pgschemadiff.domain.delta import (
    AlterTriggerEnabled,
    CreateTrigger,
    DeltaSet,
    DropTrigger,
    ReplaceTrigger,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.trigger import Trigger
from pgschemadiff.shared.errors import MigrationError

_TABLE_REF = ObjectRef(
    kind=ObjectKind.TABLE,
    qname=QualifiedName(namespace='App "Schema', name="Order"),
)
_TRIGGER_REF = ObjectRef(
    kind=ObjectKind.TRIGGER,
    qname=QualifiedName(namespace='App "Schema', name='audit "row'),
    parent=_TABLE_REF,
)


def _trigger(
    *,
    definition: str | None = None,
    is_constraint: bool = False,
    enabled: Literal["O", "D", "R", "A"] = "O",
) -> Trigger:
    default_prefix = "CREATE CONSTRAINT TRIGGER" if is_constraint else "CREATE TRIGGER"
    return Trigger(
        ref=_TRIGGER_REF,
        table_ref=_TABLE_REF,
        function_ref=ObjectRef(
            kind=ObjectKind.FUNCTION,
            qname=QualifiedName(namespace="App " + '"Schema', name="audit_row"),
            arg_signature=(),
        ),
        definition=definition
        or f'{default_prefix} "audit ""row" AFTER INSERT ON "App ""Schema"."Order"',
        timing="AFTER",
        events=("INSERT",),
        row_level=True,
        is_constraint=is_constraint,
        deferrable=is_constraint,
        initially_deferred=is_constraint,
        enabled=enabled,
    )


def _emit(
    delta: CreateTrigger | DropTrigger | ReplaceTrigger | AlterTriggerEnabled,
) -> tuple[SqlStatement, ...]:
    return SqlEmitter(default_handlers()).emit(DeltaSet.from_iterable((delta,)))


def _alter_sql(state: Literal["O", "D", "R", "A"]) -> str:
    action = {
        "O": 'ENABLE TRIGGER "audit ""row"',
        "D": 'DISABLE TRIGGER "audit ""row"',
        "R": 'ENABLE REPLICA TRIGGER "audit ""row"',
        "A": 'ENABLE ALWAYS TRIGGER "audit ""row"',
    }[state]
    return f'ALTER TABLE "App ""Schema"."Order" {action}'


def test_create_trigger_uses_catalog_definition_and_sets_nondefault_enabled_state() -> None:
    trigger = _trigger(enabled="A")
    delta = CreateTrigger(target=trigger.ref, trigger=trigger)

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        trigger.definition,
        _alter_sql("A"),
    )
    assert all(statement.transactional and statement.delta is delta for statement in statements)


def test_create_origin_trigger_emits_only_catalog_definition() -> None:
    trigger = _trigger()

    statements = _emit(CreateTrigger(target=trigger.ref, trigger=trigger))

    assert tuple(statement.sql for statement in statements) == (trigger.definition,)


def test_drop_trigger_uses_qualified_table_and_restrict() -> None:
    trigger = _trigger()

    statements = _emit(DropTrigger(target=trigger.ref, trigger=trigger))

    assert tuple(statement.sql for statement in statements) == (
        'DROP TRIGGER "audit ""row" ON "App ""Schema"."Order" RESTRICT',
    )


def test_regular_trigger_replace_rewrites_only_exact_create_prefix_and_sets_state() -> None:
    old = _trigger(enabled="D")
    new_definition = (
        'CREATE TRIGGER "audit ""row" BEFORE INSERT ON "App ""Schema"."Order" '
        'FOR EACH ROW EXECUTE FUNCTION "App ""Schema".audit_row()'
    )
    new = _trigger(definition=new_definition, enabled="R")
    delta = ReplaceTrigger(target=old.ref, old_trigger=old, new_trigger=new)

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        new_definition.replace("CREATE TRIGGER ", "CREATE OR REPLACE TRIGGER ", 1),
        _alter_sql("R"),
    )
    assert all(statement.transactional and statement.delta is delta for statement in statements)


def test_constraint_trigger_replace_drops_then_creates_transactionally() -> None:
    old = _trigger(is_constraint=True)
    new = _trigger(
        is_constraint=True,
        enabled="D",
        definition=(
            'CREATE CONSTRAINT TRIGGER "audit ""row" AFTER INSERT '
            'ON "App ""Schema"."Order" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW'
        ),
    )
    delta = ReplaceTrigger(target=old.ref, old_trigger=old, new_trigger=new)

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'DROP TRIGGER "audit ""row" ON "App ""Schema"."Order" RESTRICT',
        new.definition,
        _alter_sql("D"),
    )
    assert all(statement.transactional and statement.delta is delta for statement in statements)


@pytest.mark.parametrize("state", ["O", "D", "R", "A"])
def test_enabled_state_delta_emits_postgres_state_action(
    state: Literal["O", "D", "R", "A"],
) -> None:
    old = _trigger(enabled="D" if state == "O" else "O")
    delta = AlterTriggerEnabled(target=old.ref, trigger=old, new_enabled=state)

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (_alter_sql(state),)
    assert statements[0].transactional is True
    assert statements[0].delta is delta


@pytest.mark.parametrize(
    ("constraint", "definition"),
    [
        (False, ' CREATE TRIGGER "audit ""row" AFTER INSERT ON "App ""Schema"."Order"'),
        (False, 'CREATE CONSTRAINT TRIGGER "audit ""row" AFTER INSERT ON "App ""Schema"."Order"'),
        (True, 'CREATE TRIGGER "audit ""row" AFTER INSERT ON "App ""Schema"."Order"'),
    ],
)
def test_create_rejects_unvalidated_definition_prefix(constraint: bool, definition: str) -> None:
    trigger = _trigger(is_constraint=constraint, definition=definition)

    with pytest.raises(MigrationError, match=r"exact CREATE (?:CONSTRAINT )?TRIGGER prefix"):
        _emit(CreateTrigger(target=trigger.ref, trigger=trigger))


def test_regular_replace_rejects_unvalidated_definition_prefix() -> None:
    old = _trigger()
    new = _trigger(definition='prefix CREATE TRIGGER "audit ""row"')

    with pytest.raises(MigrationError, match="exact CREATE TRIGGER prefix"):
        _emit(ReplaceTrigger(target=old.ref, old_trigger=old, new_trigger=new))
