"""Emit DDL for PostgreSQL composite types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import catalog_fragment, quote_ident, quote_qualified
from pgschemadiff.domain.delta.composite_type import (
    AlterCompositeAddAttribute,
    AlterCompositeAttributeType,
    AlterCompositeDropAttribute,
    AlterCompositeTypeAttrs,
    CreateCompositeType,
    DropCompositeType,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.composite_type import CompositeAttribute
    from pgschemadiff.domain.delta.base import DeltaBase


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def _attribute_definition(attribute: CompositeAttribute) -> str:
    data_type = catalog_fragment(attribute.data_type, "Composite attribute data type")
    definition = f"{quote_ident(attribute.name)} {data_type}"
    if attribute.collation is not None:
        collation = catalog_fragment(attribute.collation, "Composite attribute collation")
        definition += f" COLLATE {collation}"
    return definition


def emit_create_composite_type(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateCompositeType):
        raise MigrationError("Create-composite-type handler received a different delta type.")

    composite = delta.composite
    name = quote_qualified(composite.ref.qname)
    attributes = ", ".join(_attribute_definition(item) for item in composite.attributes)
    statements = [_statement(f"CREATE TYPE {name} AS ({attributes})", delta)]
    if composite.owner is not None:
        statements.append(
            _statement(f"ALTER TYPE {name} OWNER TO {quote_ident(composite.owner)}", delta)
        )
    return tuple(statements)


def emit_drop_composite_type(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropCompositeType):
        raise MigrationError("Drop-composite-type handler received a different delta type.")
    return (_statement(f"DROP TYPE {quote_qualified(delta.composite.ref.qname)} RESTRICT", delta),)


def emit_add_composite_attribute(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterCompositeAddAttribute):
        raise MigrationError("Add-composite-attribute handler received a different delta type.")
    name = quote_qualified(delta.target.qname)
    attribute = _attribute_definition(delta.attribute)
    return (_statement(f"ALTER TYPE {name} ADD ATTRIBUTE {attribute} RESTRICT", delta),)


def emit_drop_composite_attribute(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterCompositeDropAttribute):
        raise MigrationError("Drop-composite-attribute handler received a different delta type.")
    name = quote_qualified(delta.target.qname)
    attribute = quote_ident(delta.attribute_name)
    return (_statement(f"ALTER TYPE {name} DROP ATTRIBUTE {attribute} RESTRICT", delta),)


def emit_alter_composite_attribute_type(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterCompositeAttributeType):
        raise MigrationError("Alter-composite-attribute handler received a different delta type.")
    name = quote_qualified(delta.target.qname)
    attribute = quote_ident(delta.attribute_name)
    data_type = catalog_fragment(delta.new_data_type, "Composite attribute data type")
    sql = f"ALTER TYPE {name} ALTER ATTRIBUTE {attribute} SET DATA TYPE {data_type}"
    if delta.new_collation is not None:
        collation = catalog_fragment(delta.new_collation, "Composite attribute collation")
        sql += f" COLLATE {collation}"
    return (_statement(f"{sql} RESTRICT", delta),)


def emit_alter_composite_type_attrs(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterCompositeTypeAttrs):
        raise MigrationError("Alter-composite-type-attrs handler received a different delta type.")
    name = quote_qualified(delta.target.qname)
    return (_statement(f"ALTER TYPE {name} OWNER TO {quote_ident(delta.new_owner)}", delta),)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for all SQL-emittable composite-type deltas."""
    return {
        CreateCompositeType: emit_create_composite_type,
        DropCompositeType: emit_drop_composite_type,
        AlterCompositeAddAttribute: emit_add_composite_attribute,
        AlterCompositeDropAttribute: emit_drop_composite_attribute,
        AlterCompositeAttributeType: emit_alter_composite_attribute_type,
        AlterCompositeTypeAttrs: emit_alter_composite_type_attrs,
    }
