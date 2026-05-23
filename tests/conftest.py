"""Top-level pytest configuration.

Session-scoped PostgreSQL container fixture is defined in
``tests/integration/conftest.py`` (Phase 1, task P1-TEST-01) to keep
unit tests fully isolated from Docker.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _set_log_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force JSON log format in tests for deterministic captured output."""
    monkeypatch.setenv("PGSD_LOG_FORMAT", "json")
