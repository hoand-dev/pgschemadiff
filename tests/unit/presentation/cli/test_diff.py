from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

import psycopg
from typer.testing import CliRunner

import pgschemadiff.presentation.cli.commands.diff as diff_command
from pgschemadiff.application.diff.renames import RenameAnnotations
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta.base import DeltaSet
from pgschemadiff.domain.delta.schema import CreateExtension
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.presentation import composition
from pgschemadiff.presentation.cli.main import app
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path
    from typing import Any

    import pytest


def _run_async(coroutine: Coroutine[Any, Any, object]) -> object:
    # Keep CLI tests from replacing pytest-asyncio's process-wide event loop.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def test_diff_command_is_registered() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "diff" in result.output


def test_diff_help_exposes_two_urls_and_optional_flags() -> None:
    result = CliRunner().invoke(
        app,
        ["diff", "--help"],
        env={
            "NO_COLOR": "1",
            "TERM": "dumb",
            "COLUMNS": "120",
            "FORCE_COLOR": None,
            "GITHUB_ACTIONS": None,
        },
    )

    assert result.exit_code == 0
    assert "SOURCE_URL" in result.output
    assert "TARGET_URL" in result.output
    assert "--schema" in result.output
    assert "--renames" in result.output


class FakePool:
    def __init__(self, conninfo: str) -> None:
        self.conninfo = conninfo
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> FakePool:
        self.entered = True
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.exited = True


class FakeInspector:
    def __init__(self, pool: FakePool, schemas: list[str] | None, database: Database) -> None:
        self.pool = pool
        self.schemas = schemas
        self.database = database

    async def inspect(self) -> Database:
        return self.database


def _patch_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
    databases: dict[str, Database],
) -> tuple[list[FakePool], list[FakeInspector]]:
    pools: list[FakePool] = []
    inspectors: list[FakeInspector] = []
    monkeypatch.setattr(diff_command, "asyncio", SimpleNamespace(run=_run_async))

    def make_pool(conninfo: str, **_kwargs: object) -> FakePool:
        pool = FakePool(conninfo)
        pools.append(pool)
        return pool

    def make_inspector(pool: FakePool, *, schemas: list[str] | None = None) -> FakeInspector:
        inspector = FakeInspector(pool, schemas, databases[pool.conninfo])
        inspectors.append(inspector)
        return inspector

    monkeypatch.setattr(composition, "Pool", make_pool)
    monkeypatch.setattr(composition, "PgCatalogInspector", make_inspector)
    return pools, inspectors


def test_compare_urls_uses_composition_helper_with_connection_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )
    deltas = DeltaSet()
    renames = RenameAnnotations()
    calls: list[tuple[str, str, list[str] | None, object | None]] = []

    async def fake_compare_conninfo(
        source_conninfo: str,
        target_conninfo: str,
        schemas: list[str] | None,
        *,
        renames: object | None = None,
    ) -> SimpleNamespace:
        calls.append((source_conninfo, target_conninfo, schemas, renames))
        return SimpleNamespace(deltas=deltas)

    monkeypatch.setattr(composition, "compare_conninfo", fake_compare_conninfo, raising=False)

    result = _run_async(diff_command.compare_urls(source_url, target_url, ["app"], renames=renames))

    assert result is deltas
    assert calls == [(source_url, target_url, ["app"], renames)]


def test_diff_passes_positional_urls_and_repeated_schemas_to_both_inspectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    pools, inspectors = _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )

    result = CliRunner().invoke(
        app,
        ["diff", source_url, target_url, "--schema", "public", "--schema", "sales"],
    )

    assert result.exit_code == 0
    assert [pool.conninfo for pool in pools] == [source_url, target_url]
    assert [inspector.schemas for inspector in inspectors] == [["public", "sales"]] * 2
    assert all(pool.entered and pool.exited for pool in pools)


def test_diff_loads_rename_annotations_only_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )
    rename_path = tmp_path / "renames.yaml"
    loaded_renames = object()
    load_calls: list[Path] = []
    compare_renames: list[object | None] = []

    def load_renames(path: Path) -> object:
        load_calls.append(path)
        return loaded_renames

    async def compare_schemas(
        _source: FakeInspector,
        _target: FakeInspector,
        *,
        renames: object | None = None,
    ) -> SimpleNamespace:
        compare_renames.append(renames)
        return SimpleNamespace(deltas=DeltaSet())

    monkeypatch.setattr(diff_command, "load_renames", load_renames, raising=False)
    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )

    runner = CliRunner()
    without_renames = runner.invoke(app, ["diff", source_url, target_url])
    with_renames = runner.invoke(
        app,
        ["diff", source_url, target_url, "--renames", str(rename_path)],
    )

    assert without_renames.exit_code == with_renames.exit_code == 0
    assert load_calls == [rename_path]
    assert compare_renames == [None, loaded_renames]


def test_diff_prints_parseable_typed_delta_json(monkeypatch: pytest.MonkeyPatch) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )

    async def compare_schemas(
        _source: FakeInspector, _target: FakeInspector, **_kwargs: object
    ) -> SimpleNamespace:
        return SimpleNamespace(deltas=DeltaSet())

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )

    result = CliRunner().invoke(app, ["diff", source_url, target_url])

    assert result.exit_code == 0
    assert result.stdout.strip()
    serialized = json.loads(result.stdout)
    assert DeltaSet.model_validate(serialized) == DeltaSet()


def test_diff_compares_database_wide_extensions_under_schema_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    extension = Extension(
        ref=ObjectRef(
            kind=ObjectKind.EXTENSION,
            qname=QualifiedName(namespace="public", name="pgcrypto"),
        ),
        version="1.3",
    )
    _, inspectors = _patch_infrastructure(
        monkeypatch,
        {
            source_url: Database(name="source"),
            target_url: Database(name="target", extensions=(extension,)),
        },
    )

    result = CliRunner().invoke(
        app,
        ["diff", source_url, target_url, "--schema", "public"],
    )

    assert result.exit_code == 0
    assert [inspector.schemas for inspector in inspectors] == [["public"], ["public"]]
    deltas = DeltaSet.model_validate_json(result.stdout)
    assert len(deltas.deltas) == 1
    assert isinstance(deltas.deltas[0], CreateExtension)


def test_diff_reports_errors_to_stderr_with_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )

    async def compare_schemas(
        _source: FakeInspector, _target: FakeInspector, **_kwargs: object
    ) -> DeltaSet:
        raise RuntimeError("private failure detail")

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )

    result = CliRunner().invoke(app, ["diff", source_url, target_url])

    assert result.exit_code == 1
    assert "Error:" in result.stderr
    assert "private failure detail" not in result.stderr


def test_diff_error_redacts_detail_from_output_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )

    async def compare_schemas(
        _source: FakeInspector, _target: FakeInspector, **_kwargs: object
    ) -> DeltaSet:
        raise DiffError("diff-secret-marker")

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )

    result = CliRunner().invoke(app, ["diff", source_url, target_url])

    assert result.exit_code == 1
    assert "Schema comparison failed." in result.stderr
    assert "diff-secret-marker" not in result.stderr
    assert "diff-secret-marker" not in result.output
    assert "diff-secret-marker" not in caplog.text


class FailingPool:
    async def __aenter__(self) -> FailingPool:
        raise psycopg.OperationalError("password=driver-secret")

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None


def test_connection_error_redacts_dsn_and_driver_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(diff_command, "asyncio", SimpleNamespace(run=_run_async))
    monkeypatch.setattr(composition, "Pool", lambda *_args, **_kwargs: FailingPool())

    result = CliRunner().invoke(
        app,
        [
            "diff",
            "postgresql://alice:url-secret@source/db",
            "postgresql://bob:other-secret@target/db",
        ],
    )

    assert result.exit_code == 1
    assert "postgresql://alice:url-secret@source/db" not in result.output
    assert "postgresql://bob:other-secret@target/db" not in result.output
    assert "url-secret" not in result.output
    assert "other-secret" not in result.output
    assert "driver-secret" not in result.output
    assert "driver-secret" not in caplog.text
