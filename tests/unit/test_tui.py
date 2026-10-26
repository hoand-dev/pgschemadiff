"""Smoke + interaction tests for the Textual TUI shell (task P4-TUI-01)."""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from rich.text import Text
from textual.content import Content
from textual.widgets import Button, ContentSwitcher, DataTable, Input, Select, Static
from typer.testing import CliRunner

import pgschemadiff.presentation.tui.app as tui_app_module
from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.render import RenderedBundle, render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import CreateSchema, DeltaBase, DeltaSet, DropSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.models import ConnectionInfo, Profile
from pgschemadiff.domain.schema import Schema
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.presentation.cli.main import app as cli_app
from pgschemadiff.presentation.composition import TuiDependencies
from pgschemadiff.presentation.tui import PgsdApp
from pgschemadiff.presentation.tui._mock import AI_SUGGESTIONS, DIFFS
from pgschemadiff.presentation.tui.app import _VIEW_CHORDS
from pgschemadiff.presentation.tui.screens.ai import AiModal
from pgschemadiff.presentation.tui.screens.help import HelpScreen
from pgschemadiff.presentation.tui.screens.main import MainScreen
from pgschemadiff.presentation.tui.views import ApplyView, DiffView, MigrationView
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
    from pathlib import Path

    from pgschemadiff.application.migration.model import MigrationPlan
    from pgschemadiff.application.migration.ports import BundleReader, MigrationWriter
    from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader
    from pgschemadiff.presentation.composition import (
        CompareCallable,
        ExecutorFactory,
        InspectorScope,
    )


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


def _migration_dependencies(
    tmp_path: Path,
    writer: _RecordingMigrationWriter,
    *,
    profiles: list[Profile] | None = None,
    compare: object | None = None,
) -> TuiDependencies:
    loader = _FakeProfileLoader(tmp_path / "profiles.yaml", profiles or [])
    return TuiDependencies(
        profile_loader=cast("ProfileLoader", loader),
        inspector_scope=cast("InspectorScope", Mock()),
        migration_writer=cast("MigrationWriter", writer),
        bundle_reader=cast("BundleReader", Mock()),
        executor_factory=cast("ExecutorFactory", Mock()),
        compare=cast("CompareCallable", compare) if compare is not None else _no_compare,
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
async def test_tui_unknown_command_shows_vim_style_error() -> None:
    app = PgsdApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._dispatch_command("bogusverb")
        await pilot.pause()
        assert "E492" in app.query_one(Cmdbar).hint


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
async def test_ai_requested_opens_modal() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.screen.post_message(AiRequested(AI_SUGGESTIONS[1].target))
        await pilot.pause()
        assert isinstance(app.screen, AiModal)
        await pilot.press("escape")
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
async def test_apply_run_worker_completes() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.press("g", "a")
        await pilot.pause()
        apply_view = app.query_one("#apply", ApplyView)
        apply_view._start()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert apply_view.phase == "success"


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
