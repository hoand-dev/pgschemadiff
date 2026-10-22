"""Unit tests for ``pgschemadiff.infrastructure.postgres.pool`` (task P1-INFRA-01).

These tests do NOT require a live PostgreSQL instance.  They verify:

- Public API surface (Pool is importable and has the correct interface)
- Type alias ``ConnectionPool`` is exported
- Pool raises ``RuntimeError`` when ``acquire()`` is called outside a
  context-manager block
- Pool construction with various parameter combinations produces the right
  internal state
- ``__aenter__`` / ``__aexit__`` delegate correctly to the underlying
  ``AsyncConnectionPool`` (verified via monkeypatching)
"""

from __future__ import annotations

import asyncio

import psycopg_pool
import pytest

from pgschemadiff.infrastructure.postgres.pool import ConnectionPool, Pool

# ---------------------------------------------------------------------------
# Importability and type alias
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_connection_pool_type_alias_is_importable() -> None:
    """``ConnectionPool`` must be importable and be based on AsyncConnectionPool."""
    # ConnectionPool is a parameterized generic alias of AsyncConnectionPool,
    # so we check its __origin__ instead of identity equality.
    origin = getattr(ConnectionPool, "__origin__", ConnectionPool)
    assert origin is psycopg_pool.AsyncConnectionPool


@pytest.mark.unit
def test_pool_is_importable() -> None:
    """``Pool`` must be importable."""
    assert Pool is not None


# ---------------------------------------------------------------------------
# Constructor parameter storage
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pool_stores_conninfo() -> None:
    pool = Pool("postgresql://localhost/test")
    assert pool._conninfo == "postgresql://localhost/test"


@pytest.mark.unit
def test_pool_default_sizes() -> None:
    """Default min_size=1, max_size defaults to min_size."""
    pool = Pool("postgresql://localhost/test")
    assert pool._min_size == 1
    assert pool._max_size == 1


@pytest.mark.unit
def test_pool_explicit_sizes() -> None:
    pool = Pool("postgresql://localhost/test", min_size=2, max_size=8)
    assert pool._min_size == 2
    assert pool._max_size == 8


@pytest.mark.unit
def test_pool_max_size_defaults_to_min_size() -> None:
    """When ``max_size`` is omitted it mirrors ``min_size``."""
    pool = Pool("postgresql://localhost/test", min_size=3)
    assert pool._max_size == 3


@pytest.mark.unit
def test_pool_timeout_defaults() -> None:
    pool = Pool("postgresql://localhost/test")
    assert pool._open_timeout == 30.0
    assert pool._connection_timeout == 30.0


@pytest.mark.unit
def test_pool_explicit_timeouts() -> None:
    pool = Pool("postgresql://localhost/test", open_timeout=10.0, connection_timeout=5.0)
    assert pool._open_timeout == 10.0
    assert pool._connection_timeout == 5.0


@pytest.mark.unit
def test_pool_starts_without_underlying_pool() -> None:
    """``_pool`` must be ``None`` before entering the async context."""
    pool = Pool("postgresql://localhost/test")
    assert pool._pool is None


# ---------------------------------------------------------------------------
# acquire() outside context manager
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_acquire_outside_context_raises_runtime_error() -> None:
    """Calling ``acquire()`` before entering the context must raise ``RuntimeError``."""
    pool = Pool("postgresql://localhost/test")
    with pytest.raises(RuntimeError, match="async with Pool"):
        async with pool.acquire():
            pass  # pragma: no cover


# ---------------------------------------------------------------------------
# Context manager lifecycle (with mocked underlying pool)
# ---------------------------------------------------------------------------


class _OpenTrackingPool:
    """Minimal fake pool that tracks open() and close() calls."""

    def __init__(self) -> None:
        self.opened_wait: bool | None = None
        self.opened_timeout: float | None = None
        self.close_called: bool = False

    async def open(self, *, wait: bool, timeout: float) -> None:
        self.opened_wait = wait
        self.opened_timeout = timeout

    async def close(self) -> None:
        self.close_called = True


@pytest.mark.unit
async def test_aenter_opens_pool_and_returns_self(monkeypatch: pytest.MonkeyPatch) -> None:
    """``__aenter__`` should open the underlying pool and return the ``Pool`` instance."""
    fake = _OpenTrackingPool()

    monkeypatch.setattr(
        psycopg_pool,
        "AsyncConnectionPool",
        lambda **_kw: fake,
    )

    pool = Pool("postgresql://localhost/test", open_timeout=15.0)
    result = await pool.__aenter__()
    assert result is pool
    assert pool._pool is not None
    assert fake.opened_wait is True
    assert fake.opened_timeout == 15.0

    # Cleanup: call aexit manually
    await pool.__aexit__(None, None, None)
    assert fake.close_called
    assert pool._pool is None


class _CancelledOpenPool(_OpenTrackingPool):
    async def open(self, *, wait: bool, timeout: float) -> None:
        raise asyncio.CancelledError


class _OpenAndCloseFailingPool(_OpenTrackingPool):
    def __init__(self, open_error: BaseException, close_error: BaseException) -> None:
        super().__init__()
        self.open_error = open_error
        self.close_error = close_error

    async def open(self, *, wait: bool, timeout: float) -> None:
        raise self.open_error

    async def close(self) -> None:
        self.close_called = True
        raise self.close_error


@pytest.mark.unit
async def test_aenter_closes_underlying_pool_when_open_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _CancelledOpenPool()
    monkeypatch.setattr(
        psycopg_pool,
        "AsyncConnectionPool",
        lambda **_kw: fake,
    )

    pool = Pool("postgresql://localhost/test")
    with pytest.raises(asyncio.CancelledError):
        await pool.__aenter__()

    assert fake.close_called
    assert pool._pool is None


@pytest.mark.unit
async def test_aenter_preserves_open_error_when_close_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    open_error = RuntimeError("original open failure")
    close_error = RuntimeError("postgresql://user:cleanup-secret@host/db cleanup failure")
    fake = _OpenAndCloseFailingPool(open_error, close_error)
    monkeypatch.setattr(
        psycopg_pool,
        "AsyncConnectionPool",
        lambda **_kw: fake,
    )
    pool = Pool("postgresql://localhost/test")

    with pytest.raises(RuntimeError, match="original open failure") as exc_info:
        await pool.__aenter__()

    assert exc_info.value is open_error
    assert fake.close_called
    assert pool._pool is None
    diagnostics = "\n".join(getattr(open_error, "__notes__", []))
    assert "RuntimeError" in diagnostics
    assert "details omitted" in diagnostics
    assert "cleanup-secret" not in diagnostics


@pytest.mark.unit
async def test_aexit_closes_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """``__aexit__`` must close the underlying pool and set ``_pool`` to ``None``."""
    fake = _OpenTrackingPool()

    monkeypatch.setattr(
        psycopg_pool,
        "AsyncConnectionPool",
        lambda **_kw: fake,
    )

    pool = Pool("postgresql://localhost/test")
    await pool.__aenter__()
    await pool.__aexit__(None, None, None)

    assert fake.close_called
    assert pool._pool is None


@pytest.mark.unit
async def test_aexit_noop_when_pool_is_none() -> None:
    """``__aexit__`` must not raise if the pool was never opened."""
    pool = Pool("postgresql://localhost/test")
    # Should not raise
    await pool.__aexit__(None, None, None)
    assert pool._pool is None


@pytest.mark.unit
async def test_aexit_called_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pool is closed even when the body of the context raises."""
    fake = _OpenTrackingPool()

    monkeypatch.setattr(
        psycopg_pool,
        "AsyncConnectionPool",
        lambda **_kw: fake,
    )

    pool = Pool("postgresql://localhost/test")
    with pytest.raises(ValueError, match="boom"):
        async with pool:
            raise ValueError("boom")

    assert fake.close_called
    assert pool._pool is None
