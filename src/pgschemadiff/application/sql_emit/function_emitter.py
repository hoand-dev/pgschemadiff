"""Emit DDL for PostgreSQL functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import catalog_fragment, quote_ident, quote_qualified
from pgschemadiff.domain.delta.function import (
    AlterFunctionOwner,
    CreateFunction,
    DropFunction,
    ReplaceFunction,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.function import Function
    from pgschemadiff.domain.identity import ObjectRef


def _statement(sql: str, delta: DeltaBase) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=True, delta=delta)


def _function_signature(ref: ObjectRef) -> str:
    if ref.arg_signature is None:
        raise MigrationError("Function overload identity is missing its argument signature.")
    argument_types = ", ".join(
        catalog_fragment(data_type, "Function argument type") for data_type in ref.arg_signature
    )
    return f"{quote_qualified(ref.qname)}({argument_types})"


def _require_supported(function: Function) -> None:
    if not function.is_supported:
        raise MigrationError(
            f"Function language {function.language!r} is unsupported; "
            "only sql and plpgsql are supported."
        )


def _definition(function: Function) -> str:
    _require_supported(function)
    return catalog_fragment(function.definition or "", "Function definition")


def _create_definition(function: Function) -> str:
    definition = _definition(function)
    prefix = "CREATE OR REPLACE FUNCTION "
    if not definition.startswith(prefix):
        raise MigrationError("Function definition has an unsupported pg_get_functiondef prefix.")
    return f"CREATE FUNCTION {definition[len(prefix) :]}"


def emit_create_function(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateFunction):
        raise MigrationError("Create-function handler received a different delta type.")
    if delta.default_conflict:
        raise MigrationError("Function default conflict may make overload calls ambiguous.")

    function = delta.function
    statements = [_statement(_create_definition(function), delta)]
    if function.owner is not None:
        statements.append(
            _statement(
                f"ALTER FUNCTION {_function_signature(function.ref)} "
                f"OWNER TO {quote_ident(function.owner)}",
                delta,
            )
        )
    return tuple(statements)


def emit_drop_function(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropFunction):
        raise MigrationError("Drop-function handler received a different delta type.")
    _require_supported(delta.function)
    return (_statement(f"DROP FUNCTION {_function_signature(delta.function.ref)} RESTRICT", delta),)


def emit_replace_function(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, ReplaceFunction):
        raise MigrationError("Replace-function handler received a different delta type.")
    if delta.incompatible:
        raise MigrationError("Function return or parameter shape cannot be changed in place.")
    if delta.default_conflict:
        raise MigrationError("Function default conflict may make overload calls ambiguous.")
    _require_supported(delta.old_function)
    return (_statement(_definition(delta.new_function), delta),)


def emit_alter_function_owner(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, AlterFunctionOwner):
        raise MigrationError("Alter-function-owner handler received a different delta type.")
    _require_supported(delta.function)
    sql = (
        f"ALTER FUNCTION {_function_signature(delta.function.ref)} "
        f"OWNER TO {quote_ident(delta.new_owner)}"
    )
    return (_statement(sql, delta),)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for every function delta."""
    return {
        CreateFunction: emit_create_function,
        DropFunction: emit_drop_function,
        ReplaceFunction: emit_replace_function,
        AlterFunctionOwner: emit_alter_function_owner,
    }
