"""Ordered dispatch from domain deltas to SQL statements."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from pgschemadiff.domain.delta import DeltaBase, DeltaSet
from pgschemadiff.shared.errors import MigrationError


@dataclass(frozen=True)
class SqlStatement:
    """One forward SQL statement and its execution/provenance metadata."""

    sql: str
    transactional: bool
    delta: DeltaBase

    def __post_init__(self) -> None:
        if not self.sql.strip():
            raise MigrationError("SQL statement must not be blank.")


SqlHandler = Callable[[DeltaBase], Iterable[SqlStatement]]


class SqlEmitter:
    """Dispatch deltas to exact-type handlers without changing their order."""

    def __init__(self, handlers: Mapping[type[DeltaBase], SqlHandler]) -> None:
        self._handlers = dict(handlers)

    def emit(self, deltas: DeltaSet) -> tuple[SqlStatement, ...]:
        statements: list[SqlStatement] = []
        for delta in deltas:
            handler = self._handlers.get(type(delta))
            if handler is None:
                raise MigrationError(
                    f"No SQL handler registered for delta type {type(delta).__name__}."
                )

            emitted = tuple(handler(delta))
            if not emitted:
                raise MigrationError(
                    f"SQL handler for {type(delta).__name__} emitted no statements."
                )

            for statement in emitted:
                if statement.delta is not delta:
                    raise MigrationError(
                        f"SQL statement provenance does not match {type(delta).__name__}."
                    )
                statements.append(statement)

        return tuple(statements)
