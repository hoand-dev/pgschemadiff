"""Tests for YAML profile loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader


@pytest.fixture()
def profiles_yaml(tmp_path: Path) -> Path:
    data = {
        "profiles": [
            {
                "name": "dev → staging",
                "source": {"host": "localhost", "port": 5432, "database": "app_dev", "user": "dev", "password": ""},
                "target": {"host": "staging", "port": 5432, "database": "app", "user": "app", "password": ""},
                "schemas": ["public"],
                "ignore_patterns": [],
                "mode": "schema-only",
            }
        ]
    }
    path = tmp_path / "profiles.yaml"
    with path.open("w") as f:
        yaml.safe_dump(data, f)
    return path


def test_load_profiles(profiles_yaml: Path):
    loader = ProfileLoader(profiles_yaml)
    profiles = loader.load()
    assert len(profiles) == 1
    assert profiles[0].name == "dev → staging"
    assert profiles[0].source.host == "localhost"
    assert profiles[0].target.host == "staging"


def test_load_missing_file(tmp_path: Path):
    loader = ProfileLoader(tmp_path / "nonexistent.yaml")
    assert loader.load() == []


def test_save_and_reload(tmp_path: Path, profiles_yaml: Path):
    loader = ProfileLoader(profiles_yaml)
    profiles = loader.load()

    out_path = tmp_path / "out.yaml"
    out_loader = ProfileLoader(out_path)
    out_loader.save(profiles)

    reloaded = out_loader.load()
    assert len(reloaded) == 1
    assert reloaded[0].name == profiles[0].name
    assert reloaded[0].source.host == profiles[0].source.host
