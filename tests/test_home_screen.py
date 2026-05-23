"""Integration tests for HomeScreen using Textual Pilot."""

from __future__ import annotations

import pytest
import yaml

from pgschemadiff.presentation.app import PgSchemaDiffApp


@pytest.fixture
def app_with_profiles(tmp_path):
    profiles_data = {
        "profiles": [
            {
                "name": "alpha",
                "source": {"host": "host-a", "port": 5432, "database": "db", "user": "u", "password": ""},
                "target": {"host": "host-b", "port": 5432, "database": "db", "user": "u", "password": ""},
            },
            {
                "name": "beta",
                "source": {"host": "host-c", "port": 5432, "database": "db2", "user": "u", "password": ""},
                "target": {"host": "host-d", "port": 5432, "database": "db2", "user": "u", "password": ""},
            },
        ]
    }
    p = tmp_path / "profiles.yaml"
    p.write_text(yaml.safe_dump(profiles_data))
    return PgSchemaDiffApp(config_path=p)


@pytest.mark.asyncio
async def test_app_starts_with_home_screen(app_with_profiles):
    async with app_with_profiles.run_test() as pilot:
        await pilot.pause()
        from pgschemadiff.presentation.screens.home import HomeScreen
        assert isinstance(pilot.app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_detail_shows_first_profile_on_mount(app_with_profiles):
    async with app_with_profiles.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Static
        detail_title = pilot.app.screen.query_one("#detail-title", Static)
        assert "alpha" in str(detail_title.content)


@pytest.mark.asyncio
async def test_navigate_down_updates_detail(app_with_profiles):
    async with app_with_profiles.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Static
        await pilot.press("down")
        await pilot.pause()
        detail_title = pilot.app.screen.query_one("#detail-title", Static)
        assert "beta" in str(detail_title.content)


@pytest.mark.asyncio
async def test_delete_opens_confirm_dialog(app_with_profiles):
    async with app_with_profiles.run_test() as pilot:
        await pilot.pause()
        from pgschemadiff.presentation.screens.home import HomeScreen
        assert isinstance(pilot.app.screen, HomeScreen)

        await pilot.press("d")
        await pilot.pause()

        from pgschemadiff.presentation.widgets.confirm_dialog import ConfirmDialog
        assert isinstance(pilot.app.screen, ConfirmDialog)


@pytest.mark.asyncio
async def test_cancel_delete_keeps_profiles(app_with_profiles):
    async with app_with_profiles.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import ListView
        initial_count = len(pilot.app.screen.query_one(ListView))

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        from pgschemadiff.presentation.screens.home import HomeScreen
        assert isinstance(pilot.app.screen, HomeScreen)
        assert len(pilot.app.screen.query_one(ListView)) == initial_count
