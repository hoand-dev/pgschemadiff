"""Tests for YAML profile loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pgschemadiff.domain.models import Profile
from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader


@pytest.fixture
def profiles_yaml(tmp_path: Path) -> Path:
    data = {
        "profiles": [
            {
                "name": "dev → staging",
                "source": {"host": "localhost", "port": 5432, "database": "app_dev", "user": "henrik", "password": ""},
                "target": {"host": "staging", "port": 5432, "database": "app", "user": "app", "password": ""},
                "schemas": ["public", "billing"],
                "ignore_patterns": ["temp_*"],
                "mode": "schema-only",
            }
        ]
    }
    p = tmp_path / "profiles.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_load_profiles(profiles_yaml: Path):
    loader = ProfileLoader(profiles_yaml)
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


def test_roundtrip_save_load(tmp_path: Path):
    path = tmp_path / "profiles.yaml"
    src_conn = {"host": "a", "port": 5432, "database": "db1", "user": "u", "password": ""}
    tgt_conn = {"host": "b", "port": 5432, "database": "db2", "user": "u", "password": ""}
    profile = Profile.model_validate({"name": "test", "source": src_conn, "target": tgt_conn})

    loader = ProfileLoader(path)
    loader.save([profile])
    loaded = loader.load()

    assert len(loaded) == 1
    assert loaded[0].name == "test"
    assert loaded[0].source.host == "a"
    assert loaded[0].target.host == "b"


def test_save_creates_parent_dirs(tmp_path: Path):
    path = tmp_path / "subdir" / "nested" / "profiles.yaml"
    src_conn = {"host": "a", "port": 5432, "database": "db1", "user": "u", "password": ""}
    tgt_conn = {"host": "b", "port": 5432, "database": "db2", "user": "u", "password": ""}
    profile = Profile.model_validate({"name": "test", "source": src_conn, "target": tgt_conn})

    loader = ProfileLoader(path)
    loader.save([profile])
    assert path.exists()
