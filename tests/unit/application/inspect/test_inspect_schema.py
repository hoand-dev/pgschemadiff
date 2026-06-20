"""Unit tests for the ``inspect_schema`` use case and ``pgsd inspect`` CLI command.

Tests are intentionally free of any live PostgreSQL dependency.  A minimal
stub ``SchemaInspector`` (``FakeInspector``) returns a pre-built ``Database``
domain object so the application use-case and CLI wiring can be exercised
end-to-end without hitting the network.

Coverage goals:
- ``inspect_schema()`` returns valid JSON containing expected top-level fields.
- ``pgsd inspect <conn-url>`` exits with code 0 and emits parseable JSON.
- The JSON output contains ``"name"``, ``"schemas"``, and ``"extensions"`` keys.
- ``pgsd inspect`` with a failing inspector exits with code 1.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Callable

import pytest
import typer
from typer.testing import CliRunner

from pgschemadiff.application.inspect.inspect_schema import inspect_schema
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.presentation.cli.commands.inspect import inspect_cmd
from pgschemadiff.presentation.cli.main import app
from pgschemadiff.shared.errors import InspectionError

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _schema_ref(name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.SCHEMA, qname=QualifiedName(namespace=name, name=name))


def _table_ref(schema: str, name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace=schema, name=name))


def _ext_ref(name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.EXTENSION, qname=QualifiedName(namespace="public", name=name))


def _make_minimal_database() -> Database:
    """Build a minimal ``Database`` domain object for use in stubs."""
    col = Column(name="id", position=1, data_type="integer", nullable=False)
    tbl = Table(ref=_table_ref("public", "users"), columns=(col,))
    schema = Schema(ref=_schema_ref("public"), tables=(tbl,))
    ext = Extension(ref=_ext_ref("pgcrypto"), version="1.3")
    return Database(name="testdb", schemas=(schema,), extensions=(ext,))


class FakeInspector:
    """Minimal ``SchemaInspector`` stub — returns a fixed ``Database`` snapshot."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def inspect(self) -> Database:
        return self._database


class FailingInspector:
    """``SchemaInspector`` stub that raises ``InspectionError`` on ``inspect()``."""

    async def inspect(self) -> Database:
        raise InspectionError("connection refused")


# ---------------------------------------------------------------------------
# Use-case unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_inspect_schema_returns_json_string() -> None:
    """``inspect_schema()`` must return a non-empty string."""
    db = _make_minimal_database()
    inspector = FakeInspector(db)
    result = await inspect_schema(inspector)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.unit
async def test_inspect_schema_output_is_valid_json() -> None:
    """The returned string must be parseable as JSON."""
    db = _make_minimal_database()
    inspector = FakeInspector(db)
    result = await inspect_schema(inspector)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.unit
async def test_inspect_schema_json_has_top_level_fields() -> None:
    """JSON must contain 'name', 'schemas', and 'extensions' at the top level."""
    db = _make_minimal_database()
    inspector = FakeInspector(db)
    result = await inspect_schema(inspector)
    parsed = json.loads(result)
    assert "name" in parsed
    assert "schemas" in parsed
    assert "extensions" in parsed


@pytest.mark.unit
async def test_inspect_schema_name_matches_database() -> None:
    """The 'name' field in the JSON must match the ``Database.name``."""
    db = _make_minimal_database()
    inspector = FakeInspector(db)
    result = await inspect_schema(inspector)
    parsed = json.loads(result)
    assert parsed["name"] == "testdb"


@pytest.mark.unit
async def test_inspect_schema_schemas_list() -> None:
    """``schemas`` in the JSON must be a list containing the expected schema name."""
    db = _make_minimal_database()
    inspector = FakeInspector(db)
    result = await inspect_schema(inspector)
    parsed = json.loads(result)
    schema_names = [s["ref"]["qname"]["name"] for s in parsed["schemas"]]
    assert "public" in schema_names


@pytest.mark.unit
async def test_inspect_schema_extensions_list() -> None:
    """``extensions`` in the JSON must be a list containing the expected extension."""
    db = _make_minimal_database()
    inspector = FakeInspector(db)
    result = await inspect_schema(inspector)
    parsed = json.loads(result)
    ext_names = [e["ref"]["qname"]["name"] for e in parsed["extensions"]]
    assert "pgcrypto" in ext_names


@pytest.mark.unit
async def test_inspect_schema_propagates_inspection_error() -> None:
    """``inspect_schema()`` must propagate ``InspectionError`` from the inspector."""
    inspector = FailingInspector()
    with pytest.raises(InspectionError, match="connection refused"):
        await inspect_schema(inspector)


@pytest.mark.unit
async def test_inspect_schema_empty_database() -> None:
    """An empty database (no schemas, no extensions) must still yield valid JSON."""
    db = Database(name="empty")
    inspector = FakeInspector(db)
    result = await inspect_schema(inspector)
    parsed = json.loads(result)
    assert parsed["name"] == "empty"
    assert parsed["schemas"] == []
    assert parsed["extensions"] == []


# ---------------------------------------------------------------------------
# inspect_cmd() direct unit tests
#
# We test ``inspect_cmd`` by patching ``asyncio.run`` with a side_effect that
# ALWAYS closes the coroutine it receives before returning or raising.
#
# Why: ``asyncio.run(_run())`` — Python evaluates ``_run()`` first (creating a
# coroutine), then passes it to the mock.  If the mock ignores the coroutine
# (e.g. uses ``return_value=`` without consuming it), Python emits a
# ``RuntimeWarning: coroutine '...' was never awaited`` on garbage collection.
# pytest turns this into a ``PytestUnraisableExceptionWarning`` error because
# of the ``filterwarnings = ["error"]`` configuration.
# ---------------------------------------------------------------------------


def _json_for(db: Database) -> str:
    """Return the JSON string the use case would produce for *db*."""
    return db.model_dump_json(indent=2)


def _make_asyncio_run_stub(
    return_value: str | None = None,
    exc: Exception | None = None,
) -> Callable[[object], str]:
    """Return a ``side_effect`` callable for patching ``asyncio.run``.

    The stub ALWAYS closes the coroutine it receives so Python does not emit a
    ``RuntimeWarning: coroutine '...' was never awaited``, which pytest (with
    ``filterwarnings = ["error"]``) would turn into a test failure.

    Parameters
    ----------
    return_value:
        The string to return on success.
    exc:
        An exception to raise after closing the coroutine (error path).
    """

    def _stub(coro: object) -> str:
        # Always close coroutine to suppress ResourceWarning / RuntimeWarning
        if hasattr(coro, "close"):
            coro.close()
        if exc is not None:
            raise exc
        return return_value or ""

    return _stub


@pytest.mark.unit
def test_inspect_cmd_prints_json_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """``inspect_cmd`` must write valid JSON to stdout on success."""
    db = _make_minimal_database()

    with patch(
        "pgschemadiff.presentation.cli.commands.inspect.asyncio.run",
        side_effect=_make_asyncio_run_stub(return_value=_json_for(db)),
    ):
        inspect_cmd(conn_url="postgresql://localhost/mydb", schemas=None)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["name"] == "testdb"


@pytest.mark.unit
def test_inspect_cmd_raises_exit_on_inspection_error() -> None:
    """``inspect_cmd`` must raise ``typer.Exit(code=1)`` on InspectionError."""
    with (
        patch(
            "pgschemadiff.presentation.cli.commands.inspect.asyncio.run",
            side_effect=_make_asyncio_run_stub(exc=InspectionError("fail")),
        ),
        pytest.raises(typer.Exit) as exc_info,
    ):
        inspect_cmd(conn_url="postgresql://localhost/mydb", schemas=None)

    assert exc_info.value.exit_code == 1


@pytest.mark.unit
def test_inspect_cmd_passes_schemas_to_run() -> None:
    """The ``schemas`` argument must cause ``asyncio.run`` to be called once."""
    db = _make_minimal_database()

    calls: list[int] = []

    def tracking_stub(coro: object) -> str:
        if hasattr(coro, "close"):
            coro.close()
        calls.append(1)
        return _json_for(db)

    with patch(
        "pgschemadiff.presentation.cli.commands.inspect.asyncio.run",
        side_effect=tracking_stub,
    ):
        inspect_cmd(conn_url="postgresql://localhost/mydb", schemas=["public"])

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# CLI command tests (via Typer CliRunner)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_inspect_exits_zero_and_emits_json() -> None:
    """``pgsd inspect <url>`` must exit 0 and print parseable JSON to stdout."""
    db = _make_minimal_database()
    runner = CliRunner()

    with patch(
        "pgschemadiff.presentation.cli.commands.inspect.asyncio.run",
        side_effect=_make_asyncio_run_stub(return_value=_json_for(db)),
    ):
        result = runner.invoke(app, ["inspect", "postgresql://localhost/mydb"])

    assert result.exit_code == 0, f"stdout={result.stdout!r} exc={result.exception}"
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    assert "name" in parsed
    assert "schemas" in parsed
    assert "extensions" in parsed


@pytest.mark.unit
def test_cli_inspect_json_contains_table() -> None:
    """The JSON emitted by the CLI must contain the expected table nested inside schemas."""
    db = _make_minimal_database()
    runner = CliRunner()

    with patch(
        "pgschemadiff.presentation.cli.commands.inspect.asyncio.run",
        side_effect=_make_asyncio_run_stub(return_value=_json_for(db)),
    ):
        result = runner.invoke(app, ["inspect", "postgresql://localhost/mydb"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    # Navigate into schemas → tables
    public_schema = next(
        (s for s in parsed["schemas"] if s["ref"]["qname"]["name"] == "public"), None
    )
    assert public_schema is not None
    table_names = [t["ref"]["qname"]["name"] for t in public_schema["tables"]]
    assert "users" in table_names


@pytest.mark.unit
def test_cli_inspect_exits_one_on_inspection_error() -> None:
    """``pgsd inspect`` must exit with code 1 when inspection raises InspectionError."""
    runner = CliRunner()

    with patch(
        "pgschemadiff.presentation.cli.commands.inspect.asyncio.run",
        side_effect=_make_asyncio_run_stub(exc=InspectionError("boom")),
    ):
        result = runner.invoke(app, ["inspect", "postgresql://localhost/mydb"])

    assert result.exit_code == 1


@pytest.mark.unit
def test_cli_inspect_error_message_in_output() -> None:
    """When the inspector fails, the error message must appear in the CLI output."""
    runner = CliRunner()

    with patch(
        "pgschemadiff.presentation.cli.commands.inspect.asyncio.run",
        side_effect=_make_asyncio_run_stub(exc=InspectionError("refused")),
    ):
        result = runner.invoke(app, ["inspect", "postgresql://localhost/mydb"])

    assert result.exit_code == 1
    assert "Error" in result.output


@pytest.mark.unit
def test_cli_inspect_with_schema_filter_passes_schemas() -> None:
    """``--schema public`` must result in ``inspect_cmd`` being called with schemas=['public']."""
    db = _make_minimal_database()

    schemas_seen: list[list[str] | None] = []

    def capturing_inspect_cmd(conn_url: str, schemas: list[str] | None) -> None:
        schemas_seen.append(schemas)
        # Call the real implementation with asyncio.run safely stubbed
        with patch(
            "pgschemadiff.presentation.cli.commands.inspect.asyncio.run",
            side_effect=_make_asyncio_run_stub(return_value=_json_for(db)),
        ):
            inspect_cmd(conn_url=conn_url, schemas=schemas)

    runner = CliRunner()
    with patch("pgschemadiff.presentation.cli.main.inspect_cmd", side_effect=capturing_inspect_cmd):
        result = runner.invoke(
            app,
            ["inspect", "postgresql://localhost/mydb", "--schema", "public"],
        )

    assert result.exit_code == 0
    assert schemas_seen == [["public"]]


@pytest.mark.unit
def test_cli_inspect_help_text() -> None:
    """``pgsd inspect --help`` must exit 0 and mention the conn-url or postgresql."""
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", "--help"])
    assert result.exit_code == 0
    output_lower = result.stdout.lower()
    assert "conn-url" in output_lower or "postgresql" in output_lower
