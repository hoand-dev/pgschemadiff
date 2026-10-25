"""Top-level pytest configuration.

Session-scoped PostgreSQL container fixture is defined in
``tests/integration/conftest.py`` (Phase 1, task P1-TEST-01) to keep
unit tests fully isolated from Docker.
"""

from __future__ import annotations

import asyncio
import inspect
import warnings

import pytest


@pytest.fixture(autouse=True)
def _set_log_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force JSON log format in tests for deterministic captured output."""
    monkeypatch.setenv("PGSD_LOG_FORMAT", "json")


@pytest.fixture(autouse=True)
def _close_implicit_event_loop(request: pytest.FixtureRequest) -> None:
    """Close the idle loop pytest-asyncio leaves current before a sync test.

    pytest-asyncio implicitly creates a current loop via ``get_event_loop()``
    around async tests. A later sync test calling ``asyncio.run`` (the CLI
    commands do) replaces it without closing it, and its socket pair then
    surfaces as an unraisable ``ResourceWarning`` in an unrelated test or at
    session teardown. Async tests are skipped so their runner loop is untouched.
    """
    if inspect.iscoroutinefunction(getattr(request, "function", None)):
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
    if not loop.is_running():
        loop.close()
    asyncio.set_event_loop(None)
