"""Tests for migration application ports."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pgschemadiff.application.migration.model import MigrationPlan
    from pgschemadiff.application.migration.ports import MigrationWriter


def _require_migration_writer(writer: MigrationWriter) -> None:
    pass


@pytest.mark.unit
def test_migration_writer_protocol_accepts_structural_implementation() -> None:
    class StubWriter:
        def write(self, plan: MigrationPlan, output_dir: Path) -> Path:
            return output_dir / plan.id

    module_name = "pgschemadiff.application.migration.ports"
    assert importlib.util.find_spec(module_name) is not None
    migration_ports = importlib.import_module(module_name)

    _require_migration_writer(StubWriter())
    assert isinstance(StubWriter(), migration_ports.MigrationWriter)
    assert not inspect.iscoroutinefunction(migration_ports.MigrationWriter.write)
