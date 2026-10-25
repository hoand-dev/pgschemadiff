"""Emit PostgreSQL enum DDL."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import quote_ident, quote_literal, quote_qualified
from pgschemadiff.domain.delta.enum import AddEnumValue, AlterEnumAttrs, CreateEnum, DropEnum
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase


def _statement(
    sql: str,
    delta: DeltaBase,
    *,
    isolated: bool = False,
) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta, isolated=isolated)


def emit_create_enum(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateEnum):
        raise MigrationError("Create-enum handler received a different delta type.")

    enum = delta.enum
    name = quote_qualified(enum.ref.qname)
    labels = ", ".join(quote_literal(label) for label in enum.labels)
    statements = [_statement(f"CREATE TYPE {name} AS ENUM ({labels})", delta)]
    if enum.owner is not None:
        statements.append(
            _statement(f"ALTER TYPE {name} OWNER TO {quote_ident(enum.owner)}", delta)
        )
    return tuple(statements)


def emit_drop_enum(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropEnum):
        raise MigrationError("Drop-enum handler received a different delta type.")
    return (_statement(f"DROP TYPE {quote_qualified(delta.enum.ref.qname)} RESTRICT", delta),)


def emit_add_enum_value(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AddEnumValue):
        raise MigrationError("Add-enum-value handler received a different delta type.")

    sql = f"ALTER TYPE {quote_qualified(delta.target.qname)} ADD VALUE {quote_literal(delta.label)}"
    if delta.before is not None:
        sql += f" BEFORE {quote_literal(delta.before)}"
    elif delta.after is not None:
        sql += f" AFTER {quote_literal(delta.after)}"
    return (_statement(sql, delta, isolated=True),)


def emit_alter_enum_attrs(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterEnumAttrs):
        raise MigrationError("Alter-enum-attrs handler received a different delta type.")
    name = quote_qualified(delta.target.qname)
    return (_statement(f"ALTER TYPE {name} OWNER TO {quote_ident(delta.new_owner)}", delta),)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for emittable enum deltas."""
    return {
        CreateEnum: emit_create_enum,
        DropEnum: emit_drop_enum,
        AddEnumValue: emit_add_enum_value,
        AlterEnumAttrs: emit_alter_enum_attrs,
    }
