"""Emit DDL for PostgreSQL materialized views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import catalog_fragment, quote_ident, quote_qualified
from pgschemadiff.domain.delta.materialized_view import (
    AlterMaterializedViewOwner,
    CreateMaterializedView,
    DropMaterializedView,
    ReplaceMaterializedView,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.materialized_view import MaterializedView


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def _create_sql(view: MaterializedView) -> str:
    columns = ", ".join(quote_ident(name) for name, _ in view.columns)
    sql = f"CREATE MATERIALIZED VIEW {quote_qualified(view.ref.qname)} ({columns})"
    if view.access_method is not None:
        sql += f" USING {quote_ident(view.access_method)}"
    if view.storage_parameters:
        sql += f" WITH ({', '.join(view.storage_parameters)})"
    if view.tablespace is not None:
        sql += f" TABLESPACE {quote_ident(view.tablespace)}"
    definition = catalog_fragment(view.definition, "Materialized-view definition").rstrip()
    sql += f" AS {definition.removesuffix(';').rstrip()} WITH DATA"
    return sql


def _create_statements(view: MaterializedView, delta: DeltaBase) -> tuple[SqlStatement, ...]:
    statements = [_statement(_create_sql(view), delta)]
    if view.owner is not None:
        statements.append(
            _statement(
                f"ALTER MATERIALIZED VIEW {quote_qualified(view.ref.qname)} "
                f"OWNER TO {quote_ident(view.owner)}",
                delta,
            )
        )
    return tuple(statements)


def emit_create_materialized_view(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateMaterializedView):
        raise MigrationError("Create-materialized-view handler received a different delta type.")
    return _create_statements(delta.materialized_view, delta)


def emit_drop_materialized_view(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropMaterializedView):
        raise MigrationError("Drop-materialized-view handler received a different delta type.")
    return (
        _statement(
            f"DROP MATERIALIZED VIEW {quote_qualified(delta.materialized_view.ref.qname)} RESTRICT",
            delta,
        ),
    )


def emit_replace_materialized_view(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, ReplaceMaterializedView):
        raise MigrationError("Replace-materialized-view handler received a different delta type.")
    return (
        _statement(
            f"DROP MATERIALIZED VIEW {quote_qualified(delta.old_materialized_view.ref.qname)} "
            "RESTRICT",
            delta,
        ),
        *_create_statements(delta.new_materialized_view, delta),
    )


def emit_alter_materialized_view_owner(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterMaterializedViewOwner):
        raise MigrationError(
            "Alter-materialized-view-owner handler received a different delta type."
        )
    return (
        _statement(
            f"ALTER MATERIALIZED VIEW {quote_qualified(delta.materialized_view.ref.qname)} "
            f"OWNER TO {quote_ident(delta.new_owner)}",
            delta,
        ),
    )


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for every materialized-view delta."""
    return {
        CreateMaterializedView: emit_create_materialized_view,
        DropMaterializedView: emit_drop_materialized_view,
        ReplaceMaterializedView: emit_replace_materialized_view,
        AlterMaterializedViewOwner: emit_alter_materialized_view_owner,
    }
