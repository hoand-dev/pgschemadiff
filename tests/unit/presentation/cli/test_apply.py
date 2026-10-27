"""Tests for ``pgsd apply`` command orchestration and safety boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from io import StringIO
from types import SimpleNamespace
from typing import TYPE_CHECKING

import psycopg
import psycopg_pool
import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from pgschemadiff.application.diff.fingerprint import schema_fingerprint
from pgschemadiff.application.migration.apply import (
    ApplyResult,
    StatementFinished,
    StatementStarted,
    UnitFailed,
    UnitFinished,
    UnitStarted,
)
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.database import Database
from pgschemadiff.presentation import composition
from pgschemadiff.presentation.cli.commands import apply as apply_command
from pgschemadiff.presentation.cli.main import app
from pgschemadiff.shared.errors import ApplyMigrationError, RiskGateError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from click.testing import Result

    from pgschemadiff.application.migration.bundle import ValidatedBundle

pytestmark = pytest.mark.unit

_SECRET_PASSWORD = "sentinel-password"
_DATABASE_URL = f"postgresql://operator:{_SECRET_PASSWORD}@db.invalid/app"
_STATEMENT = "SELECT 1"
_UP_SQL = f"{_STATEMENT}\n;\n".encode()


def _write_bundle(
    bundle_dir: Path,
    *,
    risk: RiskLevel = RiskLevel.SAFE,
    transactional: bool = True,
) -> Path:
    bundle_dir.mkdir()
    statement_hash = hashlib.sha256(f"{_STATEMENT}\n".encode()).hexdigest()
    manifest = {
        "format_version": 1,
        "tool_version": "test",
        "id": "bundle-test-id",
        "slug": "bundle-test",
        "created_at": "2026-10-24T00:00:00Z",
        "source_fingerprint": None,
        "target_fingerprint": None,
        "delta_count": 1,
        "overall_max_risk": risk.value,
        "assessments": [
            {
                "delta_id": "d0001",
                "kind": "test",
                "target": "app.test",
                "level": risk.value,
                "reason": "test risk",
                "reversible": False,
                "reversibility_reason": "manual reversal required",
            }
        ],
        "units": [
            {
                "index": 0,
                "transactional": transactional,
                "start_line": 1,
                "end_line": 1,
                "max_risk": risk.value,
                "delta_ids": ["d0001"],
                "statements": [{"delta_id": "d0001", "start_line": 1, "end_line": 1}],
                "sql_sha256": statement_hash,
            }
        ],
        "checksums": {"up_sql_sha256": hashlib.sha256(_UP_SQL).hexdigest()},
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (bundle_dir / "up.sql").write_bytes(_UP_SQL)
    (bundle_dir / "down.sql").write_bytes(b"must not be read")
    return bundle_dir


_SOURCE_DATABASE = Database(name="source")
_TARGET_DATABASE = Database(name="target", server_version="17")


def _write_fingerprinted_bundle(bundle_dir: Path) -> Path:
    bundle_dir = _write_bundle(bundle_dir)
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "format_version": 2,
            "inspected_schemas": ["app"],
            "source_fingerprint": schema_fingerprint(_SOURCE_DATABASE),
            "target_fingerprint": schema_fingerprint(_TARGET_DATABASE),
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return bundle_dir


def _invoke(bundle_dir: Path, *options: str) -> Result:
    return CliRunner().invoke(app, ["apply", str(bundle_dir), _DATABASE_URL, *options])


def _assert_password_redacted(result: Result) -> None:
    assert _SECRET_PASSWORD not in result.output


def _interactive(monkeypatch: pytest.MonkeyPatch, is_interactive: bool) -> None:
    monkeypatch.setattr(
        apply_command,
        "sys",
        SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: is_interactive)),
    )


@asynccontextmanager
async def _fake_executor(
    _url: str,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
) -> AsyncIterator[object]:
    _ = lock_timeout_ms, statement_timeout_ms
    yield object()


class _FakeInspector:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def inspect(self) -> Database:
        return self.database


def _patch_inspector(
    monkeypatch: pytest.MonkeyPatch,
    databases: list[Database],
) -> list[tuple[str, list[str] | None]]:
    calls: list[tuple[str, list[str] | None]] = []

    @asynccontextmanager
    async def open_inspector(
        conninfo: str,
        schemas: list[str] | None = None,
    ) -> AsyncIterator[_FakeInspector]:
        calls.append((conninfo, schemas))
        yield _FakeInspector(databases.pop(0))

    class EmptyHistory:
        async def list_history(self) -> tuple[object, ...]:
            return ()

    monkeypatch.setattr(composition, "open_inspector", open_inspector)
    monkeypatch.setattr(
        composition,
        "create_history_reader",
        lambda _conninfo: EmptyHistory(),
    )
    return calls


def _install_successful_apply(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: tuple[object, ...] = (),
    calls: dict[str, object] | None = None,
    resumed: bool = False,
) -> None:
    monkeypatch.setattr(apply_command, "open_executor", _fake_executor)

    async def apply_migration(
        bundle: ValidatedBundle,
        _executor: object,
        *,
        approve_destructive: bool,
        on_event: Callable[[object], None] | None,
    ) -> ApplyResult:
        if calls is not None:
            calls["approve_destructive"] = approve_destructive
            calls["bundle_id"] = bundle.id
        if on_event is not None:
            for event in events:
                on_event(event)
        return ApplyResult(
            bundle_id=bundle.id,
            status="applied",
            unit_count=len(bundle.units),
            applied_unit_count=len(bundle.units),
            resumed=resumed,
            elapsed=0.1,
        )

    monkeypatch.setattr(apply_command, "apply_migration", apply_migration)


def test_apply_help_is_registered() -> None:
    result = CliRunner().invoke(app, ["apply", "--help"])

    assert result.exit_code == 0
    assert "BUNDLE_DIR" in result.stdout
    assert "DB_URL" in result.stdout
    assert "--lock-timeout" in result.stdout
    assert "--statement-timeout" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--yes" in result.stdout
    assert "--skip-source-check" in result.stdout


def test_apply_exit_routes_through_shared_error_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = getattr(apply_command, "output", None)
    assert output is not None
    calls: list[tuple[str, int]] = []

    def error(message: str, code: int) -> None:
        calls.append((message, code))
        raise typer.Exit(code=code)

    monkeypatch.setattr(output, "error", error)

    with pytest.raises(typer.Exit) as raised:
        apply_command._exit("Error: operation failed.", 3)

    assert raised.value.exit_code == 3
    assert calls == [("Error: operation failed.", 3)]


@pytest.mark.parametrize(
    ("option", "value", "expected"),
    [
        ("--lock-timeout", "0", 0),
        ("--lock-timeout", "2ms", 2),
        ("--lock-timeout", "3s", 3_000),
        ("--lock-timeout", "4min", 240_000),
        ("--statement-timeout", "5min", 300_000),
    ],
)
def test_timeout_options_convert_to_milliseconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
    value: str,
    expected: int,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    captured: dict[str, int] = {}

    @asynccontextmanager
    async def open_executor(
        _url: str,
        *,
        lock_timeout_ms: int,
        statement_timeout_ms: int,
    ) -> AsyncIterator[object]:
        captured["lock_timeout_ms"] = lock_timeout_ms
        captured["statement_timeout_ms"] = statement_timeout_ms
        yield object()

    monkeypatch.setattr(apply_command, "open_executor", open_executor)

    async def apply_migration(
        bundle: ValidatedBundle,
        _executor: object,
        *,
        approve_destructive: bool,
        on_event: Callable[[object], None] | None,
    ) -> ApplyResult:
        _ = approve_destructive, on_event
        return ApplyResult(bundle.id, "applied", len(bundle.units), len(bundle.units), False, 0.0)

    monkeypatch.setattr(apply_command, "apply_migration", apply_migration)
    result = _invoke(bundle_dir, option, value)

    assert result.exit_code == 0
    timeout_name = "lock_timeout_ms" if option == "--lock-timeout" else "statement_timeout_ms"
    assert captured[timeout_name] == expected


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--lock-timeout", "-1"),
        ("--lock-timeout", "1.5s"),
        ("--lock-timeout", "1h"),
        ("--statement-timeout", "bad"),
        ("--statement-timeout", "1441min"),
    ],
)
def test_invalid_timeout_exits_two_and_names_option(
    tmp_path: Path,
    option: str,
    value: str,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")

    result = _invoke(bundle_dir, option, value)

    assert result.exit_code == 2
    assert option in result.stderr
    _assert_password_redacted(result)


def test_public_timeout_parser_preserves_units_and_validation() -> None:
    parse_timeout = getattr(apply_command, "parse_timeout", None)
    assert callable(parse_timeout)

    assert parse_timeout("4min", "--lock-timeout") == 240_000
    assert parse_timeout("0", "--statement-timeout") == 0
    with pytest.raises(ValueError, match="Error: Invalid value for --lock-timeout\\."):
        parse_timeout("bad", "--lock-timeout")
    with pytest.raises(ValueError, match="Error: --statement-timeout must not exceed 24 hours\\."):
        parse_timeout("1441min", "--statement-timeout")


def test_filesystem_error_is_generic_and_exits_one(tmp_path: Path) -> None:
    result = _invoke(tmp_path / "missing")

    assert result.exit_code == 1
    assert "Could not read migration bundle." in result.stderr
    _assert_password_redacted(result)


def test_unexpected_preflight_error_is_generic_and_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingReader:
        def read(self, _bundle_dir: Path) -> tuple[bytes, bytes]:
            raise RuntimeError(f"private reader detail {_SECRET_PASSWORD}")

    monkeypatch.setattr(apply_command, "FilesystemBundleReader", FailingReader)
    result = _invoke(tmp_path / "bundle")

    assert result.exit_code == 3
    assert "Migration apply failed." in result.stderr
    assert "private reader detail" not in result.output
    _assert_password_redacted(result)


def test_invalid_bundle_exits_two_without_connecting(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "manifest.json").write_bytes(b"{")
    (bundle_dir / "up.sql").write_bytes(_UP_SQL)

    result = _invoke(bundle_dir)

    assert result.exit_code == 2
    assert "Invalid migration bundle:" in result.stderr
    _assert_password_redacted(result)


def test_blocked_risk_is_rejected_before_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle", risk=RiskLevel.BLOCKED)

    async def unexpected_connection(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("blocked bundle attempted database connection")

    monkeypatch.setattr(apply_command, "check_connectivity", unexpected_connection)
    monkeypatch.setattr(apply_command, "open_executor", unexpected_connection, raising=False)
    result = _invoke(bundle_dir, "--yes")

    assert result.exit_code == 2
    assert "BLOCKED" in result.stderr
    _assert_password_redacted(result)


def test_destructive_apply_requires_yes_when_stdin_is_noninteractive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle", risk=RiskLevel.DESTRUCTIVE)
    _interactive(monkeypatch, False)

    result = _invoke(bundle_dir)

    assert result.exit_code == 2
    assert "requires --yes" in result.stderr
    _assert_password_redacted(result)


@pytest.mark.parametrize("approved", [True, False])
def test_interactive_destructive_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    approved: bool,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle", risk=RiskLevel.DESTRUCTIVE)
    _interactive(monkeypatch, True)
    confirmed: list[str] = []

    def confirm(prompt: str) -> bool:
        confirmed.append(prompt)
        return approved

    monkeypatch.setattr(typer, "confirm", confirm)
    calls: dict[str, object] = {}
    _install_successful_apply(monkeypatch, calls=calls)

    result = _invoke(bundle_dir)

    assert confirmed
    assert result.exit_code == (0 if approved else 2)
    if approved:
        assert calls.get("approve_destructive") is True
    else:
        assert "approve_destructive" not in calls
    _assert_password_redacted(result)


def test_yes_approves_destructive_apply_without_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle", risk=RiskLevel.DESTRUCTIVE)
    _interactive(monkeypatch, True)
    monkeypatch.setattr(
        typer,
        "confirm",
        lambda _prompt: pytest.fail("--yes must bypass confirmation"),
    )
    calls: dict[str, object] = {}
    _install_successful_apply(monkeypatch, calls=calls)

    result = _invoke(bundle_dir, "--yes")

    assert result.exit_code == 0
    assert calls["approve_destructive"] is True


@pytest.mark.parametrize(
    ("risk", "transactional", "warning"),
    [
        (RiskLevel.DESTRUCTIVE, True, True),
        (RiskLevel.SAFE, False, False),
    ],
)
def test_dry_run_prints_units_and_checks_connectivity_without_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    risk: RiskLevel,
    transactional: bool,
    warning: bool,
) -> None:
    bundle_dir = _write_bundle(
        tmp_path / "bundle",
        risk=risk,
        transactional=transactional,
    )
    connected: list[str] = []
    monkeypatch.setattr(
        apply_command,
        "check_connectivity",
        lambda url: _record_connectivity(url, connected),
        raising=False,
    )

    async def unexpected_executor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dry-run opened migration executor")

    monkeypatch.setattr(apply_command, "open_executor", unexpected_executor, raising=False)
    monkeypatch.setattr(
        typer,
        "confirm",
        lambda _prompt: pytest.fail("dry-run must not request confirmation"),
    )

    result = _invoke(bundle_dir, "--dry-run")

    assert result.exit_code == 0
    assert connected == [_DATABASE_URL]
    assert "unit 1/1" in result.stdout.lower()
    mode = "transactional" if transactional else "non-transactional"
    assert mode in result.stdout.lower()
    assert ("destructive" in result.stdout.lower()) is (risk is RiskLevel.DESTRUCTIVE)
    assert "statements=1" in result.stdout.lower()
    assert "d0001" in result.stdout
    assert "lines=1-1" in result.stdout.lower()
    assert "does not prove" in result.stdout.lower()
    assert ("destructive-risk" in result.stderr.lower()) is warning
    _assert_password_redacted(result)


def test_source_mismatch_exits_two_before_destructive_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_fingerprinted_bundle(tmp_path / "bundle")
    found = Database(name="different", server_version="18")
    inspector_calls = _patch_inspector(monkeypatch, [found])
    monkeypatch.setattr(
        typer,
        "confirm",
        lambda _prompt: pytest.fail("source mismatch must precede confirmation"),
    )

    result = _invoke(bundle_dir)

    assert result.exit_code == 2
    assert "Error: Database schema does not match the bundle's source state" in result.stderr
    assert schema_fingerprint(_SOURCE_DATABASE)[7:19] in result.stderr
    assert schema_fingerprint(found)[7:19] in result.stderr
    assert "--skip-source-check after review" in result.stderr
    assert inspector_calls == [(_DATABASE_URL, ["app"])]


def test_skip_source_check_bypasses_inspection_and_dry_run_reports_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_fingerprinted_bundle(tmp_path / "bundle")
    connected: list[str] = []

    @asynccontextmanager
    async def unexpected_inspector(*_args: object, **_kwargs: object) -> AsyncIterator[object]:
        if not _args and not _kwargs:
            yield object()
            return
        raise AssertionError("override must bypass source inspection")

    monkeypatch.setattr(composition, "open_inspector", unexpected_inspector)
    monkeypatch.setattr(
        apply_command,
        "check_connectivity",
        lambda url: _record_connectivity(url, connected),
    )

    result = _invoke(bundle_dir, "--dry-run", "--skip-source-check")

    assert result.exit_code == 0
    assert connected == [_DATABASE_URL]
    assert "Source state check: skipped (--skip-source-check)." in result.stdout
    assert "Warning: Source schema check skipped by --skip-source-check." in result.stderr


def test_dry_run_reports_matching_source_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_fingerprinted_bundle(tmp_path / "bundle")
    inspector_calls = _patch_inspector(monkeypatch, [_SOURCE_DATABASE])
    connected: list[str] = []
    monkeypatch.setattr(
        apply_command,
        "check_connectivity",
        lambda url: _record_connectivity(url, connected),
    )

    result = _invoke(bundle_dir, "--dry-run")

    assert result.exit_code == 0
    assert "Source state check: match." in result.stdout
    assert connected == [_DATABASE_URL]
    assert inspector_calls == [(_DATABASE_URL, ["app"])]


def test_dry_run_reports_applied_bundle_source_check_as_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_fingerprinted_bundle(tmp_path / "bundle")
    _patch_inspector(monkeypatch, [Database(name="already-applied", server_version="99")])

    class AppliedHistory:
        async def list_history(self) -> tuple[object, ...]:
            return (SimpleNamespace(bundle_id="bundle-test-id", status="applied"),)

    monkeypatch.setattr(composition, "create_history_reader", lambda _conninfo: AppliedHistory())
    monkeypatch.setattr(apply_command, "check_connectivity", lambda _url: asyncio.sleep(0))

    result = _invoke(bundle_dir, "--dry-run")

    assert result.exit_code == 0
    assert "Source state check: skipped_applied." in result.stdout
    assert "Source state check: match." not in result.stdout


def test_legacy_bundle_warns_and_skips_source_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    monkeypatch.setattr(
        composition,
        "open_inspector",
        lambda *_args, **_kwargs: pytest.fail("legacy bundle must skip inspection"),
    )
    connected: list[str] = []
    monkeypatch.setattr(
        apply_command,
        "check_connectivity",
        lambda url: _record_connectivity(url, connected),
    )

    result = _invoke(bundle_dir, "--dry-run")

    assert result.exit_code == 0
    assert (
        "Bundle has no source fingerprint (format 1); the database state cannot be verified."
        in result.stderr
    )
    assert connected == [_DATABASE_URL]


def test_legacy_bundle_keeps_warning_when_source_check_override_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    monkeypatch.setattr(
        composition,
        "open_inspector",
        lambda *_args, **_kwargs: pytest.fail("legacy bundle must skip inspection"),
    )
    monkeypatch.setattr(apply_command, "check_connectivity", lambda _url: asyncio.sleep(0))

    result = _invoke(bundle_dir, "--dry-run", "--skip-source-check")

    assert result.exit_code == 0
    assert "Warning: Source schema check skipped by --skip-source-check." in result.stderr
    assert (
        "Bundle has no source fingerprint (format 1); the database state cannot be verified."
        in result.stderr
    )


def test_successful_apply_verifies_desired_schema_after_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_fingerprinted_bundle(tmp_path / "bundle")
    inspector_calls = _patch_inspector(monkeypatch, [_SOURCE_DATABASE, _TARGET_DATABASE])
    _install_successful_apply(monkeypatch)

    result = _invoke(bundle_dir)

    assert result.exit_code == 0
    assert "Verified: database now matches the desired schema." in result.stdout
    assert inspector_calls == [(_DATABASE_URL, ["app"]), (_DATABASE_URL, ["app"])]


def test_skip_source_check_allows_real_apply_but_keeps_post_apply_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_fingerprinted_bundle(tmp_path / "bundle")
    inspector_calls = _patch_inspector(monkeypatch, [_TARGET_DATABASE])
    _install_successful_apply(monkeypatch)

    result = _invoke(bundle_dir, "--skip-source-check")

    assert result.exit_code == 0
    assert "Warning: Source schema check skipped by --skip-source-check." in result.stderr
    assert "Verified: database now matches the desired schema." in result.stdout
    assert inspector_calls == [(_DATABASE_URL, ["app"])]


def test_post_apply_mismatch_is_warning_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_fingerprinted_bundle(tmp_path / "bundle")
    inspector_calls = _patch_inspector(
        monkeypatch,
        [_SOURCE_DATABASE, Database(name="unexpected", server_version="18")],
    )
    _install_successful_apply(monkeypatch)

    result = _invoke(bundle_dir)

    assert result.exit_code == 0
    assert (
        "Warning: database does not match the desired schema after apply; run diff to inspect."
        in result.stderr
    )
    assert "Verified: database now matches the desired schema." not in result.stdout
    assert len(inspector_calls) == 2


def test_public_connectivity_check_executes_select_one_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    closed: list[bool] = []

    class FakeConnection:
        async def execute(self, statement: str) -> None:
            statements.append(statement)

        async def close(self) -> None:
            closed.append(True)

    async def connect(url: str) -> FakeConnection:
        assert url == _DATABASE_URL
        return FakeConnection()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)

    check_connectivity = getattr(apply_command, "check_connectivity", None)
    assert callable(check_connectivity)
    asyncio.run(check_connectivity(_DATABASE_URL))

    assert statements == ["SELECT 1"]
    assert closed == [True]


async def _record_connectivity(url: str, connected: list[str]) -> None:
    connected.append(url)


def test_dry_run_connectivity_failure_exits_one_without_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")

    async def failed_connectivity(_url: str) -> None:
        raise psycopg.OperationalError(f"driver detail {_SECRET_PASSWORD}")

    monkeypatch.setattr(apply_command, "check_connectivity", failed_connectivity)
    result = _invoke(bundle_dir, "--dry-run")

    assert result.exit_code == 1
    assert "Database connection failed." in result.stderr
    assert "driver detail" not in result.output
    _assert_password_redacted(result)


def test_success_prints_progress_events_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    events = (
        UnitStarted(0, 1, 1, ("d0001",), (1, 1), 0.0),
        StatementStarted(0, 0, 1, 1, "d0001", (1, 1), 0.0),
        StatementFinished(0, 0, 1, 1, "d0001", (1, 1), 0.1),
        UnitFinished(0, 1, 1, ("d0001",), (1, 1), 0.1),
    )
    _install_successful_apply(monkeypatch, events=events)

    result = _invoke(bundle_dir)

    assert result.exit_code == 0
    assert "unit 1/1 started" in result.stderr.lower()
    assert "statement 1/1" in result.stderr.lower()
    assert "d0001" in result.stderr
    assert "lines 1-1" in result.stderr.lower()
    assert "unit 1/1 finished" in result.stderr.lower()
    assert "applied" in result.stdout.lower()
    assert "1/1" in result.stdout
    assert "bundle-test-id" in result.stdout
    _assert_password_redacted(result)


def test_resumed_apply_prints_resumed_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    _install_successful_apply(monkeypatch, resumed=True)

    result = _invoke(bundle_dir)

    assert result.exit_code == 0
    assert "Resumed migration" in result.stdout
    assert "units-applied=1/1" in result.stdout
    assert "bundle-test-id" in result.stdout


@pytest.mark.parametrize(
    "error",
    [
        psycopg.OperationalError(f"driver detail {_SECRET_PASSWORD}"),
        psycopg_pool.PoolTimeout(f"pool detail {_SECRET_PASSWORD}"),
    ],
)
def test_database_errors_are_generic_and_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception | None,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")

    @asynccontextmanager
    async def failed_connection(
        _url: str,
        *,
        lock_timeout_ms: int,
        statement_timeout_ms: int,
    ) -> AsyncIterator[object]:
        _ = lock_timeout_ms, statement_timeout_ms
        if error is not None:
            raise error
        yield object()

    monkeypatch.setattr(apply_command, "open_executor", failed_connection)
    result = _invoke(bundle_dir)

    assert result.exit_code == 1
    assert "Database connection failed." in result.stderr
    assert "detail" not in result.output
    _assert_password_redacted(result)


@pytest.mark.parametrize("error", [RiskGateError("approval refused")])
def test_risk_gate_error_exits_two_without_driver_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: RiskGateError,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    _install_successful_apply(monkeypatch)

    async def rejected_apply(
        _bundle: ValidatedBundle,
        _executor: object,
        *,
        approve_destructive: bool,
        on_event: Callable[[object], None] | None,
    ) -> ApplyResult:
        _ = approve_destructive, on_event
        raise error

    monkeypatch.setattr(apply_command, "apply_migration", rejected_apply)
    result = _invoke(bundle_dir)

    assert result.exit_code == 2
    assert "approval refused" in result.stderr
    _assert_password_redacted(result)


def test_apply_error_without_failed_unit_prints_message_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    _install_successful_apply(monkeypatch)

    async def failed_apply(
        _bundle: ValidatedBundle,
        _executor: object,
        *,
        approve_destructive: bool,
        on_event: Callable[[object], None] | None,
    ) -> ApplyResult:
        _ = approve_destructive, on_event
        raise ApplyMigrationError("history metadata mismatch")

    monkeypatch.setattr(apply_command, "apply_migration", failed_apply)
    result = _invoke(bundle_dir)

    assert result.exit_code == 3
    assert "history metadata mismatch" in result.stderr
    assert "statement" not in result.stderr.lower()
    _assert_password_redacted(result)


@pytest.mark.parametrize("transactional", [True, False])
def test_apply_failure_prints_safe_metadata_and_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transactional: bool,
) -> None:
    bundle_dir = _write_bundle(bundle_dir=tmp_path / "bundle", transactional=transactional)
    _install_successful_apply(monkeypatch)
    failure = ApplyResult(
        bundle_id="bundle-test-id",
        status="failed",
        unit_count=1,
        applied_unit_count=0,
        resumed=False,
        elapsed=0.1,
        failed_unit_index=0,
        failed_statement_index=0,
        delta_id="d0001",
        line_range=(1, 1),
        error_class="SyntaxError",
        sqlstate="42601",
        manual_inspection_required=not transactional,
    )

    async def failed_apply(
        _bundle: ValidatedBundle,
        _executor: object,
        *,
        approve_destructive: bool,
        on_event: Callable[[object], None] | None,
    ) -> ApplyResult:
        _ = approve_destructive, on_event
        raise ApplyMigrationError("safe failure", result=failure)

    monkeypatch.setattr(apply_command, "apply_migration", failed_apply)
    result = _invoke(bundle_dir, "--yes")

    assert result.exit_code == 3
    assert "safe failure" in result.stderr
    assert "unit 1/1" in result.stderr.lower()
    assert "statement 1/1" in result.stderr.lower()
    assert "d0001" in result.stderr
    assert "lines 1-1" in result.stderr.lower()
    assert "SyntaxError" in result.stderr
    assert "42601" in result.stderr
    if transactional:
        assert "INVALID index" not in result.stderr
    else:
        assert "INVALID index" in result.stderr
        assert "manually inspect" in result.stderr.lower()
    _assert_password_redacted(result)


@pytest.mark.parametrize("exception", [asyncio.CancelledError(), KeyboardInterrupt()])
def test_cancellation_exits_three_with_partial_apply_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: BaseException,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    _install_successful_apply(monkeypatch)

    async def cancelled_apply(
        _bundle: ValidatedBundle,
        _executor: object,
        *,
        approve_destructive: bool,
        on_event: Callable[[object], None] | None,
    ) -> ApplyResult:
        _ = approve_destructive, on_event
        raise exception

    monkeypatch.setattr(apply_command, "apply_migration", cancelled_apply)
    result = _invoke(bundle_dir)

    assert result.exit_code == 3
    assert "Apply cancelled; earlier units remain applied." in result.stderr
    _assert_password_redacted(result)


def test_unexpected_exception_exits_three_without_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle")
    _install_successful_apply(monkeypatch)

    async def unexpected_apply(
        _bundle: ValidatedBundle,
        _executor: object,
        *,
        approve_destructive: bool,
        on_event: Callable[[object], None] | None,
    ) -> ApplyResult:
        _ = approve_destructive, on_event
        raise RuntimeError(f"private driver detail {_SECRET_PASSWORD}")

    monkeypatch.setattr(apply_command, "apply_migration", unexpected_apply)
    result = _invoke(bundle_dir)

    assert result.exit_code == 3
    assert "Migration apply failed." in result.stderr
    assert "private driver detail" not in result.output
    _assert_password_redacted(result)


@pytest.mark.parametrize("sqlstate", ["42601", None])
def test_failed_event_prints_class_and_sqlstate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sqlstate: str | None,
) -> None:
    bundle_dir = _write_bundle(tmp_path / "bundle", transactional=False)
    failed_event = UnitFailed(0, 1, 0, 1, "d0001", (1, 1), "SyntaxError", sqlstate, True, 0.1)
    _install_successful_apply(monkeypatch, events=(failed_event,))

    result = _invoke(bundle_dir, "--yes")

    assert result.exit_code == 0
    assert "SyntaxError" in result.stderr
    assert f"SQLSTATE={'42601' if sqlstate is not None else 'unknown'}" in result.stderr
    _assert_password_redacted(result)


def test_failed_event_uses_red_for_terminal_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = getattr(apply_command, "output", None)
    assert output is not None
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system="standard",
        markup=False,
        highlight=False,
        emoji=False,
        soft_wrap=True,
    )
    monkeypatch.setattr(output, "stderr_console", lambda: console)

    apply_command._print_event(
        UnitFailed(0, 1, 0, 1, "d0001", (1, 1), "SyntaxError", "42601", True, 0.1)
    )

    assert "failed" in stream.getvalue()
    assert "\x1b[" in stream.getvalue()
