"""Shared CLI test setup."""

from __future__ import annotations

import asyncio
import warnings

import pytest


@pytest.fixture(autouse=True)
def _close_implicit_event_loop() -> None:
    """Close the idle loop pytest-asyncio leaves current before ``asyncio.run``.

    pytest-asyncio implicitly creates a current loop via ``get_event_loop()``
    around async tests; the commands' ``asyncio.run`` replaces it without
    closing it, and its socket pair later leaks as a ``ResourceWarning``.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
    if not loop.is_running():
        loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture(autouse=True)
def _plain_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Rich output free of ANSI codes and wrapping on every runner.

    GitHub Actions sets ``GITHUB_ACTIONS``/``FORCE_COLOR``, which makes Rich
    emit escape sequences that split option names in Typer error panels.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
