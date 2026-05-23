"""Smoke tests for all screens using Textual Pilot."""

from __future__ import annotations

import pytest

from pgschemadiff.domain.models import ConnectionInfo, Profile
from pgschemadiff.presentation.app import PgSchemaDiffApp

SAMPLE_PROFILES = [
    Profile(
        name="dev → staging",
        source=ConnectionInfo(host="localhost", port=5432, database="app_dev", user="test"),
        target=ConnectionInfo(host="staging.local", port=5432, database="app", user="app"),
        schemas=["public", "billing"],
        ignore_patterns=["temp_*"],
        mode="schema-only",
    ),
    Profile(
        name="staging → prod",
        source=ConnectionInfo(host="staging.local", port=5432, database="app", user="app"),
        target=ConnectionInfo(host="prod.local", port=5432, database="app", user="readonly"),
        schemas=["public"],
        ignore_patterns=[],
        mode="schema-only",
    ),
]


@pytest.fixture
def config_path(tmp_path):
    import yaml
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(yaml.safe_dump({"profiles": [p.model_dump() for p in SAMPLE_PROFILES]}))
    return cfg


@pytest.mark.asyncio
async def test_home_screen_loads(config_path):
    app = PgSchemaDiffApp(config_path=config_path)
    async with app.run_test() as pilot:
        assert app.screen.__class__.__name__ == "HomeScreen"
        await pilot.pause()


@pytest.mark.asyncio
async def test_home_navigate_list(config_path):
    app = PgSchemaDiffApp(config_path=config_path)
    async with app.run_test() as pilot:
        await pilot.press("down")
        await pilot.pause()


@pytest.mark.asyncio
async def test_delete_profile_opens_confirm(config_path):
    app = PgSchemaDiffApp(config_path=config_path)
    async with app.run_test() as pilot:
        await pilot.press("d")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ConfirmDialog"
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "HomeScreen"


@pytest.mark.asyncio
async def test_compare_pushes_comparing_screen(config_path):
    app = PgSchemaDiffApp(config_path=config_path)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ComparingScreen"
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "HomeScreen"


@pytest.mark.asyncio
async def test_comparing_screen_renders(config_path):
    app = PgSchemaDiffApp(config_path=config_path)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert app.screen.__class__.__name__ == "ComparingScreen"
        screen = app.screen
        assert screen._profile.name == "dev → staging"
        await pilot.press("escape")
        await pilot.pause()
