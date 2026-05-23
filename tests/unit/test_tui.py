"""Smoke + interaction tests for the Textual TUI shell (task P4-TUI-01)."""

from __future__ import annotations

import pytest
from textual.widgets import Input
from typer.testing import CliRunner

from pgschemadiff.presentation.cli.main import app as cli_app
from pgschemadiff.presentation.tui import PgsdApp
from pgschemadiff.presentation.tui.app import _VIEW_CHORDS
from pgschemadiff.presentation.tui.screens.help import HelpScreen
from pgschemadiff.presentation.tui.screens.main import MainScreen
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
