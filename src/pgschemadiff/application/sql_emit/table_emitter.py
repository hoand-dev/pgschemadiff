"""Emit table DDL. Table constraints stay in separate AddConstraint deltas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.column_emitter import (
    render_column_definition,
)
from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import (
    catalog_fragment,
    quote_ident,
    quote_literal,
    quote_qualified,
)
from pgschemadiff.domain.delta.table import AlterTableAttrs, CreateTable, DropTable, RenameTable
from pgschemadiff.domain.identity import QualifiedName
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def emit_create_table(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateTable):
        raise MigrationError("Create-table handler received a different delta type.")

    table = delta.table
    if table.unlogged and (table.partition_info is not None or table.partition_of is not None):
        raise MigrationError(
            "UNLOGGED tables with partition metadata are unsupported by PostgreSQL 18."
        )
    table_name = quote_qualified(table.qname)
    if table.partition_of is not None:
        parent = QualifiedName(
            namespace=table.partition_of.parent_namespace,
            name=table.partition_of.parent_name,
        )
        bound = table.partition_of.partition_bound
        bound_sql = "DEFAULT" if bound is None else catalog_fragment(bound, "Partition bound")
        create_sql = f"CREATE TABLE {table_name} PARTITION OF {quote_qualified(parent)} {bound_sql}"
    else:
        columns = ", ".join(
            render_column_definition(column)
            for column in sorted(table.columns, key=lambda column: column.position)
        )
        create_keyword = "CREATE UNLOGGED TABLE" if table.unlogged else "CREATE TABLE"
        create_sql = f"{create_keyword} {table_name} ({columns})"

    if table.partition_info is not None:
        partition_key = catalog_fragment(table.partition_info.partition_key, "Partition key")
        create_sql += f" PARTITION BY {partition_key}"

    statements = [_statement(create_sql, delta)]
    if table.owner is not None:
        statements.append(
            _statement(
                f"ALTER TABLE {table_name} OWNER TO {quote_ident(table.owner)}",
                delta,
            )
        )
    if table.tablespace is not None:
        statements.append(
            _statement(
                f"ALTER TABLE {table_name} SET TABLESPACE {quote_ident(table.tablespace)}",
                delta,
            )
        )
    if table.comment is not None:
        statements.append(
            _statement(
                f"COMMENT ON TABLE {table_name} IS {quote_literal(table.comment)}",
                delta,
            )
        )
    return tuple(statements)


def emit_drop_table(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropTable):
        raise MigrationError("Drop-table handler received a different delta type.")
    table_name = quote_qualified(delta.table.qname)
    return (_statement(f"DROP TABLE {table_name} RESTRICT", delta),)


def emit_rename_table(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, RenameTable):
        raise MigrationError("Rename-table handler received a different delta type.")
    old_table = quote_qualified(delta.old_name)
    new_name = quote_ident(delta.new_name.name)
    statements = [_statement(f"ALTER TABLE {old_table} RENAME TO {new_name}", delta)]
    if delta.old_name.namespace != delta.new_name.namespace:
        renamed_table = quote_qualified(
            QualifiedName(namespace=delta.old_name.namespace, name=delta.new_name.name)
        )
        new_schema = quote_ident(delta.new_name.namespace)
        statements.append(_statement(f"ALTER TABLE {renamed_table} SET SCHEMA {new_schema}", delta))
    return tuple(statements)


def emit_alter_table_attrs(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterTableAttrs):
        raise MigrationError("Alter-table-attrs handler received a different delta type.")
    if delta.new_partition_info is not None or delta.new_partition_of is not None:
        raise MigrationError("Changing partition strategy or parent is unsupported.")

    table_name = quote_qualified(delta.target.qname)
    statements: list[SqlStatement] = []
    if delta.new_owner is not None:
        statements.append(
            _statement(
                f"ALTER TABLE {table_name} OWNER TO {quote_ident(delta.new_owner)}",
                delta,
            )
        )
    if delta.new_tablespace is not None:
        statements.append(
            _statement(
                f"ALTER TABLE {table_name} SET TABLESPACE {quote_ident(delta.new_tablespace)}",
                delta,
            )
        )
    if delta.new_unlogged is not None:
        persistence = "UNLOGGED" if delta.new_unlogged else "LOGGED"
        statements.append(_statement(f"ALTER TABLE {table_name} SET {persistence}", delta))
    if delta.new_comment is not None:
        comment = "NULL" if delta.new_comment == "" else quote_literal(delta.new_comment)
        statements.append(_statement(f"COMMENT ON TABLE {table_name} IS {comment}", delta))
    if not statements:
        raise MigrationError("AlterTableAttrs contains no supported table attribute changes.")
    return tuple(statements)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for exactly the concrete table delta types."""
    return {
        CreateTable: emit_create_table,
        DropTable: emit_drop_table,
        RenameTable: emit_rename_table,
        AlterTableAttrs: emit_alter_table_attrs,
    }
