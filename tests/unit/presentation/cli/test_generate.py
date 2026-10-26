from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import psycopg
from typer.testing import CliRunner

import pgschemadiff.presentation.cli.commands.generate as generate_command
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import CreateSchema, DeltaSet, DropSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.presentation import composition
from pgschemadiff.presentation.cli.main import app
from pgschemadiff.shared.errors import DiffError, InspectionError

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path
    from typing import Any

    import pytest

    from pgschemadiff.application.migration.model import MigrationPlan


def test_generate_help_exposes_arguments_and_options() -> None:
    result = CliRunner().invoke(
        app,
        ["generate", "--help"],
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
    assert "--out" in result.output
    assert "--schema" in result.output
    assert "--renames" in result.output
    assert "--max-risk" in result.output
    assert "--name" in result.output
    assert "default: dangerous" in result.output
    assert "default: diff" in result.output


def _run_async(coroutine: Coroutine[Any, Any, object]) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def _create_schema(name: str) -> CreateSchema:
    ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )
    return CreateSchema(target=ref, pg_schema=Schema(ref=ref))


def _drop_schema(name: str) -> DropSchema:
    ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )
    return DropSchema(target=ref, pg_schema=Schema(ref=ref))


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
    monkeypatch.setattr(generate_command, "asyncio", SimpleNamespace(run=_run_async), raising=False)

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


def _patch_compare(
    monkeypatch: pytest.MonkeyPatch,
    delta_set: DeltaSet,
) -> list[object | None]:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )
    renames_seen: list[object | None] = []

    async def compare_schemas(
        _source: FakeInspector,
        _target: FakeInspector,
        *,
        renames: object | None = None,
    ) -> SimpleNamespace:
        renames_seen.append(renames)
        return SimpleNamespace(deltas=delta_set)

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )
    return renames_seen


def test_generate_writes_bundle_with_cli_options_and_prints_path_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    pools, inspectors = _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )
    deltas = DeltaSet.from_iterable((_create_schema("app"),))
    renames_seen: list[object | None] = []

    async def compare_schemas(
        _source: FakeInspector,
        _target: FakeInspector,
        *,
        renames: object | None = None,
    ) -> SimpleNamespace:
        renames_seen.append(renames)
        return SimpleNamespace(deltas=deltas)

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )
    rename_path = tmp_path / "renames.yaml"
    loaded_renames = object()
    monkeypatch.setattr(
        generate_command,
        "load_renames",
        lambda path: loaded_renames if path == rename_path else None,
        raising=False,
    )

    generation_calls: list[tuple[RiskLevel, str]] = []

    def generate(
        delta_set: DeltaSet,
        *,
        max_risk: RiskLevel,
        slug: str,
    ) -> MigrationPlan:
        generation_calls.append((max_risk, slug))
        return generate_migration(delta_set, max_risk=max_risk, slug=slug)

    monkeypatch.setattr(generate_command, "generate_migration", generate, raising=False)

    class FakeWriter:
        def __init__(self) -> None:
            self.calls: list[tuple[MigrationPlan, Path]] = []

        def write(self, plan: MigrationPlan, output_dir: Path) -> Path:
            self.calls.append((plan, output_dir))
            bundle_path = output_dir / "bundle"
            bundle_path.mkdir()
            return bundle_path

    writer = FakeWriter()
    monkeypatch.setattr(
        generate_command,
        "FilesystemMigrationWriter",
        lambda: writer,
        raising=False,
    )

    result = CliRunner().invoke(
        app,
        [
            "generate",
            source_url,
            target_url,
            "--out",
            str(tmp_path),
            "--schema",
            "public",
            "--schema",
            "sales",
            "--renames",
            str(rename_path),
            "--max-risk",
            "warning",
            "--name",
            "nightly",
        ],
    )

    bundle_path = tmp_path / "bundle"
    assert result.exit_code == 0
    assert result.stdout == f"{bundle_path}\n"
    assert "deltas=1" in result.stderr
    assert "max-risk=safe" in result.stderr
    assert "units=1" in result.stderr
    assert generation_calls == [(RiskLevel.WARNING, "nightly")]
    assert len(writer.calls) == 1
    assert writer.calls[0][1] == tmp_path
    assert writer.calls[0][0].slug == "nightly"
    assert bundle_path.is_dir()
    assert renames_seen == [loaded_renames]
    assert [pool.conninfo for pool in pools] == [source_url, target_url]
    assert [inspector.schemas for inspector in inspectors] == [["public", "sales"]] * 2
    assert all(pool.entered and pool.exited for pool in pools)


def test_empty_diff_reports_no_changes_without_generating_or_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_compare(monkeypatch, DeltaSet())

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("empty diff must not generate or write a bundle")

    monkeypatch.setattr(generate_command, "generate_migration", unexpected, raising=False)
    monkeypatch.setattr(generate_command, "FilesystemMigrationWriter", unexpected, raising=False)

    result = CliRunner().invoke(
        app,
        ["generate", "postgresql://source/db", "postgresql://target/db", "--out", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "No schema changes." in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_risk_gate_rejection_exits_two_and_shows_offending_delta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_url = "postgresql://alice:source-secret@source/db"
    target_url = "postgresql://bob:target-secret@target/db"
    _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )

    async def compare_schemas(
        _source: FakeInspector,
        _target: FakeInspector,
        **_kwargs: object,
    ) -> SimpleNamespace:
        return SimpleNamespace(deltas=DeltaSet.from_iterable((_drop_schema("legacy"),)))

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )

    result = CliRunner().invoke(
        app,
        ["generate", source_url, target_url, "--out", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "Migration risk gate failed" in result.stderr
    assert 'target="public"."legacy"' in result.stderr
    assert "level=destructive" in result.stderr
    assert "source-secret" not in result.output
    assert "target-secret" not in result.output
    assert source_url not in result.output
    assert target_url not in result.output


def test_connection_failure_redacts_urls_and_driver_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingPool:
        async def __aenter__(self) -> FailingPool:
            raise psycopg.OperationalError("password=driver-secret")

        async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
            return None

    monkeypatch.setattr(generate_command, "asyncio", SimpleNamespace(run=_run_async), raising=False)
    monkeypatch.setattr(composition, "Pool", lambda *_args, **_kwargs: FailingPool())
    source_url = "postgresql://alice:url-secret@source/db"
    target_url = "postgresql://bob:other-secret@target/db"

    result = CliRunner().invoke(
        app,
        ["generate", source_url, target_url, "--out", "."],
    )

    assert result.exit_code == 1
    assert "Database connection failed." in result.stderr
    assert source_url not in result.output
    assert target_url not in result.output
    assert "url-secret" not in result.output
    assert "other-secret" not in result.output
    assert "driver-secret" not in result.output
    assert "driver-secret" not in caplog.text


def test_inspection_failure_exits_one_without_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_compare(monkeypatch, DeltaSet())

    async def compare_schemas(
        _source: FakeInspector,
        _target: FakeInspector,
        **_kwargs: object,
    ) -> DeltaSet:
        raise InspectionError("inspection-private-detail")

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )
    result = CliRunner().invoke(
        app,
        ["generate", "postgresql://source/db", "postgresql://target/db", "--out", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Schema inspection failed." in result.stderr
    assert "inspection-private-detail" not in result.output


def test_comparison_failure_exits_one_without_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_compare(monkeypatch, DeltaSet())

    async def compare_schemas(
        _source: FakeInspector,
        _target: FakeInspector,
        **_kwargs: object,
    ) -> DeltaSet:
        raise DiffError("comparison-private-detail")

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )
    result = CliRunner().invoke(
        app,
        ["generate", "postgresql://source/db", "postgresql://target/db", "--out", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Schema comparison failed." in result.stderr
    assert "comparison-private-detail" not in result.output


def test_unexpected_comparison_failure_exits_one_without_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_compare(monkeypatch, DeltaSet())

    async def compare_schemas(
        _source: FakeInspector,
        _target: FakeInspector,
        **_kwargs: object,
    ) -> DeltaSet:
        raise RuntimeError("unexpected-comparison-private-detail")

    monkeypatch.setattr(
        composition,
        "compare_schemas_with_snapshots",
        compare_schemas,
        raising=False,
    )
    result = CliRunner().invoke(
        app,
        ["generate", "postgresql://source/db", "postgresql://target/db", "--out", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Schema diff failed." in result.stderr
    assert "unexpected-comparison-private-detail" not in result.output


def test_writer_failure_exits_one_without_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_compare(monkeypatch, DeltaSet.from_iterable((_create_schema("app"),)))

    class FailingWriter:
        def write(self, _plan: object, _output_dir: Path) -> Path:
            raise OSError("writer-private-detail")

    monkeypatch.setattr(
        generate_command,
        "FilesystemMigrationWriter",
        FailingWriter,
        raising=False,
    )
    result = CliRunner().invoke(
        app,
        ["generate", "postgresql://source/db", "postgresql://target/db", "--out", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Migration bundle writing failed." in result.stderr
    assert "writer-private-detail" not in result.output


def test_invalid_name_exits_one_with_validation_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_compare(monkeypatch, DeltaSet.from_iterable((_create_schema("app"),)))
    result = CliRunner().invoke(
        app,
        [
            "generate",
            "postgresql://source/db",
            "postgresql://target/db",
            "--out",
            str(tmp_path),
            "--name",
            "bad/name",
        ],
    )

    assert result.exit_code == 1
    assert "Migration generation failed:" in result.stderr
    assert "lowercase ASCII" in result.stderr


def test_unexpected_generation_failure_exits_one_without_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_compare(monkeypatch, DeltaSet.from_iterable((_create_schema("app"),)))

    def generate(_delta_set: DeltaSet, **_kwargs: object) -> object:
        raise RuntimeError("generation-private-detail")

    monkeypatch.setattr(generate_command, "generate_migration", generate, raising=False)
    result = CliRunner().invoke(
        app,
        ["generate", "postgresql://source/db", "postgresql://target/db", "--out", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Migration generation failed." in result.stderr
    assert "generation-private-detail" not in result.output


def test_missing_output_directory_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_compare(monkeypatch, DeltaSet.from_iterable((_create_schema("app"),)))
    missing_dir = tmp_path / "missing"

    result = CliRunner().invoke(
        app,
        ["generate", "postgresql://source/db", "postgresql://target/db", "--out", str(missing_dir)],
    )

    assert result.exit_code == 1
    assert "Migration bundle writing failed." in result.stderr
    assert not missing_dir.exists()


def test_invalid_max_risk_is_typer_usage_error() -> None:
    result = CliRunner().invoke(
        app,
        [
            "generate",
            "postgresql://source/db",
            "postgresql://target/db",
            "--out",
            ".",
            "--max-risk",
            "invalid",
        ],
    )

    assert result.exit_code == 2
    assert "--max-risk" in result.output
    assert "invalid" in result.output
