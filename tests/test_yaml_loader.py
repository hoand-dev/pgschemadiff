"""Tests for ProfileLoader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader


@pytest.fixture
def sample_yaml(tmp_path: Path) -> Path:
    data = {
        "profiles": [
            {
                "name": "local-dev",
                "source": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "mydb_dev",
                    "user": "alice",
                },
                "target": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "mydb_prod",
                    "user": "alice",
                },
                "schemas": ["public", "audit"],
                "ignore_patterns": ["*.tmp"],
                "mode": "schema-only",
            }
        ]
    }
    config_file = tmp_path / "profiles.yaml"
    config_file.write_text(yaml.safe_dump(data))
    return config_file


def test_load_profiles(sample_yaml: Path) -> None:
    loader = ProfileLoader(sample_yaml)
    profiles = loader.load()
    assert len(profiles) == 1
    p = profiles[0]
    assert p.name == "local-dev"
    assert p.schemas == ["public", "audit"]
    assert p.ignore_patterns == ["*.tmp"]


def test_load_missing_file(tmp_path: Path) -> None:
    loader = ProfileLoader(tmp_path / "nonexistent.yaml")
    assert loader.load() == []


def test_load_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.yaml"
    f.write_text("")
    loader = ProfileLoader(f)
    assert loader.load() == []


def test_roundtrip_save_load(sample_yaml: Path, tmp_path: Path) -> None:
    loader = ProfileLoader(sample_yaml)
    profiles = loader.load()

    out = tmp_path / "out.yaml"
    saver = ProfileLoader(out)
    saver.save(profiles)

    loader2 = ProfileLoader(out)
    profiles2 = loader2.load()
    assert len(profiles2) == 1
    assert profiles2[0].name == profiles[0].name
    assert profiles2[0].schemas == profiles[0].schemas
