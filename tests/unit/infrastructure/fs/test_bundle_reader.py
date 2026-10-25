"""Tests for filesystem migration bundle reads."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader

pytestmark = pytest.mark.unit


def test_reads_only_manifest_and_up_sql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "manifest.json").write_bytes(b"manifest")
    (bundle_dir / "up.sql").write_bytes(b"up")
    (bundle_dir / "down.sql").write_bytes(b"down")
    read_bytes = Path.read_bytes
    read_paths: list[str] = []

    def tracked_read(path: Path) -> bytes:
        read_paths.append(path.name)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read)

    assert FilesystemBundleReader().read(bundle_dir) == (b"manifest", b"up")
    assert read_paths == ["manifest.json", "up.sql"]


@pytest.mark.parametrize("missing", ["manifest.json", "up.sql"])
def test_missing_required_file_raises_oserror(tmp_path: Path, missing: str) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    for name in {"manifest.json", "up.sql"} - {missing}:
        (bundle_dir / name).write_bytes(b"content")

    with pytest.raises(FileNotFoundError):
        FilesystemBundleReader().read(bundle_dir)


def test_non_directory_bundle_path_raises_oserror(tmp_path: Path) -> None:
    bundle_path = tmp_path / "not-a-directory"
    bundle_path.write_text("file", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        FilesystemBundleReader().read(bundle_path)


def test_nonexistent_bundle_path_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FilesystemBundleReader().read(tmp_path / "missing")


@pytest.mark.parametrize("entry_name", ["manifest.json", "up.sql"])
def test_symlinked_bundle_file_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_name: str,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    for name in ("manifest.json", "up.sql"):
        (bundle_dir / name).write_bytes(b"content")
    lstat = Path.lstat

    def report_symlink(path: Path) -> os.stat_result:
        if path.name == entry_name:
            return os.stat_result((stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", report_symlink)

    with pytest.raises(OSError, match="regular file"):
        FilesystemBundleReader().read(bundle_dir)
