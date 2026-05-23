"""Tests for ProfileLoader."""

from __future__ import annotations

from pathlib import Path

from pgschemadiff.domain.models import ConnectionInfo, Profile
from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader


def _make_profile(name: str, src_host: str = "src", tgt_host: str = "tgt") -> Profile:
    src = ConnectionInfo(host=src_host, database="db", user="user")
    tgt = ConnectionInfo(host=tgt_host, database="db", user="user")
    return Profile(name=name, source=src, target=tgt)


def test_load_nonexistent_file(tmp_path: Path) -> None:
    loader = ProfileLoader(tmp_path / "nonexistent.yaml")
    assert loader.load() == []


def test_load_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "profiles.yaml"
    p.write_text("")
    assert ProfileLoader(p).load() == []


def test_load_no_profiles_key(tmp_path: Path) -> None:
    p = tmp_path / "profiles.yaml"
    p.write_text("other_key: value\n")
    assert ProfileLoader(p).load() == []


def test_roundtrip_single_profile(tmp_path: Path) -> None:
    profile = _make_profile("test-profile", "localhost", "remote")
    config_file = tmp_path / "profiles.yaml"

    loader = ProfileLoader(config_file)
    loader.save([profile])

    loaded = loader.load()
    assert len(loaded) == 1
    assert loaded[0].name == "test-profile"
    assert loaded[0].source.host == "localhost"
    assert loaded[0].target.host == "remote"


def test_roundtrip_multiple_profiles(tmp_path: Path) -> None:
    profiles = [_make_profile(f"profile-{i}") for i in range(3)]
    config_file = tmp_path / "profiles.yaml"

    loader = ProfileLoader(config_file)
    loader.save(profiles)

    loaded = loader.load()
    assert len(loaded) == 3
    assert [p.name for p in loaded] == ["profile-0", "profile-1", "profile-2"]


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    config_file = tmp_path / "nested" / "deep" / "profiles.yaml"
    loader = ProfileLoader(config_file)
    loader.save([_make_profile("p")])
    assert config_file.exists()


def test_roundtrip_preserves_unicode(tmp_path: Path) -> None:
    profile = _make_profile("dev → staging")
    loader = ProfileLoader(tmp_path / "profiles.yaml")
    loader.save([profile])

    loaded = loader.load()
    assert loaded[0].name == "dev → staging"
