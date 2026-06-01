"""Domain-layer port Protocols (task P1-DOM-08).

Defines the boundaries between the domain and the infrastructure layer.
The infrastructure layer implements these Protocols; the application layer
depends only on these interfaces.

**Design rules:**

- These are ``typing.Protocol`` definitions only — no implementation.
- ``@runtime_checkable`` is applied to allow ``isinstance`` checks in tests
  and in the application layer (useful for asserting that a concrete adapter
  actually satisfies the protocol).
- ``async def`` methods use Python's native coroutine syntax.  No ``asyncio``
  import is required here; the coroutine protocol is a language feature, not
  a library import.  This keeps the domain layer clean per ADR-0005.

All models are pure domain: no IO, no async framework imports, no drivers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pgschemadiff.domain.database import Database


@runtime_checkable
class SchemaInspector(Protocol):
    """Port: reads a live PostgreSQL database and returns a ``Database`` snapshot.

    The infrastructure layer provides a concrete implementation
    (``PgCatalogInspector``) that executes ``pg_catalog`` queries via
    psycopg 3 async.  Tests can inject a lightweight stub.

    Example usage in an application use-case::

        async def compare(
            source: SchemaInspector,
            target: SchemaInspector,
        ) -> ...:
            src_db = await source.inspect()
            tgt_db = await target.inspect()
            ...

    """

    async def inspect(self) -> Database:
        """Introspect the connected database and return a ``Database``.

        Raises
        ------
        pgschemadiff.shared.errors.InspectionError
            If the connection fails or a required catalog query returns
            unexpected results.
        """
        ...


@runtime_checkable
class MigrationWriter(Protocol):
    """Port: writes a migration plan to one or more output files.

    The infrastructure layer provides a concrete implementation that creates
    ``up.sql``, ``down.sql``, and ``manifest.json`` files (ADR-0008).
    """

    async def write(
        self,
        migration_sql: str,
        *,
        label: str,
    ) -> str:
        """Persist the migration SQL and return the output path.

        Parameters
        ----------
        migration_sql:
            The full SQL script to write.
        label:
            A human-readable migration name used to derive the output
            file name (e.g. ``"add_users_table"``).

        Returns
        -------
        str
            Absolute path to the written migration file.

        Raises
        ------
        pgschemadiff.shared.errors.MigrationError
            If the file cannot be created or written.
        """
        ...
