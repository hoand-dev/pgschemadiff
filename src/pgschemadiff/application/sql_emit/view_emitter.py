"""Emit DDL for PostgreSQL views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import catalog_fragment, quote_ident, quote_qualified
from pgschemadiff.domain.delta.view import (
    AlterViewOwner,
    CreateView,
    DropView,
    ReplaceView,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.view import View


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def _create_sql(view: View, *, replace: bool) -> str:
    columns = ", ".join(quote_ident(name) for name, _ in view.columns)
    options = []
    if view.security_barrier:
        options.append("security_barrier = true")
    if view.security_invoker:
        options.append("security_invoker = true")
    option_sql = f" WITH ({', '.join(options)})" if options else ""
    prefix = "CREATE OR REPLACE VIEW" if replace else "CREATE VIEW"
    sql = f"{prefix} {quote_qualified(view.ref.qname)} ({columns}){option_sql} AS "
    sql += catalog_fragment(view.definition, "View definition")
    if view.check_option != "none":
        sql += f" WITH {view.check_option.upper()} CHECK OPTION"
    return sql


def emit_create_view(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateView):
        raise MigrationError("Create-view handler received a different delta type.")
    statements = [_statement(_create_sql(delta.view, replace=False), delta)]
    if delta.view.owner is not None:
        statements.append(
            _statement(
                f"ALTER VIEW {quote_qualified(delta.view.ref.qname)} "
                f"OWNER TO {quote_ident(delta.view.owner)}",
                delta,
            )
        )
    return tuple(statements)


def emit_drop_view(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropView):
        raise MigrationError("Drop-view handler received a different delta type.")
    return (_statement(f"DROP VIEW {quote_qualified(delta.view.ref.qname)} RESTRICT", delta),)


def emit_replace_view(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, ReplaceView):
        raise MigrationError("Replace-view handler received a different delta type.")
    if delta.incompatible or not delta.old_view.can_be_replaced_by(delta.new_view):
        raise MigrationError(
            "View output column names, order, and types must remain unchanged; "
            "only appended columns are supported."
        )
    return (_statement(_create_sql(delta.new_view, replace=True), delta),)


def emit_alter_view_owner(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterViewOwner):
        raise MigrationError("Alter-view-owner handler received a different delta type.")
    return (
        _statement(
            f"ALTER VIEW {quote_qualified(delta.view.ref.qname)} "
            f"OWNER TO {quote_ident(delta.new_owner)}",
            delta,
        ),
    )


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for every view delta."""
    return {
        CreateView: emit_create_view,
        DropView: emit_drop_view,
        ReplaceView: emit_replace_view,
        AlterViewOwner: emit_alter_view_owner,
    }
