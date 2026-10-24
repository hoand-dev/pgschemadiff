"""Emit schema and extension DDL."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import quote_ident, quote_literal
from pgschemadiff.domain.delta.schema import (
    AlterExtension,
    CreateExtension,
    CreateSchema,
    DropExtension,
    DropSchema,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def emit_create_schema(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateSchema):
        raise MigrationError("Create-schema handler received a different delta type.")

    schema = delta.pg_schema
    name = quote_ident(schema.name)
    sql = f"CREATE SCHEMA {name}"
    if schema.owner is not None:
        sql += f" AUTHORIZATION {quote_ident(schema.owner)}"

    statements = [_statement(sql, delta)]
    if schema.comment is not None:
        statements.append(
            _statement(
                f"COMMENT ON SCHEMA {name} IS {quote_literal(schema.comment)}",
                delta,
            )
        )
    return tuple(statements)


def emit_drop_schema(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropSchema):
        raise MigrationError("Drop-schema handler received a different delta type.")
    return (_statement(f"DROP SCHEMA {quote_ident(delta.pg_schema.name)} RESTRICT", delta),)


def emit_create_extension(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateExtension):
        raise MigrationError("Create-extension handler received a different delta type.")

    extension = delta.extension
    name = quote_ident(extension.name)
    sql = f"CREATE EXTENSION {name}"
    if extension.installed_schema is not None:
        sql += f" WITH SCHEMA {quote_ident(extension.installed_schema)}"
    sql += f" VERSION {quote_literal(extension.version)}"

    # PostgreSQL runs extension scripts inside a transaction block.
    statements = [_statement(sql, delta)]
    if extension.comment is not None:
        statements.append(
            _statement(
                f"COMMENT ON EXTENSION {name} IS {quote_literal(extension.comment)}",
                delta,
            )
        )
    return tuple(statements)


def emit_drop_extension(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropExtension):
        raise MigrationError("Drop-extension handler received a different delta type.")
    return (_statement(f"DROP EXTENSION {quote_ident(delta.extension.name)} RESTRICT", delta),)


def emit_alter_extension(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterExtension):
        raise MigrationError("Alter-extension handler received a different delta type.")

    name = quote_ident(delta.target.qname.name)
    statements: list[SqlStatement] = []
    if delta.new_version is not None:
        statements.append(
            _statement(
                f"ALTER EXTENSION {name} UPDATE TO {quote_literal(delta.new_version)}",
                delta,
            )
        )
    if delta.new_schema is not None:
        statements.append(
            _statement(
                f"ALTER EXTENSION {name} SET SCHEMA {quote_ident(delta.new_schema)}",
                delta,
            )
        )
    if not statements:
        raise MigrationError("AlterExtension contains no clauses.")
    return tuple(statements)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for exactly the concrete schema and extension delta types."""
    return {
        CreateSchema: emit_create_schema,
        DropSchema: emit_drop_schema,
        CreateExtension: emit_create_extension,
        DropExtension: emit_drop_extension,
        AlterExtension: emit_alter_extension,
    }
