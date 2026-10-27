from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.domain.delta import CreateSchema, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.presentation.cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

_CREATED_AT = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
_FINGERPRINT = "sha256:" + "0" * 64


def _write_bundle(output_dir: Path) -> Path:
    ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="report_app"),
    )
    plan = generate_migration(
        DeltaSet.from_iterable((CreateSchema(target=ref, pg_schema=Schema(ref=ref)),)),
        source_fingerprint=_FINGERPRINT,
        target_fingerprint=_FINGERPRINT,
        slug="report-test",
        clock=lambda: _CREATED_AT,
        id_factory=lambda: "report-bundle",
    )
    return FilesystemMigrationWriter().write(plan, output_dir)


def test_report_command_is_registered() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "report" in result.output


def test_report_prints_validated_bundle_html_to_stdout(tmp_path: Path) -> None:
    bundle_dir = _write_bundle(tmp_path)

    result = CliRunner().invoke(app, ["report", str(bundle_dir)])

    assert result.exit_code == 0
    assert "<!doctype html>" in result.stdout
    assert "report-bundle" in result.stdout
    assert "report-test" in result.stdout
    assert "d0001" in result.stdout
    assert "CREATE SCHEMA" in result.stdout
    assert "Content-Security-Policy" in result.stdout
    assert result.stderr == ""


def test_report_writes_html_to_new_output_file(tmp_path: Path) -> None:
    bundle_dir = _write_bundle(tmp_path)
    report_path = tmp_path / "report.html"

    result = CliRunner().invoke(app, ["report", str(bundle_dir), "--out", str(report_path)])

    assert result.exit_code == 0
    assert result.stdout == ""
    assert report_path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_report_rejects_invalid_bundle_with_exit_two(tmp_path: Path) -> None:
    bundle_dir = _write_bundle(tmp_path)
    (bundle_dir / "up.sql").write_text("-- changed\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["report", str(bundle_dir)])

    assert result.exit_code == 2
    assert result.stderr.startswith("Error: Invalid migration bundle:")


def test_report_refuses_to_overwrite_output_file(tmp_path: Path) -> None:
    bundle_dir = _write_bundle(tmp_path)
    report_path = tmp_path / "report.html"
    report_path.write_text("keep me", encoding="utf-8")

    result = CliRunner().invoke(app, ["report", str(bundle_dir), "--out", str(report_path)])

    assert result.exit_code == 2
    assert report_path.read_text(encoding="utf-8") == "keep me"


def test_report_existing_output_error_uses_vietnamese(tmp_path: Path) -> None:
    bundle_dir = _write_bundle(tmp_path)
    report_path = tmp_path / "report.html"
    report_path.write_text("keep me", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["report", str(bundle_dir), "--out", str(report_path)],
        env={"PGSD_LANG": "vi"},
    )

    assert result.exit_code == 2
    assert result.stderr == "Lỗi: Tệp --out đã tồn tại.\n"
    assert report_path.read_text(encoding="utf-8") == "keep me"


def test_report_rejects_missing_output_parent_with_exit_two(tmp_path: Path) -> None:
    bundle_dir = _write_bundle(tmp_path)
    report_path = tmp_path / "missing" / "report.html"

    result = CliRunner().invoke(app, ["report", str(bundle_dir), "--out", str(report_path)])

    assert result.exit_code == 2
    assert not report_path.parent.exists()
