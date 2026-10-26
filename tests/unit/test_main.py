from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

import pgschemadiff.__main__ as entrypoint
from pgschemadiff.presentation.composition import TuiDependencies
from pgschemadiff.presentation.tui import PgsdApp

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_module_entrypoint_launches_supported_tui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launched: list[PgsdApp] = []
    config_path = tmp_path / "profiles.yaml"

    def fake_run(app: PgsdApp) -> None:
        launched.append(app)

    monkeypatch.setattr(PgsdApp, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["pgschemadiff", "--config", str(config_path)])

    entrypoint.main()

    assert len(launched) == 1
    assert isinstance(launched[0].dependencies, TuiDependencies)
    assert launched[0].dependencies is not None
    assert launched[0].dependencies.profile_loader.config_path == config_path
