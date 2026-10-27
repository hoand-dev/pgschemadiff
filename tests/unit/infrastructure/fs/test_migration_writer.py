"""Tests for the atomic migration bundle filesystem adapter."""

from __future__ import annotations

import builtins
import json
import os
import sys
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.ports import MigrationWriter
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.domain.delta import DeltaSet
from pgschemadiff.infrastructure.fs import migration_writer as writer_module
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

    from pgschemadiff.application.migration.model import MigrationPlan

_CREATED_AT = datetime(2026, 10, 24, 12, 30, 45, tzinfo=UTC)
_FINGERPRINT = "sha256:" + "0" * 64


def _plan() -> MigrationPlan:
    return generate_migration(
        DeltaSet.from_iterable([]),
        source_fingerprint=_FINGERPRINT,
        target_fingerprint=_FINGERPRINT,
        clock=lambda: _CREATED_AT,
        id_factory=lambda: "filesystem-plan",
    )


def _assert_failed_write_is_clean(
    writer: FilesystemMigrationWriter,
    plan: MigrationPlan,
    output_dir: Path,
) -> None:
    final_path = output_dir / render_bundle(plan).dir_name

    assert not final_path.exists()
    assert not list(output_dir.glob(f".{final_path.name}.tmp-*"))


def test_write_publishes_exact_rendered_files_and_satisfies_port(tmp_path: Path) -> None:
    plan = _plan()
    rendered = render_bundle(plan)
    writer: MigrationWriter = FilesystemMigrationWriter()

    result = writer.write(plan, tmp_path)

    assert isinstance(writer, MigrationWriter)
    assert result == tmp_path / rendered.dir_name
    assert {path.name for path in result.iterdir()} == {
        "up.sql",
        "down.sql",
        "manifest.json",
        "deltas.json",
        "README.md",
    }
    assert {path.name: path.read_bytes() for path in result.iterdir()} == dict(rendered.files)


def test_write_requires_output_directory_to_exist(tmp_path: Path) -> None:
    output_dir = tmp_path / "missing"

    with pytest.raises(MigrationError, match="Output directory"):
        FilesystemMigrationWriter().write(_plan(), output_dir)

    assert not output_dir.exists()


def test_write_refuses_existing_destination_before_file_operations(tmp_path: Path) -> None:
    plan = _plan()
    final_path = tmp_path / render_bundle(plan).dir_name
    final_path.mkdir()
    marker = final_path / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")

    with pytest.raises(MigrationError, match="already exists"):
        FilesystemMigrationWriter().write(plan, tmp_path)

    assert marker.read_text(encoding="utf-8") == "untouched"
    assert not list(tmp_path.glob(f".{final_path.name}.tmp-*"))


def test_write_rechecks_destination_immediately_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    actual_check = writer_module._destination_exists
    checks = 0

    def destination_appears(path: Path) -> bool:
        nonlocal checks
        checks += 1
        if checks == 2:
            path.mkdir()
        return actual_check(path)

    def rename_must_not_run(_source: Path, _destination: Path) -> None:
        pytest.fail("rename must not run after the second collision check")

    monkeypatch.setattr(writer_module, "_destination_exists", destination_appears)
    monkeypatch.setattr(os, "rename", rename_must_not_run)

    with pytest.raises(MigrationError, match="already exists"):
        FilesystemMigrationWriter().write(plan, tmp_path)

    assert checks == 2
    assert (tmp_path / render_bundle(plan).dir_name).is_dir()
    assert not list(tmp_path.glob(f".{render_bundle(plan).dir_name}.tmp-*"))


def test_write_failure_cleans_temp_directory_and_chains_os_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = OSError("injected write failure")

    def fail_file_write(
        _path: object,
        mode: str = "r",
        **_kwargs: object,
    ) -> BinaryIO:
        assert mode == "wb"
        raise failure

    monkeypatch.setattr(builtins, "open", fail_file_write)

    with pytest.raises(MigrationError, match=r"write.*up\.sql") as error:
        FilesystemMigrationWriter().write(_plan(), tmp_path)

    assert error.value.__cause__ is failure
    _assert_failed_write_is_clean(FilesystemMigrationWriter(), _plan(), tmp_path)


def test_fsync_failure_cleans_temp_directory_and_chains_os_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = OSError("injected fsync failure")

    def fail_fsync(_file_descriptor: int) -> None:
        raise failure

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(MigrationError, match=r"fsync.*up\.sql") as error:
        FilesystemMigrationWriter().write(_plan(), tmp_path)

    assert error.value.__cause__ is failure
    _assert_failed_write_is_clean(FilesystemMigrationWriter(), _plan(), tmp_path)


def test_parent_fsync_failure_reports_error_after_complete_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    rendered = render_bundle(plan)
    final_path = tmp_path / rendered.dir_name
    failure = OSError("injected parent fsync failure")
    fsync_directory = writer_module._fsync_directory

    def fail_parent_fsync(path: Path) -> None:
        if path == tmp_path:
            raise failure
        fsync_directory(path)

    monkeypatch.setattr(writer_module, "_fsync_directory", fail_parent_fsync)

    with pytest.raises(MigrationError, match="fsync output directory") as error:
        FilesystemMigrationWriter().write(plan, tmp_path)

    assert error.value.__cause__ is failure
    assert {path.name: path.read_bytes() for path in final_path.iterdir()} == dict(rendered.files)
    assert not list(tmp_path.glob(f".{final_path.name}.tmp-*"))


def test_rename_failure_cleans_temp_directory_and_chains_os_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = OSError("injected rename failure")

    def fail_rename(_source: Path, _destination: Path) -> None:
        raise failure

    monkeypatch.setattr(os, "rename", fail_rename)

    with pytest.raises(MigrationError, match="rename") as error:
        FilesystemMigrationWriter().write(_plan(), tmp_path)

    assert error.value.__cause__ is failure
    _assert_failed_write_is_clean(FilesystemMigrationWriter(), _plan(), tmp_path)


def test_directory_fsync_unsupported_on_windows_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_directory_open(_path: Path, _flags: int) -> int:
        raise PermissionError("directory handles unsupported")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "open", fail_directory_open)

    result = FilesystemMigrationWriter().write(_plan(), tmp_path)

    assert result.is_dir()


def test_written_manifest_checksum_matches_up_sql(tmp_path: Path) -> None:
    result = FilesystemMigrationWriter().write(_plan(), tmp_path)
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
    up_sql = (result / "up.sql").read_bytes()

    assert manifest["checksums"]["up_sql_sha256"] == sha256(up_sql).hexdigest()
