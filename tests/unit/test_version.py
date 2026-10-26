from __future__ import annotations

from importlib import metadata, reload
from typing import TYPE_CHECKING

from typer.testing import CliRunner

import pgschemadiff
from pgschemadiff.presentation.cli.main import app

if TYPE_CHECKING:
    import pytest


def test_version_comes_from_distribution_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = "9.8.7"

    try:
        with monkeypatch.context() as patch:
            patch.setattr(metadata, "version", lambda _name: expected)
            reload(pgschemadiff)
            assert pgschemadiff.__version__ == expected
    finally:
        reload(pgschemadiff)


def test_version_falls_back_when_distribution_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_distribution(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(metadata, "version", missing_distribution)
            reload(pgschemadiff)
            assert pgschemadiff.__version__ == "0+unknown"
    finally:
        reload(pgschemadiff)


def test_pgsd_version_reports_installed_distribution_metadata() -> None:
    expected = metadata.version("pgschemadiff")
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"pgschemadiff {expected}\n"
