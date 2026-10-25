"""Emit DDL for PostgreSQL procedures."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import catalog_fragment, quote_ident, quote_qualified
from pgschemadiff.domain.delta.procedure import (
    AlterProcedureOwner,
    CreateProcedure,
    DropProcedure,
    ReplaceProcedure,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.identity import ObjectRef
    from pgschemadiff.domain.procedure import Procedure


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def _procedure_signature(ref: ObjectRef) -> str:
    if ref.arg_signature is None:
        raise MigrationError("Procedure overload identity is missing its argument signature.")
    # Explicit IN markers: without argmodes, DROP/ALTER PROCEDURE also matches the
    # list against all argument types (including OUT) and can become ambiguous.
    argument_types = ", ".join(
        f"IN {catalog_fragment(data_type, 'Procedure argument type')}"
        for data_type in ref.arg_signature
    )
    return f"{quote_qualified(ref.qname)}({argument_types})"


def _require_supported(procedure: Procedure) -> None:
    if not procedure.is_supported:
        raise MigrationError(
            f"Procedure language {procedure.language!r} is unsupported; "
            "only sql and plpgsql are supported."
        )


def _definition(procedure: Procedure) -> str:
    _require_supported(procedure)
    return catalog_fragment(procedure.definition or "", "Procedure definition")


def _create_definition(procedure: Procedure) -> str:
    definition = _definition(procedure)
    prefix = "CREATE OR REPLACE PROCEDURE "
    if not definition.startswith(prefix):
        raise MigrationError("Procedure definition has an unsupported pg_get_functiondef prefix.")
    return f"CREATE PROCEDURE {definition[len(prefix) :]}"


def emit_create_procedure(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateProcedure):
        raise MigrationError("Create-procedure handler received a different delta type.")

    procedure = delta.procedure
    statements = [_statement(_create_definition(procedure), delta)]
    if procedure.owner is not None:
        statements.append(
            _statement(
                f"ALTER PROCEDURE {_procedure_signature(procedure.ref)} "
                f"OWNER TO {quote_ident(procedure.owner)}",
                delta,
            )
        )
    return tuple(statements)


def emit_drop_procedure(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropProcedure):
        raise MigrationError("Drop-procedure handler received a different delta type.")
    _require_supported(delta.procedure)
    return (
        _statement(
            f"DROP PROCEDURE {_procedure_signature(delta.procedure.ref)} RESTRICT",
            delta,
        ),
    )


def emit_replace_procedure(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, ReplaceProcedure):
        raise MigrationError("Replace-procedure handler received a different delta type.")
    if delta.incompatible:
        raise MigrationError("Procedure parameter shape cannot be changed in place.")
    _require_supported(delta.old_procedure)
    return (_statement(_definition(delta.new_procedure), delta),)


def emit_alter_procedure_owner(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterProcedureOwner):
        raise MigrationError("Alter-procedure-owner handler received a different delta type.")
    _require_supported(delta.procedure)
    sql = (
        f"ALTER PROCEDURE {_procedure_signature(delta.procedure.ref)} "
        f"OWNER TO {quote_ident(delta.new_owner)}"
    )
    return (_statement(sql, delta),)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for every procedure delta."""
    return {
        CreateProcedure: emit_create_procedure,
        DropProcedure: emit_drop_procedure,
        ReplaceProcedure: emit_replace_procedure,
        AlterProcedureOwner: emit_alter_procedure_owner,
    }
