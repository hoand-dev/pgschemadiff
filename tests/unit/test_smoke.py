"""Phase 0 smoke tests — verify the package imports and the CLI is wired up."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import pgschemadiff
from pgschemadiff.presentation.cli.main import app
from pgschemadiff.shared import errors
from pgschemadiff.shared import logging as log_module


@pytest.mark.unit
def test_package_has_version() -> None:
    assert isinstance(pgschemadiff.__version__, str)
    assert pgschemadiff.__version__ != ""


@pytest.mark.unit
def test_cli_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "pgschemadiff" in result.stdout


@pytest.mark.unit
def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pgsd" in result.stdout.lower() or "compare" in result.stdout.lower()


@pytest.mark.unit
def test_error_hierarchy() -> None:
    assert issubclass(errors.DomainError, errors.PgSchemaDiffError)
    assert issubclass(errors.InspectionError, errors.PgSchemaDiffError)
    assert issubclass(errors.CyclicDependencyError, errors.DiffError)
    assert issubclass(errors.BlockedMigrationError, errors.MigrationError)


@pytest.mark.unit
def test_logging_configures_without_error() -> None:
    log_module.configure_logging(level="DEBUG", fmt="json")
    logger = log_module.get_logger("smoke", run_id="test")
    logger.info("smoke_event", value=1)
