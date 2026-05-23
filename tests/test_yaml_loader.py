"""Tests for ProfileLoader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader


def _write_yaml(path: Path, profiles: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump({"profiles": profiles}, f)


_SAMPLE = {
    "name": "dev → staging",
    "source": {"host": "localhost", "port": 5432, "database": "dev", "user": "u"},
    "target": {"host": "staging", "port": 5432, "database": "app", "user": "app"},
    "schemas": ["public"],
    "ignore_patterns": [],
    "mode": "schema-only",
}


def test_load_returns_profiles(tmp_path: Path) -> None:
    cfg = tmp_path / "profiles.yaml"
    _write_yaml(cfg, [_SAMPLE])
    loader = ProfileLoader(cfg)
    profiles = loader.load()
    assert len(profiles) == 1
    assert profiles[0].name == "dev → staging"


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    loader = ProfileLoader(tmp_path / "nonexistent.yaml")
    assert loader.load() == []


def test_load_empty_file_returns_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text("")
    assert ProfileLoader(cfg).load() == []


def test_roundtrip_save_load(tmp_path: Path) -> None:
    cfg = tmp_path / "profiles.yaml"
    _write_yaml(cfg, [_SAMPLE])
    loader = ProfileLoader(cfg)
    profiles = loader.load()
    loader.save(profiles)
    reloaded = loader.load()
    assert len(reloaded) == 1
    assert reloaded[0].name == profiles[0].name
    assert reloaded[0].source.host == profiles[0].source.host
