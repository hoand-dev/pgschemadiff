"""Tests for ProfileLoader."""

from __future__ import annotations

from pathlib import Path

from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader

SAMPLE_YAML = """\
profiles:
  - name: dev → staging
    source:
      host: localhost
      port: 5432
      database: app_dev
      user: henrik
      password: ""
    target:
      host: staging.db.local
      port: 5432
      database: app
      user: app
      password: ""
    schemas: [public, billing]
    ignore_patterns: []
    mode: schema-only
"""


def test_load_returns_profiles(tmp_path: Path):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(SAMPLE_YAML, encoding="utf-8")
    loader = ProfileLoader(cfg)
    profiles = loader.load()
    assert len(profiles) == 1
    assert profiles[0].name == "dev → staging"
    assert profiles[0].source.host == "localhost"
    assert profiles[0].target.host == "staging.db.local"


def test_load_missing_file_returns_empty(tmp_path: Path):
    loader = ProfileLoader(tmp_path / "nonexistent.yaml")
    assert loader.load() == []


def test_load_empty_file_returns_empty(tmp_path: Path):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text("", encoding="utf-8")
    loader = ProfileLoader(cfg)
    assert loader.load() == []


def test_roundtrip(tmp_path: Path):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(SAMPLE_YAML, encoding="utf-8")
    loader = ProfileLoader(cfg)
    profiles = loader.load()
    loader.save(profiles)
    reloaded = loader.load()
    assert len(reloaded) == 1
    assert reloaded[0].name == profiles[0].name
    assert reloaded[0].source.host == profiles[0].source.host
