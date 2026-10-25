"""Build the default exact-type SQL handler registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit import (
    column_emitter,
    composite_type_emitter,
    constraint_emitter,
    domain_type_emitter,
    enum_emitter,
    index_emitter,
    schema_emitter,
    sequence_emitter,
    table_emitter,
)
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.application.sql_emit.emitter import SqlHandler
    from pgschemadiff.domain.delta import DeltaBase


def default_handlers() -> dict[type[DeltaBase], SqlHandler]:
    """Return a fresh mapping covering every current concrete delta type."""
    handlers: dict[type[DeltaBase], SqlHandler] = {}
    for emitter_handlers in (
        table_emitter.handlers(),
        column_emitter.handlers(),
        composite_type_emitter.handlers(),
        domain_type_emitter.handlers(),
        index_emitter.handlers(),
        constraint_emitter.handlers(),
        enum_emitter.handlers(),
        schema_emitter.handlers(),
        sequence_emitter.handlers(),
    ):
        for delta_type, handler in emitter_handlers.items():
            if delta_type in handlers:
                raise MigrationError(
                    f"Duplicate SQL handler registration for {delta_type.__name__}."
                )
            handlers[delta_type] = handler
    return handlers
