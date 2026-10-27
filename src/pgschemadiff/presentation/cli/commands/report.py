"""``pgsd report`` command implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import typer

from pgschemadiff.application.migration.bundle import ValidatedBundle, load_bundle
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.presentation.cli import output
from pgschemadiff.presentation.i18n import t
from pgschemadiff.presentation.report.html import render_report
from pgschemadiff.presentation.report.model import from_bundle
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pathlib import Path


def _read_bundle(bundle_dir: Path) -> ValidatedBundle:
    try:
        manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    except OSError:
        output.error(t("report.error.bundle_read"), 1)

    try:
        return load_bundle(manifest_bytes, up_sql_bytes)
    except MigrationError as error:
        output.error(t("report.error.bundle_invalid", error=error), 2)


def _write_report(out_file: Path, content: str) -> None:
    if out_file.exists() or out_file.is_symlink():
        output.error(t("report.error.output_exists"), 2)
    if not out_file.parent.is_dir():
        output.error(t("report.error.output_parent"), 2)

    try:
        with out_file.open("x", encoding="utf-8", newline="\n") as report_file:
            report_file.write(content)
    except FileExistsError:
        output.error(t("report.error.output_exists"), 2)
    except OSError:
        output.error(t("report.error.write"), 1)


def report_cmd(bundle_dir: Path, out_file: Path | None = None) -> None:
    """Render a checksum-validated migration bundle as offline HTML."""
    bundle = _read_bundle(bundle_dir)
    model = from_bundle(bundle, generated_at=datetime.now(UTC))
    content = render_report(model)
    if out_file is None:
        typer.echo(content, nl=False)
    else:
        _write_report(out_file, content)
