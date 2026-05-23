"""Tests for YAML profile loader."""

from __future__ import annotations

from pathlib import Path

import yaml

from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader

_SAMPLE_YAML = {
    "profiles": [
        {
            "name": "dev → staging",
            "source": {"host": "localhost", "port": 5432, "database": "app_dev", "user": "dev", "password": ""},
            "target": {"host": "staging.db", "port": 5432, "database": "app", "user": "app", "password": ""},
            "schemas": ["public"],
            "ignore_patterns": [],
            "mode": "schema-only",
        }
    ]
}


def test_load_profiles(tmp_path: Path) -> None:
    config = tmp_path / "profiles.yaml"
    config.write_text(yaml.safe_dump(_SAMPLE_YAML))
    loader = ProfileLoader(config)
    profiles = loader.load()
    assert len(profiles) == 1
    assert profiles[0].name == "dev → staging"
    assert profiles[0].source.host == "localhost"


def test_load_missing_file(tmp_path: Path) -> None:
    loader = ProfileLoader(tmp_path / "nonexistent.yaml")
    assert loader.load() == []


def test_load_empty_file(tmp_path: Path) -> None:
    config = tmp_path / "profiles.yaml"
    config.write_text("")
    loader = ProfileLoader(config)
    assert loader.load() == []


def test_roundtrip(tmp_path: Path) -> None:
    config = tmp_path / "profiles.yaml"
    config.write_text(yaml.safe_dump(_SAMPLE_YAML))
    loader = ProfileLoader(config)
    profiles = loader.load()
    loader.save(profiles)
    reloaded = loader.load()
    assert len(reloaded) == 1
    assert reloaded[0].name == profiles[0].name
    assert reloaded[0].source.host == profiles[0].source.host


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    config = tmp_path / "nested" / "dir" / "profiles.yaml"
    loader = ProfileLoader(config)
    config2 = tmp_path / "profiles.yaml"
    config2.write_text(yaml.safe_dump(_SAMPLE_YAML))
    profiles = ProfileLoader(config2).load()
    loader.save(profiles)
    assert config.exists()
