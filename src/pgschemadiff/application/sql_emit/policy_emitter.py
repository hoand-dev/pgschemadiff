"""Emit DDL for PostgreSQL row-level security policies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import catalog_fragment, quote_ident, quote_qualified
from pgschemadiff.domain.delta.policy import AlterPolicy, CreatePolicy, DropPolicy, ReplacePolicy
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.policy import Policy


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def _roles_sql(roles: tuple[str, ...]) -> str:
    if not roles:
        raise MigrationError("Policy must have at least one role.")
    return ", ".join("PUBLIC" if role == "public" else quote_ident(role) for role in roles)


def _create_sql(policy: Policy) -> str:
    mode = "PERMISSIVE" if policy.permissive else "RESTRICTIVE"
    command = str(policy.command)
    if command not in {"ALL", "SELECT", "INSERT", "UPDATE", "DELETE"}:
        raise MigrationError(f"Unsupported policy command {command!r}.")
    sql = (
        f"CREATE POLICY {quote_ident(policy.ref.qname.name)} "
        f"ON {quote_qualified(policy.table_ref.qname)} AS {mode} "
        f"FOR {command} TO {_roles_sql(policy.roles)}"
    )
    if policy.using_expr is not None:
        sql += f" USING ({catalog_fragment(policy.using_expr, 'USING expression')})"
    if policy.with_check_expr is not None:
        sql += f" WITH CHECK ({catalog_fragment(policy.with_check_expr, 'WITH CHECK expression')})"
    return sql


def _drop_sql(policy: Policy) -> str:
    return (
        f"DROP POLICY {quote_ident(policy.ref.qname.name)} "
        f"ON {quote_qualified(policy.table_ref.qname)}"
    )


def emit_create_policy(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreatePolicy):
        raise MigrationError("Create-policy handler received a different delta type.")
    return (_statement(_create_sql(delta.policy), delta),)


def emit_drop_policy(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropPolicy):
        raise MigrationError("Drop-policy handler received a different delta type.")
    return (_statement(_drop_sql(delta.policy), delta),)


def emit_alter_policy(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterPolicy):
        raise MigrationError("Alter-policy handler received a different delta type.")
    clauses = []
    if delta.new_roles is not None:
        clauses.append(f"TO {_roles_sql(delta.new_roles)}")
    if delta.new_using_expr is not None:
        clauses.append(f"USING ({catalog_fragment(delta.new_using_expr, 'USING expression')})")
    if delta.new_with_check_expr is not None:
        clauses.append(
            f"WITH CHECK ({catalog_fragment(delta.new_with_check_expr, 'WITH CHECK expression')})"
        )
    if not clauses:
        raise MigrationError("Alter-policy delta contains no changed clauses.")
    return (
        _statement(
            f"ALTER POLICY {quote_ident(delta.policy.ref.qname.name)} "
            f"ON {quote_qualified(delta.policy.table_ref.qname)} {' '.join(clauses)}",
            delta,
        ),
    )


def emit_replace_policy(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, ReplacePolicy):
        raise MigrationError("Replace-policy handler received a different delta type.")
    return (
        _statement(_drop_sql(delta.old_policy), delta),
        _statement(_create_sql(delta.new_policy), delta),
    )


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for every policy delta."""
    return {
        CreatePolicy: emit_create_policy,
        DropPolicy: emit_drop_policy,
        AlterPolicy: emit_alter_policy,
        ReplacePolicy: emit_replace_policy,
    }
