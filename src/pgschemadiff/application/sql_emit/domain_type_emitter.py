"""Emit PostgreSQL domain DDL."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import (
    catalog_fragment,
    quote_ident,
    quote_qualified,
)
from pgschemadiff.domain.delta.domain_type import (
    AddDomainCheck,
    AlterDomainAttrs,
    AlterDomainDefault,
    AlterDomainNullability,
    CreateDomain,
    DropDomain,
    DropDomainCheck,
    ValidateDomainCheck,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.domain_type import DomainCheck


def _statement(sql: str, delta: DeltaBase, *, isolated: bool = False) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta, isolated=isolated)


# PostgreSQL's documented procedure for a domain check: add it NOT VALID, commit,
# wait for transactions that started before that commit, then VALIDATE. The
# wait needs pg_read_all_stats (or equivalent) visibility and fails closed
# without it. ponytail: the wait is bounded only by --statement-timeout (default
# unlimited); add a dedicated drain timeout if long idle transactions are common.
_DOMAIN_CHECK_TRANSACTION_DRAIN = """DO $pgschemadiff$
DECLARE
    old_transaction record;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_stat_activity
        WHERE datname = pg_catalog.current_database()
          AND pid <> pg_catalog.pg_backend_pid()
          AND state IS DISTINCT FROM 'idle'
          AND xact_start IS NULL
    ) THEN
        RAISE EXCEPTION USING MESSAGE =
            'Cannot safely validate a domain check without visibility into all '
            || 'active transactions; grant pg_read_all_stats or drain transactions manually.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_prepared_xacts
        WHERE database = pg_catalog.current_database()
    ) THEN
        RAISE EXCEPTION 'Cannot safely validate a domain check while prepared transactions exist.';
    END IF;

    FOR old_transaction IN
        SELECT pid, backend_start, xact_start
        FROM pg_catalog.pg_stat_activity
        WHERE datname = pg_catalog.current_database()
          AND pid <> pg_catalog.pg_backend_pid()
          AND xact_start IS NOT NULL
    LOOP
        LOOP
            PERFORM pg_catalog.pg_stat_clear_snapshot();
            EXIT WHEN NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_stat_activity
                WHERE pid = old_transaction.pid
                  AND backend_start = old_transaction.backend_start
                  AND xact_start = old_transaction.xact_start
            );
            PERFORM pg_catalog.pg_sleep(0.1);
        END LOOP;
    END LOOP;
END
$pgschemadiff$"""


def _add_check_sql(check: DomainCheck, domain_name: str) -> str:
    expression = catalog_fragment(check.expression, "Domain check expression")
    return (
        f"ALTER DOMAIN {domain_name} ADD CONSTRAINT {quote_ident(check.name)} "
        f"CHECK ({expression}) NOT VALID"
    )


def emit_create_domain(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateDomain):
        raise MigrationError("Create-domain handler received a different delta type.")

    domain = delta.domain
    name = quote_qualified(domain.ref.qname)
    base_type = catalog_fragment(domain.base_type, "Domain base type")
    sql = f"CREATE DOMAIN {name} AS {base_type}"
    if domain.collation is not None:
        sql += f" COLLATE {catalog_fragment(domain.collation, 'Domain collation')}"
    if domain.default_expr is not None:
        sql += f" DEFAULT {catalog_fragment(domain.default_expr, 'Domain default expression')}"
    if domain.not_null:
        sql += " NOT NULL"
    for check in domain.checks:
        if check.validated:
            expression = catalog_fragment(check.expression, "Domain check expression")
            sql += f" CONSTRAINT {quote_ident(check.name)} CHECK ({expression})"

    statements = [_statement(sql, delta)]
    for check in domain.checks:
        if not check.validated:
            statements.append(_statement(_add_check_sql(check, name), delta))
    if domain.owner is not None:
        statements.append(
            _statement(f"ALTER DOMAIN {name} OWNER TO {quote_ident(domain.owner)}", delta)
        )
    return tuple(statements)


def emit_drop_domain(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropDomain):
        raise MigrationError("Drop-domain handler received a different delta type.")
    return (_statement(f"DROP DOMAIN {quote_qualified(delta.domain.ref.qname)} RESTRICT", delta),)


def emit_alter_domain_default(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterDomainDefault):
        raise MigrationError("Alter-domain-default handler received a different delta type.")
    name = quote_qualified(delta.target.qname)
    if delta.new_default_expr is None:
        sql = f"ALTER DOMAIN {name} DROP DEFAULT"
    else:
        default = catalog_fragment(delta.new_default_expr, "Domain default expression")
        sql = f"ALTER DOMAIN {name} SET DEFAULT {default}"
    return (_statement(sql, delta),)


def emit_alter_domain_nullability(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterDomainNullability):
        raise MigrationError("Alter-domain-nullability handler received a different delta type.")
    if delta.new_not_null and delta.used_in_container:
        raise MigrationError("Cannot set domain NOT NULL when the domain is used in a container.")
    action = "SET NOT NULL" if delta.new_not_null else "DROP NOT NULL"
    return (_statement(f"ALTER DOMAIN {quote_qualified(delta.target.qname)} {action}", delta),)


def emit_add_domain_check(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AddDomainCheck):
        raise MigrationError("Add-domain-check handler received a different delta type.")
    if delta.used_in_container:
        raise MigrationError("Cannot add a domain check when the domain is used in a container.")
    name = quote_qualified(delta.target.qname)
    statements = [_statement(_add_check_sql(delta.check, name), delta, isolated=True)]
    if delta.check.validated:
        statements.append(
            _statement(_DOMAIN_CHECK_TRANSACTION_DRAIN, delta, isolated=True),
        )
        statements.append(
            _statement(
                f"ALTER DOMAIN {name} VALIDATE CONSTRAINT {quote_ident(delta.check.name)}",
                delta,
                isolated=True,
            )
        )
    return tuple(statements)


def emit_validate_domain_check(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, ValidateDomainCheck):
        raise MigrationError("Validate-domain-check handler received a different delta type.")
    if delta.used_in_container:
        raise MigrationError(
            "Cannot validate a domain check when the domain is used in a container."
        )
    sql = (
        f"ALTER DOMAIN {quote_qualified(delta.target.qname)} VALIDATE CONSTRAINT "
        f"{quote_ident(delta.check_name)}"
    )
    return (
        _statement(_DOMAIN_CHECK_TRANSACTION_DRAIN, delta, isolated=True),
        _statement(sql, delta, isolated=True),
    )


def emit_drop_domain_check(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropDomainCheck):
        raise MigrationError("Drop-domain-check handler received a different delta type.")
    sql = (
        f"ALTER DOMAIN {quote_qualified(delta.target.qname)} DROP CONSTRAINT "
        f"{quote_ident(delta.check_name)}"
    )
    return (_statement(sql, delta),)


def emit_alter_domain_attrs(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterDomainAttrs):
        raise MigrationError("Alter-domain-attrs handler received a different delta type.")
    sql = (
        f"ALTER DOMAIN {quote_qualified(delta.target.qname)} OWNER TO "
        f"{quote_ident(delta.new_owner)}"
    )
    return (_statement(sql, delta),)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for emittable domain deltas."""
    return {
        CreateDomain: emit_create_domain,
        DropDomain: emit_drop_domain,
        AlterDomainDefault: emit_alter_domain_default,
        AlterDomainNullability: emit_alter_domain_nullability,
        AddDomainCheck: emit_add_domain_check,
        ValidateDomainCheck: emit_validate_domain_check,
        DropDomainCheck: emit_drop_domain_check,
        AlterDomainAttrs: emit_alter_domain_attrs,
    }
