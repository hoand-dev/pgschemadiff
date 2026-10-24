"""Emit SQL for column deltas and render reusable column definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import (
    catalog_fragment,
    quote_ident,
    quote_qualified,
)
from pgschemadiff.domain.column import Column, GeneratedTiming
from pgschemadiff.domain.delta.column import (
    AddColumn,
    AlterColumnType,
    DropColumn,
    RenameColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.column import IdentitySpec
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.identity import ObjectRef


def _render_identity(identity: IdentitySpec) -> str:
    generated = "ALWAYS" if identity.generated is GeneratedTiming.ALWAYS else "BY DEFAULT"
    clause = f"GENERATED {generated} AS IDENTITY"
    options: list[str] = []
    if identity.sequence_start is not None:
        options.extend(("START WITH", str(identity.sequence_start)))
    if identity.sequence_increment is not None:
        options.extend(("INCREMENT BY", str(identity.sequence_increment)))
    if identity.sequence_min_value is not None:
        options.extend(("MINVALUE", str(identity.sequence_min_value)))
    if identity.sequence_max_value is not None:
        options.extend(("MAXVALUE", str(identity.sequence_max_value)))
    if identity.sequence_cache is not None:
        options.extend(("CACHE", str(identity.sequence_cache)))
    if identity.sequence_cycle:
        options.append("CYCLE")
    if options:
        clause += f" ({' '.join(options)})"
    return clause


def render_column_definition(column: Column) -> str:
    """Render one CREATE/ADD column definition from its catalog-backed model."""
    has_identity = column.identity is not None
    has_generated = column.generated_expression is not None
    has_default = column.default_expr is not None
    if has_identity and has_default:
        raise MigrationError("Identity columns cannot also have a default expression.")
    if has_identity and has_generated:
        raise MigrationError("Identity columns cannot also be generated columns.")
    if has_generated and has_default:
        raise MigrationError("Generated columns cannot also have a default expression.")

    definition = [
        quote_ident(column.name),
        catalog_fragment(column.data_type, "Column data type"),
    ]
    if column.collation is not None:
        definition.extend(("COLLATE", quote_ident(column.collation)))

    if column.identity is not None:
        definition.append(_render_identity(column.identity))
        # PostgreSQL identity columns are implicitly NOT NULL.
    elif column.generated_expression is not None:
        expression = catalog_fragment(column.generated_expression, "Generated expression")
        definition.append(f"GENERATED ALWAYS AS ({expression}) STORED")
    elif column.default_expr is not None:
        default = catalog_fragment(column.default_expr, "Column default")
        definition.extend(("DEFAULT", default))

    if not has_identity and not column.nullable:
        definition.append("NOT NULL")
    return " ".join(definition)


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def _table_name(target: ObjectRef) -> str:
    if target.parent is None:
        raise MigrationError("Column delta target has no parent table.")
    return quote_qualified(target.parent.qname)


def _column_name(target: ObjectRef) -> str:
    return quote_ident(target.qname.name)


def emit_add_column(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AddColumn):
        raise MigrationError("Add-column handler received a different delta type.")
    table = _table_name(delta.target)
    definition = render_column_definition(delta.column)
    return (_statement(f"ALTER TABLE {table} ADD COLUMN {definition}", delta),)


def emit_drop_column(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropColumn):
        raise MigrationError("Drop-column handler received a different delta type.")
    table = _table_name(delta.target)
    column = _column_name(delta.target)
    return (_statement(f"ALTER TABLE {table} DROP COLUMN {column}", delta),)


def emit_alter_column_type(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterColumnType):
        raise MigrationError("Alter-column-type handler received a different delta type.")
    table = _table_name(delta.target)
    column = _column_name(delta.target)
    new_type = catalog_fragment(delta.new_data_type, "Column data type")
    sql = f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {new_type}"
    if delta.new_collation is not None:
        sql += f" COLLATE {quote_ident(delta.new_collation)}"
    if delta.using_expression is not None:
        using = catalog_fragment(delta.using_expression, "USING expression")
        sql += f" USING {using}"
    return (_statement(sql, delta),)


def emit_set_column_default(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, SetColumnDefault):
        raise MigrationError("Set-column-default handler received a different delta type.")
    table = _table_name(delta.target)
    column = _column_name(delta.target)
    if delta.new_default is None:
        action = "DROP DEFAULT"
    else:
        default = catalog_fragment(delta.new_default, "Column default")
        action = f"SET DEFAULT {default}"
    return (_statement(f"ALTER TABLE {table} ALTER COLUMN {column} {action}", delta),)


def emit_set_column_nullability(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, SetColumnNullability):
        raise MigrationError("Set-column-nullability handler received a different delta type.")
    table = _table_name(delta.target)
    column = _column_name(delta.target)
    action = "DROP NOT NULL" if delta.nullable else "SET NOT NULL"
    return (_statement(f"ALTER TABLE {table} ALTER COLUMN {column} {action}", delta),)


def emit_rename_column(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, RenameColumn):
        raise MigrationError("Rename-column handler received a different delta type.")
    table = _table_name(delta.target)
    old_name = quote_ident(delta.old_name)
    new_name = quote_ident(delta.new_name)
    return (
        _statement(
            f"ALTER TABLE {table} RENAME COLUMN {old_name} TO {new_name}",
            delta,
        ),
    )


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for exactly the concrete column delta types."""
    return {
        AddColumn: emit_add_column,
        DropColumn: emit_drop_column,
        AlterColumnType: emit_alter_column_type,
        SetColumnDefault: emit_set_column_default,
        SetColumnNullability: emit_set_column_nullability,
        RenameColumn: emit_rename_column,
    }
