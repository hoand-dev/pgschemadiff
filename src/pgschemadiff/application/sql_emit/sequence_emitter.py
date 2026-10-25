"""Emit DDL for PostgreSQL sequences."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import quote_ident, quote_qualified
from pgschemadiff.domain.delta.sequence import (
    AlterSequenceOptions,
    AlterSequenceOwnedBy,
    AlterSequenceOwner,
    CreateSequence,
    DropSequence,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def emit_create_sequence(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateSequence):
        raise MigrationError("Create-sequence handler received a different delta type.")

    sequence = delta.sequence
    name = quote_qualified(sequence.ref.qname)
    cycle = "CYCLE" if sequence.cycle else "NO CYCLE"
    sql = (
        f"CREATE SEQUENCE {name} AS {sequence.data_type} "
        f"INCREMENT BY {sequence.increment} MINVALUE {sequence.min_value} "
        f"MAXVALUE {sequence.max_value} START WITH {sequence.start} "
        f"CACHE {sequence.cache} {cycle}"
    )
    statements = [_statement(sql, delta)]
    if sequence.owner is not None:
        statements.append(
            _statement(f"ALTER SEQUENCE {name} OWNER TO {quote_ident(sequence.owner)}", delta)
        )
    return tuple(statements)


def emit_drop_sequence(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropSequence):
        raise MigrationError("Drop-sequence handler received a different delta type.")
    name = quote_qualified(delta.sequence.ref.qname)
    return (_statement(f"DROP SEQUENCE {name} RESTRICT", delta),)


def emit_alter_sequence_options(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterSequenceOptions):
        raise MigrationError("Alter-sequence-options handler received a different delta type.")

    options: list[str] = []
    for value, clause in (
        (delta.new_data_type, "AS"),
        (delta.new_increment, "INCREMENT BY"),
        (delta.new_min_value, "MINVALUE"),
        (delta.new_max_value, "MAXVALUE"),
        (delta.new_start, "START WITH"),
        (delta.new_cache, "CACHE"),
    ):
        if value is not None:
            options.append(f"{clause} {value}")
    if delta.new_cycle is not None:
        options.append("CYCLE" if delta.new_cycle else "NO CYCLE")

    name = quote_qualified(delta.target.qname)
    return (_statement(f"ALTER SEQUENCE {name} {' '.join(options)}", delta),)


def emit_alter_sequence_owner(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterSequenceOwner):
        raise MigrationError("Alter-sequence-owner handler received a different delta type.")
    name = quote_qualified(delta.target.qname)
    owner = quote_ident(delta.new_owner)
    return (_statement(f"ALTER SEQUENCE {name} OWNER TO {owner}", delta),)


def emit_alter_sequence_owned_by(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterSequenceOwnedBy):
        raise MigrationError("Alter-sequence-owned-by handler received a different delta type.")

    if delta.new_owned_by is None:
        owner = "NONE"
    else:
        table = delta.new_owned_by.parent
        if table is None:
            raise MigrationError("Sequence OWNED BY target has no parent table.")
        owner = f"{quote_qualified(table.qname)}.{quote_ident(delta.new_owned_by.qname.name)}"
    name = quote_qualified(delta.target.qname)
    return (_statement(f"ALTER SEQUENCE {name} OWNED BY {owner}", delta),)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for every sequence delta."""
    return {
        CreateSequence: emit_create_sequence,
        DropSequence: emit_drop_sequence,
        AlterSequenceOptions: emit_alter_sequence_options,
        AlterSequenceOwner: emit_alter_sequence_owner,
        AlterSequenceOwnedBy: emit_alter_sequence_owned_by,
    }
