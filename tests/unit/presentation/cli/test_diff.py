from __future__ import annotations

import asyncio
import json
from inspect import signature
from types import SimpleNamespace
from typing import TYPE_CHECKING

import psycopg
import pytest
from typer.testing import CliRunner

import pgschemadiff.presentation.cli.commands.diff as diff_command
from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
from pgschemadiff.application.diff.renames import RenameAnnotations
from pgschemadiff.application.migration.generate import assess_deltas
from pgschemadiff.application.migration.render import target_label
from pgschemadiff.application.sql_emit.risk import RiskAssessment, RiskLevel
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta.base import DeltaSet
from pgschemadiff.domain.delta.schema import CreateExtension, CreateSchema, DropSchema
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.presentation import composition
from pgschemadiff.presentation.cli.main import app
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from pathlib import Path
    from typing import Any


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


def test_root_help_lists_stable_exit_codes() -> None:
    result = CliRunner().invoke(
        app,
        ["--help"],
        env={
            "NO_COLOR": "1",
            "TERM": "dumb",
            "COLUMNS": "120",
            "FORCE_COLOR": None,
            "GITHUB_ACTIONS": None,
        },
    )

    assert result.exit_code == 0
    assert "Exit codes" in result.output
    assert "0  Success" in result.output
    assert "1  Runtime failure" in result.output
    assert "2  Usage or policy" in result.output
    assert "3  Apply failed or cancelled" in result.output


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
    assert "--format" in result.output
    assert "--max-risk" in result.output


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


def _patch_delta_set(monkeypatch: pytest.MonkeyPatch, delta_set: DeltaSet) -> None:
    source_url = "postgresql://source/db"
    target_url = "postgresql://target/db"
    _patch_infrastructure(
        monkeypatch,
        {source_url: Database(name="source"), target_url: Database(name="target")},
    )

    async def compare_schemas(
        _source: FakeInspector,
        _target: FakeInspector,
        **_kwargs: object,
    ) -> SimpleNamespace:
        return SimpleNamespace(deltas=delta_set)

    monkeypatch.setattr(composition, "compare_schemas_with_snapshots", compare_schemas)


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
    calls: list[tuple[str, str, list[str] | None, object | None, object | None]] = []

    async def fake_compare_conninfo(
        source_conninfo: str,
        target_conninfo: str,
        schemas: list[str] | None,
        *,
        renames: object | None = None,
        on_phase: Callable[[str], None] | None = None,
    ) -> SimpleNamespace:
        calls.append((source_conninfo, target_conninfo, schemas, renames, on_phase))
        return SimpleNamespace(deltas=deltas)

    monkeypatch.setattr(composition, "compare_conninfo", fake_compare_conninfo, raising=False)

    result = _run_async(diff_command.compare_urls(source_url, target_url, ["app"], renames=renames))

    assert result is deltas
    assert calls == [(source_url, target_url, ["app"], renames, None)]


def test_compare_urls_forwards_progress_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "on_phase" in signature(diff_command.compare_urls).parameters

    def callback(_phase: str) -> None:
        return None

    forwarded: list[object] = []

    async def fake_compare_conninfo(
        _source: str,
        _target: str,
        _schemas: list[str] | None,
        *,
        renames: object | None = None,
        on_phase: object | None = None,
    ) -> SimpleNamespace:
        _ = renames
        forwarded.append(on_phase)
        return SimpleNamespace(deltas=DeltaSet())

    monkeypatch.setattr(composition, "compare_conninfo", fake_compare_conninfo)

    result = _run_async(
        diff_command.compare_urls(
            "source",
            "target",
            None,
            on_phase=callback,
        )
    )

    assert isinstance(result, DeltaSet)
    assert forwarded == [callback]


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
    assert result.stdout == DeltaSet().model_dump_json(indent=2) + "\n"
    serialized = json.loads(result.stdout)
    assert DeltaSet.model_validate(serialized) == DeltaSet()


def test_diff_summary_uses_generator_order_labels_reasons_and_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delta_set = DeltaSet.from_iterable(
        (
            _drop_schema("legacy"),
            _create_schema("[red]x[/]\\"),
        )
    )
    _patch_delta_set(monkeypatch, delta_set)

    result = CliRunner().invoke(
        app,
        ["diff", "postgresql://source/db", "postgresql://target/db", "--format", "summary"],
    )

    assessments = assess_deltas(delta_set)
    lines = result.stdout.splitlines()
    assert result.exit_code == 0
    assert "[red]x[/]\\" in result.stdout
    for index, (delta_id, assessment) in enumerate(assessments):
        line = lines[index]
        assert line.startswith(f"{delta_id}  {assessment.level.value}")
        assert assessment.delta.model_dump()["kind"] in line
        assert target_label(assessment.delta) in line
        assert assessment.reason in line
    assert lines[-1] == "2 changes: safe=1 warning=0 dangerous=0 destructive=1 blocked=0"


def test_diff_summary_empty_diff_omits_totals(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_delta_set(monkeypatch, DeltaSet())

    result = CliRunner().invoke(
        app,
        ["diff", "postgresql://source/db", "postgresql://target/db", "--format", "summary"],
    )

    assert result.exit_code == 0
    assert result.stdout == "No schema changes.\n"


def _patch_comparison_result(
    monkeypatch: pytest.MonkeyPatch,
    delta_set: DeltaSet,
) -> None:
    monkeypatch.setattr(diff_command, "asyncio", SimpleNamespace(run=_run_async))

    async def compare_conninfo(
        _source_url: str,
        _target_url: str,
        _schemas: list[str] | None,
        **_kwargs: object,
    ) -> SchemaComparisonResult:
        return SchemaComparisonResult(
            source=Database(name="current_db"),
            target=Database(name="desired_db"),
            deltas=delta_set,
        )

    monkeypatch.setattr(composition, "compare_conninfo", compare_conninfo)


def test_diff_html_uses_snapshot_names_and_summary_rows_without_connection_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delta_set = DeltaSet.from_iterable((_drop_schema("legacy"), _create_schema("new")))
    _patch_comparison_result(monkeypatch, delta_set)
    source_url = "postgresql://alice:sentinel-password@source/db"
    target_url = "postgresql://bob:other-secret@target/db"

    result = CliRunner().invoke(
        app,
        ["diff", source_url, target_url, "--format", "html"],
    )

    assert result.exit_code == 0
    assert "<!doctype html>" in result.stdout
    assert "current_db" in result.stdout
    assert "desired_db" in result.stdout
    assert result.stdout.index("d0001") < result.stdout.index("d0002")
    assert "drop_schema" in result.stdout
    assert "create_schema" in result.stdout
    assert "sentinel-password" not in result.stdout
    assert "other-secret" not in result.stdout
    assert "postgresql://" not in result.stdout


def test_diff_html_prints_report_before_max_risk_gate_exits_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_comparison_result(monkeypatch, DeltaSet.from_iterable((_drop_schema("legacy"),)))

    result = CliRunner().invoke(
        app,
        [
            "diff",
            "postgresql://source/db",
            "postgresql://target/db",
            "--format",
            "html",
            "--max-risk",
            "safe",
        ],
    )

    assert result.exit_code == 2
    assert "<!doctype html>" in result.stdout
    assert result.stderr == "Risk gate failed: 1 change(s) exceed max-risk=safe.\n"


def test_diff_max_risk_passes_when_changes_are_within_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delta_set = DeltaSet.from_iterable((_create_schema("new"),))
    _patch_delta_set(monkeypatch, delta_set)

    result = CliRunner().invoke(
        app,
        [
            "diff",
            "postgresql://source/db",
            "postgresql://target/db",
            "--max-risk",
            "safe",
        ],
    )

    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout == delta_set.model_dump_json(indent=2) + "\n"


@pytest.mark.parametrize("output_format", ["json", "summary"])
def test_diff_max_risk_failure_prints_chosen_format_then_exits_two(
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
) -> None:
    _patch_delta_set(monkeypatch, DeltaSet.from_iterable((_drop_schema("legacy"),)))

    result = CliRunner().invoke(
        app,
        [
            "diff",
            "postgresql://source/db",
            "postgresql://target/db",
            "--format",
            output_format,
            "--max-risk",
            "safe",
        ],
    )

    assert result.exit_code == 2
    assert result.stdout
    assert result.stderr == "Risk gate failed: 1 change(s) exceed max-risk=safe.\n"


def test_diff_max_risk_blocked_never_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    delta = _create_schema("blocked")
    _patch_delta_set(monkeypatch, DeltaSet.from_iterable((delta,)))
    monkeypatch.setattr(
        diff_command,
        "assess_deltas",
        lambda _deltas: (("d0001", RiskAssessment(delta, RiskLevel.BLOCKED, "blocked by test")),),
        raising=False,
    )

    result = CliRunner().invoke(
        app,
        [
            "diff",
            "postgresql://source/db",
            "postgresql://target/db",
            "--format",
            "summary",
            "--max-risk",
            "blocked",
        ],
    )

    assert result.exit_code == 0
    assert "blocked by test" in result.stdout
    assert "1 changes: safe=0 warning=0 dangerous=0 destructive=0 blocked=1" in result.stdout
    assert result.stderr == ""


def test_diff_invalid_renames_exits_two_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rename_path = tmp_path / "invalid.yaml"
    monkeypatch.setattr(
        diff_command,
        "load_renames",
        lambda _path: (_ for _ in ()).throw(DiffError("invalid YAML at line 2")),
    )

    def unexpected_pool(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid renames must fail before connecting")

    monkeypatch.setattr(composition, "Pool", unexpected_pool)
    result = CliRunner().invoke(
        app,
        [
            "diff",
            "postgresql://source/db",
            "postgresql://target/db",
            "--renames",
            str(rename_path),
        ],
    )

    assert result.exit_code == 2
    assert result.stderr == "Error: Invalid renames file: invalid YAML at line 2\n"


def test_diff_reports_progress_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_infrastructure(
        monkeypatch,
        {
            "postgresql://source/db": Database(name="source"),
            "postgresql://target/db": Database(name="target"),
        },
    )
    output = getattr(diff_command, "output", None)
    assert output is not None
    progress_calls: list[tuple[int, int, str]] = []
    monkeypatch.setattr(
        output,
        "progress",
        lambda step, total, label: progress_calls.append((step, total, label)),
    )

    result = CliRunner().invoke(
        app,
        ["diff", "postgresql://source/db", "postgresql://target/db"],
    )

    assert result.exit_code == 0
    assert progress_calls == [
        (1, 3, "Inspecting source"),
        (2, 3, "Inspecting target"),
        (3, 3, "Comparing"),
    ]


def test_diff_progress_labels_use_vietnamese(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_infrastructure(
        monkeypatch,
        {
            "postgresql://source/db": Database(name="source"),
            "postgresql://target/db": Database(name="target"),
        },
    )
    output = getattr(diff_command, "output", None)
    assert output is not None
    progress_calls: list[tuple[int, int, str]] = []
    monkeypatch.setattr(
        output,
        "progress",
        lambda step, total, label: progress_calls.append((step, total, label)),
    )

    result = CliRunner().invoke(
        app,
        ["diff", "postgresql://source/db", "postgresql://target/db"],
        env={"PGSD_LANG": "vi"},
    )

    assert result.exit_code == 0
    assert progress_calls == [
        (1, 3, "Đang đọc schema nguồn"),
        (2, 3, "Đang đọc schema đích"),
        (3, 3, "Đang so sánh"),
    ]


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


def test_connection_failure_uses_vietnamese_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingPool:
        async def __aenter__(self) -> FailingPool:
            raise psycopg.OperationalError("private connection detail")

        async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
            return None

    monkeypatch.setattr(diff_command, "asyncio", SimpleNamespace(run=_run_async))
    monkeypatch.setattr(composition, "Pool", lambda *_args, **_kwargs: FailingPool())

    result = CliRunner().invoke(
        app,
        ["diff", "postgresql://source/db", "postgresql://target/db"],
        env={"PGSD_LANG": "vi"},
    )

    assert result.exit_code == 1
    assert result.stderr == "Lỗi: Không kết nối được cơ sở dữ liệu.\n"


def test_risk_gate_error_uses_vietnamese_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_delta_set(
        monkeypatch,
        DeltaSet.from_iterable((_drop_schema("legacy"),)),
    )

    result = CliRunner().invoke(
        app,
        [
            "diff",
            "postgresql://source/db",
            "postgresql://target/db",
            "--max-risk",
            "safe",
        ],
        env={"PGSD_LANG": "vi"},
    )

    assert result.exit_code == 2
    assert result.stderr.startswith("Lỗi: ")


@pytest.mark.parametrize("output_format", ["json", "summary"])
def test_diff_stdout_is_byte_identical_across_languages(
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
) -> None:
    delta_set = DeltaSet.from_iterable((_create_schema("new"),))
    _patch_delta_set(monkeypatch, delta_set)
    runner = CliRunner()
    args = [
        "diff",
        "postgresql://source/db",
        "postgresql://target/db",
        "--format",
        output_format,
    ]

    english = runner.invoke(app, args, env={"PGSD_LANG": "en"})
    vietnamese = runner.invoke(app, args, env={"PGSD_LANG": "vi"})

    assert english.exit_code == vietnamese.exit_code == 0
    assert vietnamese.stdout == english.stdout


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
