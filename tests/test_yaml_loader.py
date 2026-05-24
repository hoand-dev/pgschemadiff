"""Tests for ProfileLoader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pgschemadiff.domain.models import Profile
from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    data = {
        "profiles": [
            {
                "name": "dev → staging",
                "source": {"host": "localhost", "port": 5432, "database": "app_dev", "user": "henrik", "password": ""},
                "target": {"host": "staging.db.local", "port": 5432, "database": "app", "user": "app", "password": ""},
                "schemas": ["public", "billing"],
                "ignore_patterns": ["temp_*"],
                "mode": "schema-only",
            }
        ]
    }
    p = tmp_path / "profiles.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True))
    return p


def test_load_profiles(config_file: Path):
    loader = ProfileLoader(config_file)
    profiles = loader.load()
    assert len(profiles) == 1
    assert profiles[0].name == "dev → staging"
    assert profiles[0].schemas == ["public", "billing"]
    assert profiles[0].ignore_patterns == ["temp_*"]


def test_load_missing_file(tmp_path: Path):
    loader = ProfileLoader(tmp_path / "nonexistent.yaml")
    assert loader.load() == []


def test_load_empty_file(tmp_path: Path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    loader = ProfileLoader(p)
    assert loader.load() == []


def test_roundtrip(tmp_path: Path, config_file: Path):
    loader = ProfileLoader(config_file)
    profiles = loader.load()

    out = tmp_path / "out.yaml"
    saver = ProfileLoader(out)
    saver.save(profiles)

    reloaded = ProfileLoader(out).load()
    assert len(reloaded) == 1
    assert reloaded[0].name == profiles[0].name
    assert reloaded[0].schemas == profiles[0].schemas
