"""Smoke + interaction tests for the Textual TUI shell (task P4-TUI-01)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from psycopg import OperationalError
from rich.text import Text
from textual.content import Content
from textual.widgets import Button, ContentSwitcher, DataTable, Input, Select, Static
from typer.testing import CliRunner

import pgschemadiff.presentation.tui.app as tui_app_module
from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
from pgschemadiff.application.migration.apply import apply_migration
from pgschemadiff.application.migration.generate import assess_deltas, generate_migration
from pgschemadiff.application.migration.history import (
    MigrationHistoryRun,
    MigrationHistoryUnavailableError,
    MigrationHistoryUnit,
)
from pgschemadiff.application.migration.ports import UnitFailure
from pgschemadiff.application.migration.render import RenderedBundle, render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import CreateSchema, DeltaBase, DeltaSet, DropSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.models import ConnectionInfo, Profile
from pgschemadiff.domain.schema import Schema
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.infrastructure.postgres.history import PostgresMigrationHistoryReader
from pgschemadiff.presentation.cli.main import app as cli_app
from pgschemadiff.presentation.composition import TuiDependencies, create_tui_dependencies
from pgschemadiff.presentation.tui import PgsdApp
from pgschemadiff.presentation.tui._mock import DIFFS
from pgschemadiff.presentation.tui.app import _VIEW_CHORDS
from pgschemadiff.presentation.tui.screens.help import HelpScreen
from pgschemadiff.presentation.tui.screens.main import MainScreen
from pgschemadiff.presentation.tui.views import DiffView, MigrationView
from pgschemadiff.presentation.tui.views._common import (
    AiRequested,
    ApplyRequested,
    DiffRequested,
    sql_content,
    sql_markup,
)
from pgschemadiff.presentation.tui.views.connection import ProfileSelected
from pgschemadiff.presentation.tui.views.history import HistoryView
from pgschemadiff.presentation.tui.widgets import Cmdbar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from textual.pilot import Pilot

    from pgschemadiff.application.migration.apply import ApplyEvent, ApplyResult
    from pgschemadiff.application.migration.bundle import BundleUnit, ValidatedBundle
    from pgschemadiff.application.migration.model import MigrationPlan
    from pgschemadiff.application.migration.ports import (
        BundleReader,
        MigrationExecutor,
        MigrationHistoryReader,
        MigrationWriter,
        RunFailure,
        RunFinishStatus,
        StatementObserver,
    )
    from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader
    from pgschemadiff.presentation.composition import (
        CompareCallable,
        ExecutorFactory,
        InspectorScope,
    )


_EXPECTED_PALETTE_COMMANDS = (
    ":o/:overview",
    ":d/:diff [qualified-name]",
    ":m/:migration",
    ":a/:apply [--dry-run]",
    ":h/:history",
    ":c/:conn/:connection",
    ":conn switch <profile>",
    ":rollback <id>",
    ":set bg=mocha|latte",
    ":s/:settings",
    ":help/?",
    ":q/:quit",
)


async def _submit_palette(app: PgsdApp, pilot: Pilot[None], command: str) -> None:
    await pilot.press("colon")
    await pilot.pause()
    app.query_one("#cmd-input", Input).value = command.removeprefix(":")
    await pilot.press("enter")
    await pilot.pause()


class _FakeProfileLoader:
    def __init__(self, path: Path, profiles: list[Profile]) -> None:
        self.config_path = path
        self.profiles = profiles

    def load(self) -> list[Profile]:
        return self.profiles


class _RecordingMigrationWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[MigrationPlan, Path]] = []
        self.thread_id: int | None = None
        self.delegate = FilesystemMigrationWriter()

    def write(self, plan: MigrationPlan, output_dir: Path) -> Path:
        self.calls.append((plan, output_dir))
        self.thread_id = threading.get_ident()
        return self.delegate.write(plan, output_dir)


class _FakeBundleReader:
    def __init__(self, files: tuple[bytes, bytes], error: Exception | None = None) -> None:
        self.files = files
        self.error = error
        self.paths: list[Path] = []
        self.thread_id: int | None = None

    def read(self, bundle_dir: Path) -> tuple[bytes, bytes]:
        self.paths.append(bundle_dir)
        self.thread_id = threading.get_ident()
        if self.error is not None:
            raise self.error
        return self.files


class _BlockingBundleReader(_FakeBundleReader):
    def __init__(self, files: tuple[bytes, bytes]) -> None:
        super().__init__(files)
        self.started = threading.Event()
        self.release = threading.Event()

    def read(self, bundle_dir: Path) -> tuple[bytes, bytes]:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError
        return super().read(bundle_dir)


class _FakeMigrationExecutor:
    def __init__(
        self,
        *,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
        failure: UnitFailure | None = None,
    ) -> None:
        self.started = started
        self.release = release
        self.failure = failure
        self.calls: list[tuple[str, object]] = []

    async def load_history(self, bundle_id: str) -> None:
        self.calls.append(("load_history", bundle_id))

    async def start_run(self, bundle: ValidatedBundle, *, resume: bool) -> None:
        self.calls.append(("start_run", resume))

    async def apply_unit(
        self,
        bundle_id: str,
        unit: BundleUnit,
        on_statement: StatementObserver,
    ) -> UnitFailure | None:
        self.calls.append(("apply_unit", unit.index))
        for statement_index in range(len(unit.statements)):
            on_statement(statement_index, True)
            if self.started is not None:
                self.started.set()
            if self.release is not None:
                await self.release.wait()
            if self.failure is not None:
                return self.failure
            on_statement(statement_index, False)
        return None

    async def finish_run(
        self,
        bundle_id: str,
        status: RunFinishStatus,
        failure: RunFailure | None,
    ) -> None:
        self.calls.append(("finish_run", status))


class _RecordingExecutorFactory:
    def __init__(
        self,
        executor: _FakeMigrationExecutor,
        error: Exception | None = None,
    ) -> None:
        self.executor = executor
        self.error = error
        self.calls: list[tuple[str, int, int]] = []

    def __call__(
        self,
        conninfo: str,
        *,
        lock_timeout_ms: int = 5_000,
        statement_timeout_ms: int = 0,
    ) -> object:
        self.calls.append((conninfo, lock_timeout_ms, statement_timeout_ms))
        return self._scope()

    @asynccontextmanager
    async def _scope(self) -> AsyncIterator[MigrationExecutor]:
        if self.error is not None:
            raise self.error
        yield cast("MigrationExecutor", self.executor)


class _RecordingHistoryReader:
    def __init__(
        self,
        runs: tuple[MigrationHistoryRun, ...] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self.runs = runs
        self.error = error
        self.calls = 0
        self.limits: list[int] = []

    async def list_history(self, *, limit: int = 50) -> tuple[MigrationHistoryRun, ...]:
        self.calls += 1
        self.limits.append(limit)
        if self.error is not None:
            raise self.error
        return self.runs


class _RecordingHistoryReaderFactory:
    def __init__(self, reader: _RecordingHistoryReader) -> None:
        self.reader = reader
        self.conninfos: list[str] = []

    def __call__(self, conninfo: str) -> MigrationHistoryReader:
        self.conninfos.append(conninfo)
        return self.reader


def _history_read_count(reader: _RecordingHistoryReader) -> int:
    return reader.calls


def _migration_dependencies(
    tmp_path: Path,
    writer: _RecordingMigrationWriter,
    *,
    profiles: list[Profile] | None = None,
    compare: object | None = None,
    bundle_reader: object | None = None,
    executor_factory: object | None = None,
) -> TuiDependencies:
    loader = _FakeProfileLoader(tmp_path / "profiles.yaml", profiles or [])
    return TuiDependencies(
        profile_loader=cast("ProfileLoader", loader),
        inspector_scope=cast("InspectorScope", Mock()),
        migration_writer=cast("MigrationWriter", writer),
        bundle_reader=cast("BundleReader", bundle_reader or Mock()),
        executor_factory=cast("ExecutorFactory", executor_factory or Mock()),
        compare=cast("CompareCallable", compare) if compare is not None else _no_compare,
    )


def _history_dependencies(
    tmp_path: Path,
    profile: Profile,
    history_reader_factory: _RecordingHistoryReaderFactory,
    *,
    profiles: list[Profile] | None = None,
    bundle_reader: object | None = None,
    executor_factory: object | None = None,
) -> TuiDependencies:
    loader = _FakeProfileLoader(tmp_path / "profiles.yaml", profiles or [profile])
    return TuiDependencies(
        profile_loader=cast("ProfileLoader", loader),
        inspector_scope=cast("InspectorScope", Mock()),
        migration_writer=cast("MigrationWriter", _RecordingMigrationWriter()),
        bundle_reader=cast("BundleReader", bundle_reader or Mock()),
        executor_factory=cast("ExecutorFactory", executor_factory or Mock()),
        history_reader_factory=history_reader_factory,
    )


def _history_runs() -> tuple[MigrationHistoryRun, ...]:
    started = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    finished = started + timedelta(seconds=90)
    return (
        MigrationHistoryRun(
            bundle_id="bundle-running",
            status="running",
            started_at=started + timedelta(days=1),
            finished_at=None,
            up_sql_sha256="fedcba0987654321" * 4,
            units=(
                MigrationHistoryUnit(
                    index=0,
                    status="running",
                    transactional=False,
                    started_at=None,
                    finished_at=None,
                    failed_statement_index=None,
                    error_class=None,
                    sqlstate=None,
                ),
            ),
        ),
        MigrationHistoryRun(
            bundle_id="bundle-new",
            status="applied",
            started_at=started,
            finished_at=finished,
            up_sql_sha256="abcdef0123456789" * 4,
            units=(
                MigrationHistoryUnit(
                    index=0,
                    status="applied",
                    transactional=True,
                    started_at=started,
                    finished_at=finished,
                    failed_statement_index=None,
                    error_class=None,
                    sqlstate=None,
                ),
            ),
        ),
        MigrationHistoryRun(
            bundle_id="bundle-old",
            status="failed",
            started_at=started - timedelta(days=1),
            finished_at=started - timedelta(days=1) + timedelta(seconds=20),
            up_sql_sha256="1234567890abcdef" * 4,
            units=(
                MigrationHistoryUnit(
                    index=3,
                    status="failed",
                    transactional=False,
                    started_at=started - timedelta(days=1),
                    finished_at=started - timedelta(days=1) + timedelta(seconds=20),
                    failed_statement_index=2,
                    error_class="UndefinedTable",
                    sqlstate="42P01",
                ),
            ),
        ),
        MigrationHistoryRun(
            bundle_id="bundle-cancelled",
            status="cancelled",
            started_at=started - timedelta(days=2),
            finished_at=started - timedelta(days=2) + timedelta(seconds=5),
            up_sql_sha256="fedcba0987654321" * 4,
            units=(),
        ),
    )


async def _no_compare(
    _source: str, _target: str, _schemas: list[str] | None
) -> SchemaComparisonResult:
    return _comparison()


def _schema_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )


def _create_schema_delta(*, comment: str | None = None) -> CreateSchema:
    ref = _schema_ref()
    return CreateSchema(target=ref, pg_schema=Schema(ref=ref, comment=comment))


def _drop_schema_delta() -> DropSchema:
    ref = _schema_ref()
    return DropSchema(target=ref, pg_schema=Schema(ref=ref))


def _comparison(*deltas: DeltaBase) -> SchemaComparisonResult:
    return SchemaComparisonResult(
        source=Database(name="source"),
        target=Database(name="target"),
        deltas=DeltaSet.from_iterable(deltas),
    )


def _profile(name: str) -> Profile:
    return Profile(
        name=name,
        source=ConnectionInfo(
            host="localhost",
            port=5432,
            database=f"{name}_source",
            user="reader",
            password="secret",
        ),
        target=ConnectionInfo(
            host="localhost",
            port=5432,
            database=f"{name}_target",
            user="writer",
            password="secret",
        ),
    )


def _bundle_files(
    delta: DeltaBase,
    *,
    max_risk: RiskLevel = RiskLevel.DANGEROUS,
    force_risk: RiskLevel | None = None,
) -> tuple[bytes, bytes]:
    plan = generate_migration(DeltaSet.from_iterable([delta]), max_risk=max_risk)
    files = dict(render_bundle(plan).files)
    manifest = json.loads(files["manifest.json"])
    if force_risk is not None:
        manifest["overall_max_risk"] = force_risk.value
        for assessment in manifest["assessments"]:
            assessment["level"] = force_risk.value
        for unit in manifest["units"]:
            unit["max_risk"] = force_risk.value
    return json.dumps(manifest).encode(), files["up.sql"]


def _plain(widget: Static) -> str:
    rendered = widget.render()
    return rendered.plain if isinstance(rendered, (Text, Content)) else str(rendered)


def _install_comparison(app: PgsdApp, *deltas: DeltaBase) -> None:
    app.session.last_comparison = _comparison(*deltas)
    app.query_one("#migration", MigrationView).update_from_session(app.session)
    app.switch_view("migration")


@pytest.mark.unit
def test_tui_app_constructs() -> None:
    app = PgsdApp()
    assert app.TITLE == "pgschemadiff"


@pytest.mark.unit
async def test_tui_mounts_main_screen() -> None:
    app = PgsdApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)
        assert app.theme == "catppuccin-mocha"


@pytest.mark.unit
async def test_tui_accepts_fake_dependencies_without_database_io() -> None:
    profile_loader = Mock()
    profile_loader.load.return_value = []
    inspector_scope = Mock()
    migration_writer = Mock()
    bundle_reader = Mock()
    executor_factory = Mock()
    dependencies = TuiDependencies(
        profile_loader=cast("ProfileLoader", profile_loader),
        inspector_scope=cast("InspectorScope", inspector_scope),
        migration_writer=cast("MigrationWriter", migration_writer),
        bundle_reader=cast("BundleReader", bundle_reader),
        executor_factory=cast("ExecutorFactory", executor_factory),
    )
    app = PgsdApp(dependencies=dependencies)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.dependencies is dependencies

    profile_loader.load.assert_called_once_with()
    inspector_scope.assert_not_called()
    migration_writer.assert_not_called()
    bundle_reader.assert_not_called()
    executor_factory.assert_not_called()


@pytest.mark.unit
async def test_tui_chord_switches_view() -> None:
    app = PgsdApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("g", "d")
        await pilot.pause()
        assert _VIEW_CHORDS["d"] == "diff"
        assert app._active_view == "diff"


@pytest.mark.unit
async def test_tui_theme_toggle_chord() -> None:
    app = PgsdApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.theme == "catppuccin-mocha"
        await pilot.press("g", "T")
        await pilot.pause()
        assert app.theme == "catppuccin-latte"
        await pilot.press("g", "T")
        await pilot.pause()
        assert app.theme == "catppuccin-mocha"


@pytest.mark.unit
async def test_tui_command_palette_opens_and_dispatches() -> None:
    app = PgsdApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("colon")
        await pilot.pause()
        assert app._mode == "command"
        cmd_input = app.query_one("#cmd-input", Input)
        cmd_input.value = "diff"
        await pilot.press("enter")
        await pilot.pause()
        assert app._active_view == "diff"
        assert app._mode == "normal"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("command", "view_id"),
    [
        (":o", "overview"),
        (":overview", "overview"),
        (":d", "diff"),
        (":diff", "diff"),
        (":m", "migration"),
        (":migration", "migration"),
        (":a", "apply"),
        (":apply", "apply"),
        (":h", "history"),
        (":history", "history"),
        (":c", "connection"),
        (":conn", "connection"),
        (":connection", "connection"),
        (":s", "settings"),
        (":settings", "settings"),
    ],
)
async def test_palette_view_commands_route_through_pilot(command: str, view_id: str) -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, command)

        assert app._active_view == view_id
        assert app.query_one("#content", ContentSwitcher).current == view_id


@pytest.mark.unit
@pytest.mark.parametrize(
    ("command", "theme"),
    [
        (":set bg=latte", "catppuccin-latte"),
        (":set bg=mocha", "catppuccin-mocha"),
    ],
)
async def test_palette_sets_only_supported_background_themes(command: str, theme: str) -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, command)

        assert app.theme == theme


@pytest.mark.unit
@pytest.mark.parametrize("command", [":help", ":?"])
async def test_palette_help_aliases_open_help(command: str) -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, command)

        assert isinstance(app.screen, HelpScreen)


@pytest.mark.unit
@pytest.mark.parametrize("command", [":q", ":quit"])
async def test_palette_quit_aliases_exit(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    app = PgsdApp()
    exits: list[bool] = []
    monkeypatch.setattr(app, "exit", lambda: exits.append(True))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, command)

    assert exits == [True]


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        ":unknown password-sentinel",
        ":config password-sentinel",
        ":zz password-sentinel",
        ":set theme=latte password-sentinel",
        ":apply --yes password-sentinel",
        ":overview password-sentinel",
        ":connection switch password-sentinel",
        ":rollback",
        ":help password-sentinel",
    ],
)
async def test_unknown_palette_command_is_redacted(command: str) -> None:
    app = PgsdApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, command)

        assert app.query_one(Cmdbar).hint == "not an editor command"
        assert "password-sentinel" not in app.query_one(Cmdbar).hint


@pytest.mark.unit
async def test_palette_diff_selects_matching_qualified_name_or_reports_not_found() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        delta = _create_schema_delta()
        app.session.last_comparison = _comparison(delta)
        cast("MainScreen", app.screen).update_from_session(app.session)

        await _submit_palette(app, pilot, f":d {delta.target.qname.fqn}")

        assert app._active_view == "diff"
        assert app.query_one("#diff", DiffView).delta_id == "d0001"
        await _submit_palette(app, pilot, ":diff missing-name-sentinel")
        assert app.query_one(Cmdbar).hint == "not found"
        assert "missing-name-sentinel" not in app.query_one(Cmdbar).hint


@pytest.mark.unit
async def test_palette_named_diff_rejects_ambiguous_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = PgsdApp()
    delta = _create_schema_delta()
    comparison = _comparison(delta)
    app.session.last_comparison = comparison
    assessment = assess_deltas(comparison.deltas)[0][1]
    monkeypatch.setattr(
        tui_app_module,
        "assess_deltas",
        Mock(return_value=(("d0001", assessment), ("d0002", assessment))),
    )

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, f":diff {delta.target.qname.fqn}")

        assert app._active_view == "overview"
        assert app.query_one(Cmdbar).hint == "multiple objects match; select from Overview"


@pytest.mark.unit
async def test_palette_named_diff_without_comparison_reports_not_found() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, ":diff public.users")

        assert app.query_one(Cmdbar).hint == "not found"


@pytest.mark.unit
async def test_palette_connection_switch_selects_profile_by_name() -> None:
    app = PgsdApp()
    first, second = _profile("first"), _profile("second")
    app.session.set_profiles([first, second])
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, ":conn switch second")

        assert app.session.selected_profile == second
        assert app._active_view == "connection"

        await _submit_palette(app, pilot, ":conn switch missing-profile-sentinel")
        assert app.query_one(Cmdbar).hint == "profile not found"
        assert "missing-profile-sentinel" not in app.query_one(Cmdbar).hint


@pytest.mark.unit
async def test_palette_connection_switch_rejects_ambiguous_profile_name() -> None:
    first = _profile("shared")
    second = Profile(name=first.name, source=first.target, target=first.source)
    app = PgsdApp()
    app.session.set_profiles([first, second])

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, ":conn switch shared")

        assert app.session.selected_profile == first
        assert app._active_view == "overview"
        assert app.query_one(Cmdbar).hint == "ambiguous profile name"


@pytest.mark.unit
async def test_palette_rollback_selects_run_and_says_unavailable() -> None:
    app = PgsdApp()
    app.session.select_profile(_profile("pilot"))
    app.session.history_runs = _history_runs()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, ":rollback bundle-new")

        assert app._active_view == "history"
        assert app.session.selected_history_bundle_id == "bundle-new"
        assert app.query_one(Cmdbar).hint == "Rollback is not available; down.sql is notes only."


@pytest.mark.unit
async def test_palette_lists_exact_supported_commands_in_help_and_cmdbar() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await _submit_palette(app, pilot, ":help")

        help_text = "\n".join(_plain(widget) for widget in app.screen.query(Static))
        assert Cmdbar.HINTS == _EXPECTED_PALETTE_COMMANDS
        for command in _EXPECTED_PALETTE_COMMANDS:
            assert help_text.count(command) == 1
        banned = ("AI", "accept", "skip", "pause", "continue", "executable rollback")
        assert not any(
            re.search(rf"\b{re.escape(word)}\b", help_text, re.IGNORECASE) for word in banned
        )


@pytest.mark.unit
async def test_tui_help_modal_opens_and_closes() -> None:
    app = PgsdApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)


@pytest.mark.unit
def test_cli_tui_subcommand_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, ["tui", "--help"])
    assert result.exit_code == 0
    assert "tui" in result.stdout.lower() or "interactive" in result.stdout.lower()


@pytest.mark.unit
@pytest.mark.parametrize("args", [[], ["tui"]])
def test_cli_entrypoints_launch_composed_tui(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    launched: list[PgsdApp] = []

    def fake_run(app: PgsdApp) -> None:
        launched.append(app)

    monkeypatch.setattr(PgsdApp, "run", fake_run)

    result = CliRunner().invoke(cli_app, args)

    assert result.exit_code == 0
    assert len(launched) == 1
    assert isinstance(launched[0].dependencies, TuiDependencies)


# --------------------------------------------------------------------------- #
# Views (P4-TUI-02 … P4-TUI-08)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_sql_content_preserves_backslashes_and_brackets_as_literal_text() -> None:
    sql = r"-- C:\[x] CREATE TYPE public.plan_tier_enum"
    rendered = sql_content(sql)

    assert isinstance(rendered, Content)
    assert rendered.plain == sql
    assert rendered.spans


@pytest.mark.unit
def test_sql_markup_remains_compatible_with_markup_string_callers() -> None:
    sql = r"-- C:\[x] CREATE TYPE public.plan_tier_enum"

    assert Content.from_markup(sql_markup(sql)).plain == sql


@pytest.mark.unit
@pytest.mark.parametrize("chord", list(_VIEW_CHORDS))
async def test_every_view_reachable_by_chord(chord: str) -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await pilot.press("g", chord)
        await pilot.pause()
        view_id = _VIEW_CHORDS[chord]
        assert app._active_view == view_id
        assert app.query_one("#content", ContentSwitcher).current == view_id


@pytest.mark.unit
async def test_diff_requested_switches_and_selects_object() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.screen.post_message(DiffRequested("d0001"))
        await pilot.pause()
        assert app._active_view == "diff"
        assert app.query_one("#diff", DiffView).delta_id == "d0001"


@pytest.mark.unit
async def test_diff_mode_toggle_recomposes() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        diff = app.query_one("#diff", DiffView)
        for mode in ("inline", "tree", "side"):
            diff.mode = mode
            await pilot.pause()
            assert diff.mode == mode


@pytest.mark.unit
async def test_settings_shows_live_values_and_redacts_profile_secrets(tmp_path: Path) -> None:
    secret = "settings-password-sentinel"
    profile = Profile(
        name="production",
        source=ConnectionInfo(
            host="source.example",
            port=5433,
            database="source_db",
            user="source_user",
            password=secret,
        ),
        target=ConnectionInfo(
            host="target.example",
            port=6432,
            database="target_db",
            user="target_user",
            password=secret,
        ),
        schemas=["sales", "audit"],
        mode="schema-only",
        ignore_patterns=["private.*", "scratch.*"],
    )
    dependencies = _migration_dependencies(
        tmp_path,
        _RecordingMigrationWriter(),
        profiles=[profile],
    )
    app = PgsdApp(dependencies=dependencies)

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.query_one("#diff", DiffView).mode = "tree"
        app.switch_view("settings")
        await pilot.pause()

        text = "\n".join(_plain(widget) for widget in app.query_one("#settings").query(Static))
        assert "catppuccin-mocha" in text
        assert "tree" in text
        assert "5000 ms" in text
        assert "0 ms (unlimited)" in text
        assert str(tmp_path / "profiles.yaml") in text
        for value in (
            "production",
            "source.example",
            "5433",
            "source_db",
            "source_user",
            "target.example",
            "6432",
            "target_db",
            "target_user",
            "sales",
            "audit",
            "schema-only",
            "2",
            "unsupported",
        ):
            assert value in text
        assert secret not in text
        assert "postgresql://" not in text
        assert "private.*" not in text
        assert "scratch.*" not in text
        assert "config.toml" not in text

        app.toggle_theme()
        await pilot.pause()
        text = "\n".join(_plain(widget) for widget in app.query_one("#settings").query(Static))
        assert "catppuccin-latte" in text

        app.session.select_profile(_profile("clean"))
        app.switch_view("settings")
        text = "\n".join(_plain(widget) for widget in app.query_one("#settings").query(Static))
        assert "Ignore patterns: none (0)" in text


@pytest.mark.unit
async def test_settings_without_profile_shows_unconfigured_state() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.switch_view("settings")
        text = "\n".join(_plain(widget) for widget in app.query_one("#settings").query(Static))

        assert "Profile path: not configured" in text
        assert "No profile selected." in text


@pytest.mark.unit
async def test_ai_requested_does_not_open_modal() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.screen.post_message(AiRequested("public.users"))
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)


@pytest.mark.unit
async def test_apply_requested_switches_view() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.screen.post_message(ApplyRequested())
        await pilot.pause()
        assert app._active_view == "apply"


@pytest.mark.unit
async def test_apply_loads_saved_bundle_off_ui_loop_and_shows_safe_summary(
    tmp_path: Path,
) -> None:
    files = _bundle_files(_create_schema_delta())
    reader = _FakeBundleReader(files)
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor())
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )
    caller_thread = threading.get_ident()
    bundle_path = tmp_path / "saved-bundle"

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = bundle_path
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()

        text = "\n".join(_plain(widget) for widget in app.query_one("#apply").query(Static))
        assert reader.paths == [bundle_path]
        assert reader.thread_id != caller_thread
        assert "pilot" in text
        assert "pilot_target" in text
        assert str(bundle_path) in text
        assert "1 delta" in text
        assert "1 unit" in text
        assert "safe" in text
        assert "secret" not in text
        assert app.query_one("#apply-lock-timeout", Input).value == "5000ms"
        assert app.query_one("#apply-statement-timeout", Input).value == "0"


@pytest.mark.unit
@pytest.mark.parametrize("command", [":a --dry-run", ":apply --dry-run"])
async def test_palette_apply_dry_run_starts_connectivity_check_without_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    profile = _profile("pilot")
    reader = _BlockingBundleReader(_bundle_files(_create_schema_delta()))
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor())
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[profile],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )
    connected: list[str] = []

    async def check_connectivity(conninfo: str) -> None:
        connected.append(conninfo)

    monkeypatch.setattr(tui_app_module, "_check_connectivity", check_connectivity)

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await pilot.pause()
        assert reader.started.wait(timeout=5)

        await _submit_palette(app, pilot, command)
        reader.release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert connected == [profile.target.dsn()]
        assert executor_factory.calls == []
        assert app.session.apply_status == (
            "Dry-run connectivity check passed; no migration SQL or history was touched."
        )

        app.session.apply_operation = "dry-run"
        await _submit_palette(app, pilot, ":a --dry-run")
        assert connected == [profile.target.dsn()]
        assert app.session.apply_operation == "dry-run"


@pytest.mark.unit
async def test_apply_always_opens_confirmation_and_cancel_does_not_open_executor(
    tmp_path: Path,
) -> None:
    reader = _FakeBundleReader(_bundle_files(_create_schema_delta()))
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor())
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await _submit_palette(app, pilot, ":apply")
        assert isinstance(app.screen, MainScreen)
        assert executor_factory.calls == []

        await pilot.click("#apply-start")
        await pilot.pause()

        assert app.screen.__class__.__name__ == "ConfirmApplyModal"
        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, MainScreen)
        assert executor_factory.calls == []
        assert app.session.apply_events == []


@pytest.mark.unit
async def test_destructive_apply_requires_explicit_modal_action_and_passes_approval(
    tmp_path: Path,
) -> None:
    reader = _FakeBundleReader(_bundle_files(_drop_schema_delta(), max_risk=RiskLevel.DESTRUCTIVE))
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor())
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#apply-start")
        await pilot.pause()

        assert app.screen.__class__.__name__ == "ConfirmApplyModal"
        modal_text = "\n".join(_plain(widget) for widget in app.screen.query(Static))
        assert "pilot_target" in modal_text
        assert "unit index 0" in modal_text
        assert "d0001" in modal_text
        assert "Removes a schema and its objects." in modal_text
        assert len(app.screen.query("#confirm-apply")) == 0
        assert len(app.screen.query("#confirm-destructive")) == 1

        await pilot.click("#confirm-destructive")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert len(executor_factory.calls) == 1
        assert executor_factory.calls[0][1:] == (5_000, 0)
        assert app.session.apply_result is not None
        assert app.session.apply_result.status == "applied"


@pytest.mark.unit
async def test_blocked_bundle_has_no_proceed_action_and_app_guard_skips_executor(
    tmp_path: Path,
) -> None:
    files = _bundle_files(
        _drop_schema_delta(),
        max_risk=RiskLevel.DESTRUCTIVE,
        force_risk=RiskLevel.BLOCKED,
    )
    reader = _FakeBundleReader(files)
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor())
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "blocked-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#apply-start")
        await pilot.pause()

        assert app.screen.__class__.__name__ == "ConfirmApplyModal"
        assert len(app.screen.query("#confirm-apply")) == 0
        assert len(app.screen.query("#confirm-destructive")) == 0
        app._on_apply_confirmation(True)
        await pilot.pause()

        assert executor_factory.calls == []
        assert "BLOCKED" in app.session.apply_status


@pytest.mark.unit
async def test_low_risk_apply_passes_false_approval_and_renders_ordered_real_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeBundleReader(_bundle_files(_create_schema_delta()))
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor())
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )
    approval_values: list[bool] = []
    original_apply = apply_migration

    async def record_approval(
        bundle: ValidatedBundle,
        executor: MigrationExecutor,
        *,
        approve_destructive: bool,
        on_event: Callable[[ApplyEvent], None] | None = None,
    ) -> ApplyResult:
        approval_values.append(approve_destructive)
        return await original_apply(
            bundle,
            executor,
            approve_destructive=approve_destructive,
            on_event=on_event,
        )

    monkeypatch.setattr(tui_app_module, "apply_migration", record_approval)

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#apply-start")
        await pilot.pause()

        assert app.screen.__class__.__name__ == "ConfirmApplyModal"
        assert len(app.screen.query("#confirm-apply")) == 1
        await pilot.click("#confirm-apply")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert approval_values == [False]
        event_names = [type(event).__name__ for event in app.session.apply_events]
        expected = ["RunStarted", "UnitStarted"]
        bundle = app.session.validated_bundle
        assert bundle is not None
        for _ in range(len(bundle.units[0].statements)):
            expected.extend(["StatementStarted", "StatementFinished"])
        expected.extend(["UnitFinished", "RunFinished"])
        assert event_names == expected
        log_text = _plain(app.query_one("#apply-log", Static))
        assert "StatementStarted" in log_text
        assert "unit=1/1" in log_text
        assert "delta=d0001" in log_text
        assert "CREATE SCHEMA" not in log_text
        assert app.session.apply_result is not None
        assert app.session.apply_result.applied_unit_count == 1


@pytest.mark.unit
async def test_apply_failure_renders_only_safe_result_metadata(tmp_path: Path) -> None:
    executor = _FakeMigrationExecutor(
        failure=UnitFailure(statement_index=0, error_class="UndefinedTable", sqlstate="42P01")
    )
    reader = _FakeBundleReader(_bundle_files(_create_schema_delta()))
    executor_factory = _RecordingExecutorFactory(executor)
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#apply-start")
        await pilot.pause()
        await pilot.click("#confirm-apply")
        await app.workers.wait_for_complete()
        await pilot.pause()

        result = app.session.apply_result
        assert result is not None
        assert result.status == "failed"
        assert result.failed_unit_index == 0
        assert result.failed_statement_index == 0
        assert result.delta_id == "d0001"
        assert result.error_class == "UndefinedTable"
        assert result.sqlstate == "42P01"
        result_text = _plain(app.query_one("#apply-result", Static))
        assert "status=failed" in result_text
        assert "error=UndefinedTable" in result_text
        assert "SQLSTATE=42P01" in result_text
        assert app.session.apply_status == "Migration apply failed."


@pytest.mark.unit
async def test_apply_cancel_disables_actions_and_reports_partial_apply_semantics(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    executor = _FakeMigrationExecutor(started=started, release=release)
    reader = _FakeBundleReader(_bundle_files(_create_schema_delta()))
    executor_factory = _RecordingExecutorFactory(executor)
    profiles = [_profile("first"), _profile("second")]
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=profiles,
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#apply-start")
        await pilot.pause()
        await pilot.click("#confirm-apply")
        await started.wait()
        await pilot.pause()

        assert app.query_one("#saved-profiles", DataTable).disabled
        assert app.query_one("#btn-test-both", Button).disabled
        assert app.query_one("#mig-generate", Button).disabled
        assert app.query_one("#mig-save", Button).disabled
        assert app.query_one("#apply-start", Button).disabled
        app.on_profile_selected(ProfileSelected(1))
        assert app.session.selected_profile == profiles[0]

        await pilot.click("#apply-cancel")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert executor.calls[-1] == ("finish_run", "cancelled")
        assert app.session.apply_status == (
            "Cancelled — earlier units remain applied; an in-flight non-transactional "
            "statement may be indeterminate."
        )
        apply_text = "\n".join(_plain(widget) for widget in app.query_one("#apply").query(Static))
        assert "rollback" not in apply_text.lower()


@pytest.mark.unit
async def test_dry_run_uses_connectivity_only_and_never_opens_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeBundleReader(_bundle_files(_drop_schema_delta(), max_risk=RiskLevel.DESTRUCTIVE))
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor())
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )
    checked: list[str] = []

    async def check_connectivity(conninfo: str) -> None:
        checked.append(conninfo)

    monkeypatch.setattr(tui_app_module, "_check_connectivity", check_connectivity)

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "destructive" in _plain(app.query_one("#apply-warning", Static)).lower()

        await pilot.click("#apply-dry-run")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert len(checked) == 1
        checked_target = checked[0].rsplit("/", maxsplit=1)[-1] if checked else ""
        assert checked_target == "pilot_target"
        assert executor_factory.calls == []
        assert app.session.apply_status == (
            "Dry-run connectivity check passed; no migration SQL or history was touched."
        )


@pytest.mark.unit
async def test_apply_timeout_validation_reuses_cli_limits(tmp_path: Path) -> None:
    reader = _FakeBundleReader(_bundle_files(_create_schema_delta()))
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor())
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.query_one("#apply-lock-timeout", Input).value = "86400001ms"
        await pilot.click("#apply-start")
        await pilot.pause()

        assert app.screen.__class__.__name__ == "MainScreen"
        assert "must not exceed 24 hours" in app.session.apply_status
        assert executor_factory.calls == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (
            OperationalError("password-sentinel@exception-host-sentinel"),
            "Database connection failed.",
        ),
        (RuntimeError("password-sentinel@exception-host-sentinel"), "Migration apply failed."),
    ],
    ids=["driver-error", "unexpected-error"],
)
async def test_apply_failure_redacts_driver_message_from_view_and_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    exception: Exception,
    expected_status: str,
) -> None:
    reader = _FakeBundleReader(_bundle_files(_create_schema_delta()))
    executor_factory = _RecordingExecutorFactory(_FakeMigrationExecutor(), error=exception)
    profile = _profile("pilot")
    profile = Profile(
        name=profile.name,
        source=profile.source,
        target=ConnectionInfo(
            host="profile-host",
            port=profile.target.port,
            database=profile.target.database,
            user=profile.target.user,
            password="password-sentinel",
        ),
    )
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[profile],
            bundle_reader=reader,
            executor_factory=executor_factory,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#apply-start")
        await pilot.pause()
        await pilot.click("#confirm-apply")
        await app.workers.wait_for_complete()
        await pilot.pause()

        text = "\n".join(_plain(widget) for widget in app.query(Static))
        assert app.session.apply_status == expected_status
        assert "password-sentinel" not in text
        assert "exception-host-sentinel" not in text
        assert "password-sentinel" not in caplog.text
        assert "exception-host-sentinel" not in caplog.text


@pytest.mark.unit
async def test_bundle_read_failure_is_generic(tmp_path: Path) -> None:
    reader = _FakeBundleReader((b"", b""), error=OSError("password-sentinel host-sentinel"))
    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            _RecordingMigrationWriter(),
            profiles=[_profile("pilot")],
            bundle_reader=reader,
            executor_factory=_RecordingExecutorFactory(_FakeMigrationExecutor()),
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "unreadable-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert app.session.apply_status == "Could not load migration bundle."
        text = "\n".join(_plain(widget) for widget in app.query_one("#apply").query(Static))
        assert "password-sentinel" not in text
        assert "host-sentinel" not in text


@pytest.mark.unit
async def test_migration_rollback_toggle() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        mig = app.query_one("#migration", MigrationView)
        assert mig.show_rollback is False
        mig.show_rollback = True
        await pilot.pause()
        assert mig.show_rollback is True


@pytest.mark.unit
async def test_migration_generation_renders_bundle_and_execution_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _RecordingMigrationWriter()
    app = PgsdApp(dependencies=_migration_dependencies(tmp_path, writer))
    caller_thread = threading.get_ident()
    generation_threads: list[int] = []
    render_threads: list[int] = []
    original_generate = generate_migration
    original_render = render_bundle

    def track_generate(deltas: DeltaSet, *, max_risk: RiskLevel) -> MigrationPlan:
        generation_threads.append(threading.get_ident())
        return original_generate(deltas, max_risk=max_risk)

    def track_render(plan: MigrationPlan) -> RenderedBundle:
        render_threads.append(threading.get_ident())
        return original_render(plan)

    monkeypatch.setattr(tui_app_module, "generate_migration", track_generate, raising=False)
    monkeypatch.setattr(tui_app_module, "render_bundle", track_render, raising=False)

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        _install_comparison(app, _create_schema_delta(comment=r"C:\[x]"))
        await pilot.pause()
        risk = app.query_one("#mig-risk", Select)
        assert risk.value == RiskLevel.DANGEROUS.value
        assert app.query_one("#mig-output-dir", Input).value == "./migrations"

        await pilot.click("#mig-generate")
        await app.workers.wait_for_complete()
        await pilot.pause()

        plan = app.session.migration_plan
        bundle = app.session.rendered_bundle
        assert plan is not None
        assert bundle is not None
        assert plan.slug == "diff"
        assert "CREATE SCHEMA" in _plain(app.query_one("#mig-up-sql", Static))
        assert r"C:\[x]" in _plain(app.query_one("#mig-up-sql", Static))

        files = dict(bundle.files)
        manifest = json.loads(files["manifest.json"])
        checksum = manifest["checksums"]["up_sql_sha256"]
        metadata = _plain(app.query_one("#mig-metadata", Static))
        assert checksum in metadata
        assert str(plan.created_at.isoformat()) in metadata
        assert "1 delta" in metadata
        assert str(len(files["up.sql"])) in metadata

        units = app.query_one("#mig-units", DataTable)
        assert units.row_count == 1
        row = units.get_row_at(0)
        assert tuple(str(value) for value in row) == (
            "0",
            "transactional",
            "2",
            "d0001",
            "safe — Creates an empty schema.",
        )
        assert any(thread != caller_thread for thread in generation_threads)
        assert any(thread != caller_thread for thread in render_threads)
        assert app.query_one("#mig-apply", Button).disabled
        screen_text = "\n".join(
            _plain(widget) for widget in app.query_one("#migration").query(Static)
        )
        assert "N/A — no lock/row-count estimator." in screen_text
        assert "lock estimate" not in screen_text.lower()
        assert "conflicts skipped" not in screen_text.lower()


@pytest.mark.unit
async def test_migration_risk_gate_displays_safe_details_and_requires_destructive_selection(
    tmp_path: Path,
) -> None:
    writer = _RecordingMigrationWriter()
    app = PgsdApp(dependencies=_migration_dependencies(tmp_path, writer))

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        _install_comparison(app, _drop_schema_delta())
        await pilot.pause()
        risk = app.query_one("#mig-risk", Select)
        assert risk.value == RiskLevel.DANGEROUS.value

        await pilot.click("#mig-generate")
        await app.workers.wait_for_complete()
        await pilot.pause()

        gate = _plain(app.query_one("#mig-status", Static))
        assert "Migration risk gate failed (max_risk=dangerous)" in gate
        assert "d0001 kind=drop_schema" in gate
        assert "level=destructive" in gate
        assert "Removes a schema and its objects." in gate
        assert app.session.migration_plan is None
        assert app.session.rendered_bundle is None
        assert "DROP SCHEMA" not in "\n".join(
            _plain(widget) for widget in app.query_one("#migration").query(Static)
        )

        await pilot.click("#mig-risk")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#mig-generate")
        await app.workers.wait_for_complete()
        await pilot.pause()

        generated_plan = cast("MigrationPlan | None", app.session.migration_plan)
        assert generated_plan is not None
        assert generated_plan.overall_max_risk is RiskLevel.DESTRUCTIVE
        assert "DROP SCHEMA" in _plain(app.query_one("#mig-up-sql", Static))


@pytest.mark.unit
async def test_unexpected_generation_error_shows_only_generic_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _RecordingMigrationWriter()
    app = PgsdApp(dependencies=_migration_dependencies(tmp_path, writer))

    def fail_generation(_deltas: DeltaSet, *, max_risk: RiskLevel) -> MigrationPlan:
        _ = max_risk
        raise RuntimeError("secret SQL C:\\[x]")

    monkeypatch.setattr(tui_app_module, "generate_migration", fail_generation, raising=False)

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        _install_comparison(app, _create_schema_delta())
        await pilot.pause()
        await pilot.click("#mig-generate")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert (
            _plain(app.query_one("#mig-status", Static)) == "Could not generate migration bundle."
        )
        assert app.session.migration_plan is None
        assert app.session.rendered_bundle is None


@pytest.mark.unit
async def test_save_bundle_uses_writer_and_enables_apply_only_after_success(tmp_path: Path) -> None:
    writer = _RecordingMigrationWriter()
    app = PgsdApp(dependencies=_migration_dependencies(tmp_path, writer))

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        _install_comparison(app, _create_schema_delta())
        await pilot.pause()
        await pilot.click("#mig-generate")
        await app.workers.wait_for_complete()
        await pilot.pause()

        output_dir = app.query_one("#mig-output-dir", Input)
        output_dir.value = str(tmp_path)
        caller_thread = threading.get_ident()
        await pilot.click("#mig-save")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert len(writer.calls) == 1
        assert writer.calls[0][1] == tmp_path
        assert writer.thread_id != caller_thread
        assert app.session.written_bundle_path is not None
        assert app.session.written_bundle_path.is_dir()
        assert app.session.written_bundle_path.parent == tmp_path
        assert str(app.session.written_bundle_path) in _plain(
            app.query_one("#mig-written-path", Static)
        )
        assert not app.query_one("#mig-apply", Button).disabled


@pytest.mark.unit
async def test_save_bundle_missing_directory_is_generic_and_never_created(tmp_path: Path) -> None:
    writer = _RecordingMigrationWriter()
    app = PgsdApp(dependencies=_migration_dependencies(tmp_path, writer))
    missing = tmp_path / "missing-parent"

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        _install_comparison(app, _create_schema_delta())
        await pilot.pause()
        await pilot.click("#mig-generate")
        await app.workers.wait_for_complete()
        await pilot.pause()

        app.query_one("#mig-output-dir", Input).value = str(missing)
        await pilot.click("#mig-save")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert _plain(app.query_one("#mig-status", Static)) == "Could not save migration bundle."
        assert not missing.exists()
        assert app.session.written_bundle_path is None
        assert app.query_one("#mig-apply", Button).disabled


@pytest.mark.unit
async def test_new_comparison_and_profile_change_invalidate_migration_state(tmp_path: Path) -> None:
    writer = _RecordingMigrationWriter()
    next_comparison = _comparison(_create_schema_delta(comment="new"))

    async def compare(
        _source: str, _target: str, _schemas: list[str] | None
    ) -> SchemaComparisonResult:
        return next_comparison

    app = PgsdApp(
        dependencies=_migration_dependencies(
            tmp_path,
            writer,
            profiles=[_profile("first"), _profile("second")],
            compare=compare,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        plan = generate_migration(_comparison(_create_schema_delta()).deltas)
        bundle = render_bundle(plan)
        app.session.last_comparison = _comparison(_create_schema_delta())
        app.session.migration_plan = plan
        app.session.rendered_bundle = bundle
        app.session.written_bundle_path = tmp_path
        app.query_one("#migration", MigrationView).update_from_session(app.session)
        await pilot.pause()
        assert not app.query_one("#mig-apply", Button).disabled

        app.action_test_both()
        invalidated_state = (
            cast("MigrationPlan | None", app.session.migration_plan),
            cast("RenderedBundle | None", app.session.rendered_bundle),
            cast("Path | None", app.session.written_bundle_path),
        )
        assert invalidated_state == (None, None, None)
        await pilot.pause()
        assert app.query_one("#mig-apply", Button).disabled
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.session.last_comparison is next_comparison
        comparison_state = (
            cast("MigrationPlan | None", app.session.migration_plan),
            cast("RenderedBundle | None", app.session.rendered_bundle),
            cast("Path | None", app.session.written_bundle_path),
        )
        assert comparison_state == (None, None, None)

        app.session.migration_plan = plan
        app.session.rendered_bundle = bundle
        app.session.written_bundle_path = tmp_path
        app.query_one("#migration", MigrationView).update_from_session(app.session)
        app.on_profile_selected(ProfileSelected(1))
        await pilot.pause()
        profile_state = (
            cast("SchemaComparisonResult | None", app.session.last_comparison),
            cast("MigrationPlan | None", app.session.migration_plan),
            cast("RenderedBundle | None", app.session.rendered_bundle),
            cast("Path | None", app.session.written_bundle_path),
        )
        assert profile_state == (None, None, None, None)
        assert app.query_one("#mig-apply", Button).disabled


@pytest.mark.unit
async def test_diff_forward_sql_uses_plan_statements_for_selected_delta() -> None:
    app = PgsdApp()
    delta = _create_schema_delta(comment="plan preview")
    comparison = _comparison(delta)
    plan = generate_migration(comparison.deltas)

    async with app.run_test(size=(150, 50)) as pilot:
        await pilot.pause()
        app.session.last_comparison = comparison
        app.session.migration_plan = plan
        diff = app.query_one("#diff", DiffView)
        diff.update_from_session(app.session)
        diff.delta_id = "d0001"
        await pilot.pause()

        rendered = "\n".join(_plain(widget) for widget in diff.query(Static))
        assert "Generate a plan to preview SQL" not in rendered
        assert "CREATE SCHEMA" in rendered
        assert "COMMENT ON SCHEMA" in rendered


@pytest.mark.unit
async def test_history_row_selection_updates_detail() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        hist = app.query_one("#history", HistoryView)
        hist.selected_id = "h-238"
        await pilot.pause()
        assert hist.selected_id == "h-238"


@pytest.mark.unit
def test_tui_dependencies_default_history_factory_builds_postgres_reader() -> None:
    dependencies = create_tui_dependencies()

    reader = dependencies.history_reader_factory("postgresql://history-test")

    assert isinstance(reader, PostgresMigrationHistoryReader)


@pytest.mark.unit
async def test_history_loads_selected_target_and_renders_persisted_timeline(
    tmp_path: Path,
) -> None:
    profile = _profile("selected")
    reader = _RecordingHistoryReader(_history_runs())
    factory = _RecordingHistoryReaderFactory(reader)
    app = PgsdApp(dependencies=_history_dependencies(tmp_path, profile, factory))

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.switch_view("history")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert factory.conninfos == [profile.target.dsn()]
        assert reader.limits == [50]
        run_list = "\n".join(_plain(row) for row in app.query_one("#history-runs").query(Static))
        assert run_list.index("bundle-new") < run_list.index("bundle-old")
        assert "applied" in run_list
        assert "failed" in run_list
        assert "running" in run_list
        assert "cancelled" in run_list
        assert "2026-10-26" in run_list
        assert "90.00s" in run_list
        assert "n/a" in run_list
        assert app.session.selected_history_bundle_id == "bundle-running"
        assert "failure: n/a" in _plain(app.query_one("#history-timeline", Static))

        await pilot.click("#history-run-2")
        await pilot.pause()
        assert app.session.selected_history_bundle_id == "bundle-old"
        detail = _plain(app.query_one("#history-detail", Static))
        timeline = _plain(app.query_one("#history-timeline", Static))
        assert "bundle-old" in detail
        assert "sha256:1234567890ab…" in detail
        assert "unit 3" in timeline
        assert "transactional: no" in timeline
        assert "statement index 2" in timeline
        assert "UndefinedTable" in timeline
        assert "SQLSTATE 42P01" in timeline

        history_text = "\n".join(
            _plain(widget) for widget in app.query_one("#history").query(Static)
        )
        hidden_labels = (
            "author",
            "snapshot",
            "dump",
            "rollback",
            "dry-run",
            "pending",
            "rolled-back",
        )
        for hidden in hidden_labels:
            assert hidden not in history_text.lower()

        await pilot.click("#history-refresh")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert reader.calls == 2


@pytest.mark.unit
async def test_history_load_does_not_cancel_running_comparison(tmp_path: Path) -> None:
    profile = _profile("selected")
    release = asyncio.Event()
    comparison = _comparison()

    async def slow_compare(
        _source: str, _target: str, _schemas: list[str] | None
    ) -> SchemaComparisonResult:
        await release.wait()
        return comparison

    reader = _RecordingHistoryReader(_history_runs())
    dependencies = dataclasses.replace(
        _history_dependencies(tmp_path, profile, _RecordingHistoryReaderFactory(reader)),
        compare=slow_compare,
    )
    app = PgsdApp(dependencies=dependencies)

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app._start_test_both()
        await pilot.pause()
        app.switch_view("history")
        await pilot.pause()
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert app.session.last_comparison is comparison
        assert reader.calls == 1


@pytest.mark.unit
async def test_history_shows_empty_state(tmp_path: Path) -> None:
    profile = _profile("empty")
    reader = _RecordingHistoryReader()
    app = PgsdApp(
        dependencies=_history_dependencies(
            tmp_path,
            profile,
            _RecordingHistoryReaderFactory(reader),
        )
    )

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.switch_view("history")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert _plain(app.query_one("#history-status", Static)) == "No migration history found."
        assert len(app.query_one("#history-runs").query("#history-run-0")) == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            MigrationHistoryUnavailableError("history-secret-sentinel"),
            "History unavailable (incompatible layout).",
        ),
        (OperationalError("history-secret-sentinel"), "Could not load migration history."),
        (RuntimeError("history-secret-sentinel"), "Could not load migration history."),
    ],
    ids=["incompatible-layout", "postgres-error", "unexpected-error"],
)
async def test_history_errors_are_fixed_and_redacted(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    expected_status: str,
) -> None:
    profile = _profile("errors")
    reader = _RecordingHistoryReader(error=error)
    app = PgsdApp(
        dependencies=_history_dependencies(
            tmp_path,
            profile,
            _RecordingHistoryReaderFactory(reader),
        )
    )

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.switch_view("history")
        await app.workers.wait_for_complete()
        await pilot.pause()

        view_text = "\n".join(_plain(widget) for widget in app.query_one("#history").query(Static))
        assert _plain(app.query_one("#history-status", Static)) == expected_status
        assert "history-secret-sentinel" not in view_text
        assert "history-secret-sentinel" not in caplog.text


@pytest.mark.unit
async def test_history_without_profile_does_not_start_reader() -> None:
    app = PgsdApp()

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.switch_view("history")
        await pilot.pause()

        assert _plain(app.query_one("#history-status", Static)) == "No profile selected."


@pytest.mark.unit
async def test_history_result_from_previous_profile_is_ignored(tmp_path: Path) -> None:
    first = _profile("first-target")
    second = _profile("second-target")
    app = PgsdApp(
        dependencies=_history_dependencies(
            tmp_path,
            first,
            _RecordingHistoryReaderFactory(_RecordingHistoryReader()),
            profiles=[first, second],
        )
    )

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        old_profile = app.session.selected_profile
        assert old_profile is first
        app.session.select_profile(second)

        app.on_history_load_finished(
            tui_app_module.HistoryLoadFinished(id(first), runs=_history_runs())
        )

        assert app.session.history_runs == ()
        assert app.session.selected_history_bundle_id is None


@pytest.mark.unit
async def test_history_markup_like_values_are_rendered_as_literal_text(tmp_path: Path) -> None:
    literal = "[bold]literal[/] $primary"
    started = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    run = MigrationHistoryRun(
        bundle_id=literal,
        status="failed",
        started_at=started,
        finished_at=started + timedelta(seconds=1),
        up_sql_sha256="abcdef0123456789" * 4,
        units=(
            MigrationHistoryUnit(
                index=0,
                status="failed",
                transactional=True,
                started_at=started,
                finished_at=started + timedelta(seconds=1),
                failed_statement_index=0,
                error_class=literal,
                sqlstate=literal,
            ),
        ),
    )
    reader = _RecordingHistoryReader((run,))
    app = PgsdApp(
        dependencies=_history_dependencies(
            tmp_path,
            _profile("markup"),
            _RecordingHistoryReaderFactory(reader),
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.switch_view("history")
        await app.workers.wait_for_complete()
        await pilot.pause()

        text = "\n".join(_plain(widget) for widget in app.query_one("#history").query(Static))
        assert text.count(literal) >= 3


@pytest.mark.unit
async def test_history_does_not_read_during_apply_and_refreshes_after_finish(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    executor = _FakeMigrationExecutor(started=started, release=release)
    executor_factory = _RecordingExecutorFactory(executor)
    reader = _RecordingHistoryReader()
    profile = _profile("apply-history")
    app = PgsdApp(
        dependencies=_history_dependencies(
            tmp_path,
            profile,
            _RecordingHistoryReaderFactory(reader),
            bundle_reader=_FakeBundleReader(_bundle_files(_create_schema_delta())),
            executor_factory=executor_factory,
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.written_bundle_path = tmp_path / "saved-bundle"
        app.switch_view("apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#apply-start")
        await pilot.pause()
        await pilot.click("#confirm-apply")
        await started.wait()
        await pilot.pause()

        app.switch_view("history")
        await pilot.pause()
        assert app.session.apply_operation == "apply"
        assert _history_read_count(reader) == 0
        assert _plain(app.query_one("#history-status", Static)) == "History refresh after apply."
        await pilot.click("#history-refresh")
        await pilot.pause()
        assert _history_read_count(reader) == 0

        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert _history_read_count(reader) == 1


@pytest.mark.unit
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_history_refreshes_after_every_apply_outcome(
    tmp_path: Path,
    outcome: str,
) -> None:
    reader = _RecordingHistoryReader()
    app = PgsdApp(
        dependencies=_history_dependencies(
            tmp_path,
            _profile(f"apply-{outcome}"),
            _RecordingHistoryReaderFactory(reader),
        )
    )

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.session.apply_operation = "apply"
        if outcome == "failure":
            message = tui_app_module.ApplyOperationFinished(error_message="Migration apply failed.")
        elif outcome == "cancelled":
            message = tui_app_module.ApplyOperationFinished(cancelled=True)
        else:
            message = tui_app_module.ApplyOperationFinished()

        app.on_apply_operation_finished(message)
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert reader.calls == 1


@pytest.mark.unit
async def test_rollback_palette_selects_history_run_without_executing_sql(tmp_path: Path) -> None:
    reader = _RecordingHistoryReader(_history_runs())
    app = PgsdApp(
        dependencies=_history_dependencies(
            tmp_path,
            _profile("rollback"),
            _RecordingHistoryReaderFactory(reader),
        )
    )

    async with app.run_test(size=(150, 50)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app._dispatch_command("rollback bundle-old")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert app._active_view == "history"
        assert app.session.selected_history_bundle_id == "bundle-old"
        assert "Rollback is not available; down.sql is notes only." in app.query_one(Cmdbar).hint
        assert reader.calls == 1


@pytest.mark.unit
async def test_slash_focuses_sidebar_search() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        assert isinstance(app.focused, Input)
        assert app.focused.id == "sidebar-search"


@pytest.mark.unit
async def test_ctrl_b_toggles_sidebar() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        sidebar = app.query_one("#sidebar")
        assert not sidebar.has_class("hidden")
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert sidebar.has_class("hidden")


@pytest.mark.unit
def test_every_diff_has_forward_sql() -> None:
    for key, obj in DIFFS.items():
        assert obj.forward, f"{key} missing forward DDL"
        assert obj.inline, f"{key} missing inline diff"
