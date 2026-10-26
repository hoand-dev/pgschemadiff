"""Emit DDL for PostgreSQL table triggers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import catalog_fragment, quote_ident, quote_qualified
from pgschemadiff.domain.delta.trigger import (
    AlterTriggerEnabled,
    CreateTrigger,
    DropTrigger,
    ReplaceTrigger,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.trigger import Trigger


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def _definition(trigger: Trigger, *, replace_regular: bool = False) -> str:
    definition = catalog_fragment(trigger.definition, "Trigger definition")
    prefix = "CREATE CONSTRAINT TRIGGER " if trigger.is_constraint else "CREATE TRIGGER "
    if not definition.startswith(prefix) or not definition[len(prefix) :].strip():
        raise MigrationError(f"Trigger definition must have exact {prefix.strip()} prefix.")
    if replace_regular:
        return "CREATE OR REPLACE TRIGGER " + definition[len("CREATE TRIGGER ") :]
    return definition


def _enabled_sql(trigger: Trigger, state: str) -> str:
    action = {
        "O": "ENABLE TRIGGER",
        "D": "DISABLE TRIGGER",
        "R": "ENABLE REPLICA TRIGGER",
        "A": "ENABLE ALWAYS TRIGGER",
    }.get(state)
    if action is None:
        raise MigrationError(f"Unsupported trigger enabled state {state!r}.")
    return (
        f"ALTER TABLE {quote_qualified(trigger.table_ref.qname)} "
        f"{action} {quote_ident(trigger.ref.qname.name)}"
    )


def _create_statements(trigger: Trigger, delta: DeltaBase) -> tuple[SqlStatement, ...]:
    statements = [_statement(_definition(trigger), delta)]
    if trigger.enabled != "O":
        statements.append(_statement(_enabled_sql(trigger, trigger.enabled), delta))
    return tuple(statements)


def emit_create_trigger(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateTrigger):
        raise MigrationError("Create-trigger handler received a different delta type.")
    return _create_statements(delta.trigger, delta)


def emit_drop_trigger(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropTrigger):
        raise MigrationError("Drop-trigger handler received a different delta type.")
    return (
        _statement(
            f"DROP TRIGGER {quote_ident(delta.trigger.ref.qname.name)} "
            f"ON {quote_qualified(delta.trigger.table_ref.qname)} RESTRICT",
            delta,
        ),
    )


def emit_replace_trigger(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, ReplaceTrigger):
        raise MigrationError("Replace-trigger handler received a different delta type.")
    if delta.old_trigger.is_constraint or delta.new_trigger.is_constraint:
        statements = [
            _statement(
                f"DROP TRIGGER {quote_ident(delta.old_trigger.ref.qname.name)} "
                f"ON {quote_qualified(delta.old_trigger.table_ref.qname)} RESTRICT",
                delta,
            ),
            _statement(_definition(delta.new_trigger), delta),
        ]
        if delta.new_trigger.enabled != "O":
            statements.append(
                _statement(_enabled_sql(delta.new_trigger, delta.new_trigger.enabled), delta)
            )
        return tuple(statements)

    definition = _definition(delta.new_trigger, replace_regular=True)
    statements = [_statement(definition, delta)]
    if delta.old_trigger.enabled != delta.new_trigger.enabled or delta.new_trigger.enabled != "O":
        statements.append(
            _statement(_enabled_sql(delta.new_trigger, delta.new_trigger.enabled), delta)
        )
    return tuple(statements)


def emit_alter_trigger_enabled(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterTriggerEnabled):
        raise MigrationError("Alter-trigger-enabled handler received a different delta type.")
    return (_statement(_enabled_sql(delta.trigger, delta.new_enabled), delta),)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for every trigger delta."""
    return {
        CreateTrigger: emit_create_trigger,
        DropTrigger: emit_drop_trigger,
        ReplaceTrigger: emit_replace_trigger,
        AlterTriggerEnabled: emit_alter_trigger_enabled,
    }
