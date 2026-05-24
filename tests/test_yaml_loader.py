"""Tests for YAML profile loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from pgschemadiff.domain.models import ConnectionInfo, Profile
from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader


def _make_profile(name: str, host: str = "localhost") -> Profile:
    conn = ConnectionInfo(host=host, port=5432, database="db", user="user")
    return Profile(name=name, source=conn, target=conn)


class TestProfileLoader:
    def test_load_missing_file_returns_empty(self) -> None:
        loader = ProfileLoader(Path("/nonexistent/path/profiles.yaml"))
        assert loader.load() == []

    def test_load_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "profiles.yaml"
        f.write_text("")
        loader = ProfileLoader(f)
        assert loader.load() == []

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        f = tmp_path / "profiles.yaml"
        loader = ProfileLoader(f)
        original = [_make_profile("alpha"), _make_profile("beta", host="remote.db")]
        loader.save(original)
        loaded = loader.load()
        assert len(loaded) == 2
        assert loaded[0].name == "alpha"
        assert loaded[1].name == "beta"
        assert loaded[1].source.host == "remote.db"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        f = tmp_path / "deep" / "nested" / "profiles.yaml"
        loader = ProfileLoader(f)
        loader.save([_make_profile("x")])
        assert f.exists()

    def test_load_preserves_schemas_and_mode(self, tmp_path: Path) -> None:
        f = tmp_path / "profiles.yaml"
        conn = ConnectionInfo(host="h", port=5432, database="d", user="u")
        p = Profile(
            name="full",
            source=conn,
            target=conn,
            schemas=["public", "audit"],
            ignore_patterns=["temp_*"],
            mode="schema-only",
        )
        ProfileLoader(f).save([p])
        loaded = ProfileLoader(f).load()
        assert loaded[0].schemas == ["public", "audit"]
        assert loaded[0].ignore_patterns == ["temp_*"]
        assert loaded[0].mode == "schema-only"
