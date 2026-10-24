"""Emit DDL for table constraints."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import (
    catalog_fragment,
    quote_ident,
    quote_qualified,
)
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ConstraintDeferrability,
    ExclusionConstraint,
    FKAction,
    FKMatch,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.identity import ObjectKind, QualifiedName
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.constraint import Constraint
    from pgschemadiff.domain.delta.base import DeltaBase


_NO_INHERIT = re.compile(r"\bNO\s+INHERIT\b", re.IGNORECASE)
_FK_ACTION_COLUMN_LIST = re.compile(
    r"\bON\s+(?:UPDATE|DELETE)\s+SET\s+(?:NULL|DEFAULT)\s*\(", re.IGNORECASE
)
_FK_ACTION_SQL = {
    FKAction.NO_ACTION: "NO ACTION",
    FKAction.RESTRICT: "RESTRICT",
    FKAction.CASCADE: "CASCADE",
    FKAction.SET_NULL: "SET NULL",
    FKAction.SET_DEFAULT: "SET DEFAULT",
}
_FK_MATCH_SQL = {
    FKMatch.SIMPLE: "SIMPLE",
    FKMatch.FULL: "FULL",
}
_DEFERRABILITY_SQL = {
    ConstraintDeferrability.NOT_DEFERRABLE: "NOT DEFERRABLE",
    ConstraintDeferrability.DEFERRABLE_INITIALLY_IMMEDIATE: ("DEFERRABLE INITIALLY IMMEDIATE"),
    ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED: "DEFERRABLE INITIALLY DEFERRED",
}


def _statement(sql: str, delta: DeltaBase, *, new_unit: bool = False) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta, new_unit=new_unit)


def _owner_table_name(delta: DeltaBase) -> str:
    parent = delta.target.parent
    if parent is None or parent.kind is not ObjectKind.TABLE:
        raise MigrationError("Constraint delta has no parent table.")
    return quote_qualified(parent.qname)


def _raw_definition(definition: str | None, description: str) -> str:
    if definition is None:
        raise MigrationError(f"{description} is missing its catalog definition.")
    return catalog_fragment(definition, description)


def _quoted_columns(columns: tuple[str, ...], description: str) -> str:
    if not columns or any(column == "?" for column in columns):
        raise MigrationError(f"{description} contains missing catalog columns.")
    return ", ".join(quote_ident(column) for column in columns)


def _outside_quoted_identifiers(sql: str) -> str:
    characters: list[str] = []
    quoted = False
    position = 0
    while position < len(sql):
        char = sql[position]
        if char == '"':
            characters.append(" ")
            if quoted and position + 1 < len(sql) and sql[position + 1] == '"':
                characters.append(" ")
                position += 2
                continue
            quoted = not quoted
        else:
            characters.append(" " if quoted else char)
        position += 1
    return "".join(characters)


def _render_foreign_key(constraint: ForeignKeyConstraint) -> str:
    if constraint.match_type is FKMatch.PARTIAL:
        raise MigrationError("MATCH PARTIAL foreign keys are unsupported.")
    if (
        constraint.definition is not None
        and _FK_ACTION_COLUMN_LIST.search(_outside_quoted_identifiers(constraint.definition))
        is not None
    ):
        raise MigrationError("Foreign-key action column lists are unsupported.")
    match = _FK_MATCH_SQL.get(constraint.match_type)
    on_update = _FK_ACTION_SQL.get(constraint.on_update)
    on_delete = _FK_ACTION_SQL.get(constraint.on_delete)
    deferrability = _DEFERRABILITY_SQL.get(constraint.deferrability)
    if match is None or on_update is None or on_delete is None or deferrability is None:
        raise MigrationError("Foreign-key options cannot be represented in SQL.")
    if len(constraint.columns) != len(constraint.ref_columns):
        raise MigrationError("Foreign-key local and referenced columns do not match in count.")
    if constraint.ref_namespace == "?" or constraint.ref_table == "?":
        raise MigrationError("Foreign-key reference contains missing catalog identifiers.")

    reference = quote_qualified(
        QualifiedName(namespace=constraint.ref_namespace, name=constraint.ref_table)
    )
    local_columns = _quoted_columns(constraint.columns, "Foreign-key local columns")
    ref_columns = _quoted_columns(constraint.ref_columns, "Foreign-key referenced columns")
    return (
        f"FOREIGN KEY ({local_columns}) REFERENCES {reference} ({ref_columns}) "
        f"MATCH {match} ON UPDATE {on_update} ON DELETE {on_delete} {deferrability}"
    )


def _render_definition(constraint: Constraint) -> str:
    if isinstance(constraint, (PrimaryKeyConstraint, UniqueConstraint, ExclusionConstraint)):
        return _raw_definition(constraint.definition, "Constraint definition")
    if isinstance(constraint, CheckConstraint):
        definition = _raw_definition(constraint.definition, "Check constraint definition")
        if constraint.no_inherit and _NO_INHERIT.search(definition) is None:
            raise MigrationError("NO INHERIT flag is missing from the check definition.")
        return definition
    if isinstance(constraint, ForeignKeyConstraint):
        return _render_foreign_key(constraint)
    raise MigrationError("Constraint kind is unsupported.")


def emit_add_constraint(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AddConstraint):
        raise MigrationError("Add-constraint handler received a different delta type.")
    if delta.constraint.inherited:
        raise MigrationError("Inherited constraints must not reach the SQL emitter.")

    table = _owner_table_name(delta)
    name = quote_ident(delta.target.qname.name)
    definition = _render_definition(delta.constraint)
    add_sql = f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}"
    if isinstance(delta.constraint, (CheckConstraint, ForeignKeyConstraint)):
        return (
            _statement(f"{add_sql} NOT VALID", delta),
            _statement(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}", delta, new_unit=True),
        )
    return (_statement(add_sql, delta),)


def emit_drop_constraint(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropConstraint):
        raise MigrationError("Drop-constraint handler received a different delta type.")
    if delta.constraint.inherited:
        raise MigrationError("Inherited constraints must not reach the SQL emitter.")

    table = _owner_table_name(delta)
    name = quote_ident(delta.target.qname.name)
    return (_statement(f"ALTER TABLE {table} DROP CONSTRAINT {name}", delta),)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for exactly the concrete constraint delta types."""
    return {
        AddConstraint: emit_add_constraint,
        DropConstraint: emit_drop_constraint,
    }
