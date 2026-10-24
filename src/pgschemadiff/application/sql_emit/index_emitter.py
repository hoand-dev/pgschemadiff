"""Emit concurrent index DDL from catalog-backed index definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.emitter import SqlHandler, SqlStatement
from pgschemadiff.application.sql_emit.quoting import (
    catalog_fragment,
    quote_literal,
    quote_qualified,
)
from pgschemadiff.domain.delta.index import CreateIndex, DropIndex, ReplaceIndex
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.index import Index


def _statement(sql: str, delta: DeltaBase, *, transactional: bool) -> SqlStatement:
    return SqlStatement(sql=sql, transactional=transactional, delta=delta)


def _is_identifier_start(char: str) -> bool:
    return char == "_" or char.isalpha() or ord(char) >= 128


def _is_identifier_part(char: str) -> bool:
    return _is_identifier_start(char) or char.isdigit() or char == "$"


def _read_identifier(sql: str, position: int) -> tuple[str, bool, int] | None:
    if position >= len(sql):
        return None
    if sql[position] == '"':
        position += 1
        value: list[str] = []
        while position < len(sql):
            char = sql[position]
            if char == '"':
                if position + 1 < len(sql) and sql[position + 1] == '"':
                    value.append('"')
                    position += 2
                    continue
                return "".join(value), True, position + 1
            value.append(char)
            position += 1
        return None

    start = position
    if not _is_identifier_start(sql[position]):
        return None
    position += 1
    while position < len(sql) and _is_identifier_part(sql[position]):
        position += 1
    return sql[start:position], False, position


def _find_on_target(sql: str, start: int) -> int | None:
    position = start
    while position < len(sql) and sql[position].isspace():
        position += 1
    index_name = _read_identifier(sql, position)
    if index_name is None:
        return None
    name, quoted_name, position = index_name
    if not quoted_name and name.upper() == "CONCURRENTLY":
        return None

    while position < len(sql) and sql[position].isspace():
        position += 1

    if (
        sql[position : position + 2].upper() != "ON"
        or position + 2 >= len(sql)
        or not sql[position + 2].isspace()
    ):
        return None
    return position + 2


def _matches_qualified_table(definition: str, start: int, namespace: str, table: str) -> bool:
    position = start
    while position < len(definition) and definition[position].isspace():
        position += 1

    namespace_token = _read_identifier(definition, position)
    if namespace_token is None:
        return False
    parsed_namespace, namespace_quoted, position = namespace_token
    while position < len(definition) and definition[position].isspace():
        position += 1
    if position >= len(definition) or definition[position] != ".":
        return False

    position += 1
    while position < len(definition) and definition[position].isspace():
        position += 1
    table_token = _read_identifier(definition, position)
    if table_token is None:
        return False
    parsed_table, table_quoted, position = table_token
    if position < len(definition) and not definition[position].isspace():
        return False

    def matches(actual: str, quoted: bool, expected: str) -> bool:
        if quoted:
            return actual == expected
        if actual.isascii():
            return actual.lower() == expected
        # ponytail: reject caseful Unicode; exact folding needs the server locale.
        if actual != actual.lower():
            return False
        return actual == expected

    return matches(parsed_namespace, namespace_quoted, namespace) and matches(
        parsed_table, table_quoted, table
    )


def _create_definition(index: Index) -> str:
    definition = catalog_fragment(index.definition or "", "Index definition")
    if definition.startswith("CREATE UNIQUE INDEX "):
        prefix = "CREATE UNIQUE INDEX "
    elif definition.startswith("CREATE INDEX "):
        prefix = "CREATE INDEX "
    else:
        raise MigrationError("Index definition has an unsupported pg_get_indexdef prefix.")

    target_start = _find_on_target(definition, len(prefix))
    table = index.table_ref.qname
    if target_start is None or not _matches_qualified_table(
        definition, target_start, table.namespace, table.name
    ):
        raise MigrationError("Index definition must reference its expected schema-qualified table.")
    return f"{prefix.rstrip()} CONCURRENTLY {definition[len(prefix) :]}"


def _check_standalone(index: Index) -> None:
    if index.constraint_name is not None:
        raise MigrationError("Constraint-backed indexes must be changed through constraint DDL.")


def emit_create_index(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, CreateIndex):
        raise MigrationError("Create-index handler received a different delta type.")
    _check_standalone(delta.index)

    statements = [_statement(_create_definition(delta.index), delta, transactional=False)]
    if delta.index.comment is not None:
        statements.append(
            _statement(
                f"COMMENT ON INDEX {quote_qualified(delta.index.ref.qname)} "
                f"IS {quote_literal(delta.index.comment)}",
                delta,
                transactional=True,
            )
        )
    return tuple(statements)


def emit_drop_index(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, DropIndex):
        raise MigrationError("Drop-index handler received a different delta type.")
    _check_standalone(delta.index)
    return (
        _statement(
            f"DROP INDEX CONCURRENTLY {quote_qualified(delta.index.ref.qname)}",
            delta,
            transactional=False,
        ),
    )


def emit_replace_index(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    if not isinstance(delta, ReplaceIndex):
        raise MigrationError("Replace-index handler received a different delta type.")
    _check_standalone(delta.old_index)
    _check_standalone(delta.new_index)

    statements = [
        _statement(
            f"DROP INDEX CONCURRENTLY {quote_qualified(delta.old_index.ref.qname)}",
            delta,
            transactional=False,
        ),
        _statement(_create_definition(delta.new_index), delta, transactional=False),
    ]
    if delta.new_index.comment is not None:
        statements.append(
            _statement(
                f"COMMENT ON INDEX {quote_qualified(delta.new_index.ref.qname)} "
                f"IS {quote_literal(delta.new_index.comment)}",
                delta,
                transactional=True,
            )
        )
    return tuple(statements)


def handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return handlers for exactly the concrete index delta types."""
    return {
        CreateIndex: emit_create_index,
        DropIndex: emit_drop_index,
        ReplaceIndex: emit_replace_index,
    }
