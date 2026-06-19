"""Async connection pool wrapper (task P1-INFRA-01).

Provides a thin async context-manager facade around
``psycopg_pool.AsyncConnectionPool``.  The pool is opened lazily on context
entry and closed on context exit, following ADR-0002 and the MVP simplification
in ADR-0012 (single connection, REPEATABLE READ).

Usage::

    async with Pool("postgresql://user:pass@localhost/db") as pool:
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")

No business logic lives here — this file is infrastructure glue only.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg_pool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Public type alias callers can use to annotate pool parameters.
ConnectionPool = psycopg_pool.AsyncConnectionPool[psycopg.AsyncConnection[Any]]


class Pool:
    """Async context-manager wrapper around :class:`psycopg_pool.AsyncConnectionPool`.

    Parameters
    ----------
    conninfo:
        A libpq connection string or DSN (e.g. ``"postgresql://user:pass@host/db"``
        or ``"host=localhost dbname=mydb"``).
    min_size:
        Minimum number of connections kept open in the pool.
    max_size:
        Maximum number of connections the pool may open.  Defaults to
        ``min_size`` (fixed-size pool), matching the MVP single-connection
        simplification described in ADR-0012.
    open_timeout:
        Seconds to wait for the pool to reach ``min_size`` connections on open.
    connection_timeout:
        Seconds to wait when acquiring a connection from the pool.
    """

    def __init__(
        self,
        conninfo: str,
        *,
        min_size: int = 1,
        max_size: int | None = None,
        open_timeout: float = 30.0,
        connection_timeout: float = 30.0,
    ) -> None:
        self._conninfo = conninfo
        self._min_size = min_size
        self._max_size = max_size if max_size is not None else min_size
        self._open_timeout = open_timeout
        self._connection_timeout = connection_timeout
        self._pool: ConnectionPool | None = None

    # ------------------------------------------------------------------
    # Async context-manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Pool:
        """Open the underlying pool and wait until ``min_size`` connections exist."""
        pool: ConnectionPool = psycopg_pool.AsyncConnectionPool(
            conninfo=self._conninfo,
            min_size=self._min_size,
            max_size=self._max_size,
            timeout=self._connection_timeout,
            # Do not open automatically in the constructor — we call open()
            # explicitly so we can pass wait=True for synchronous readiness.
            open=False,
        )
        await pool.open(wait=True, timeout=self._open_timeout)
        self._pool = pool
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Close the pool and release all connections."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        """Async context manager that yields a connection from the pool.

        The connection is returned to the pool on exit.  If the transaction
        is still open it will be rolled back automatically by psycopg.

        Raises
        ------
        RuntimeError
            If called outside an ``async with Pool(...) as pool:`` block.
        psycopg_pool.PoolTimeout
            If no connection becomes available within ``connection_timeout``.
        """
        if self._pool is None:
            raise RuntimeError(
                "Pool.acquire() called outside an 'async with Pool(...)' block. "
                "Use 'async with Pool(...) as pool: async with pool.acquire() as conn: ...'."
            )
        async with self._pool.connection() as conn:
            yield conn
