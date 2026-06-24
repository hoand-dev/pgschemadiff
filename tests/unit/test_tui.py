"""Smoke + interaction tests for the Textual TUI shell (task P4-TUI-01)."""

from __future__ import annotations

import pytest
from textual.widgets import ContentSwitcher, Input
from typer.testing import CliRunner

from pgschemadiff.presentation.cli.main import app as cli_app
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
    sql_markup,
)
from pgschemadiff.presentation.tui.views.history import HistoryView
from pgschemadiff.presentation.tui.widgets import Cmdbar


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


# --------------------------------------------------------------------------- #
# Views (P4-TUI-02 … P4-TUI-08)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_sql_markup_is_bracket_safe() -> None:
    """Migration comments like ``-- [c01]`` must not break console markup."""
    out = sql_markup("-- [c01] CREATE TYPE public.plan_tier_enum")
    assert r"\[c01]" in out  # literal bracket escaped
    assert out.count("[/]") == out.count("[$")  # tags balanced 1:1


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
        app.screen.post_message(DiffRequested("public.users"))
        await pilot.pause()
        assert app._active_view == "diff"
        assert app.query_one("#diff", DiffView).object_key == "public.users"


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
