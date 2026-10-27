"""Shared CLI test setup."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _plain_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Rich output free of ANSI codes and wrapping on every runner.

    GitHub Actions sets ``GITHUB_ACTIONS``/``FORCE_COLOR``, which makes Rich
    emit escape sequences that split option names in Typer error panels.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("PGSD_LANG", "en")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
