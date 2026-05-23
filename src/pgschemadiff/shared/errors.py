"""Common exception hierarchy used across layers."""

from __future__ import annotations


class PgSchemaDiffError(Exception):
    """Base class for all pgschemadiff errors."""


class DomainError(PgSchemaDiffError):
    """Invalid state or constraint violation in a domain model."""


class InspectionError(PgSchemaDiffError):
    """Raised by the infrastructure layer when introspection fails."""


class DiffError(PgSchemaDiffError):
    """Raised by the diff engine for unrecoverable comparison failures."""


class CyclicDependencyError(DiffError):
    """The dependency graph for a migration contains an unbreakable cycle."""


class MigrationError(PgSchemaDiffError):
    """Raised by the SQL emitter or applier when a migration cannot proceed."""


class BlockedMigrationError(MigrationError):
    """A change is blocked because PostgreSQL cannot express it safely."""
