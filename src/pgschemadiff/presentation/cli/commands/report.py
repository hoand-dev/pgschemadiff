"""``pgsd report`` command implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import typer

from pgschemadiff.application.migration.bundle import ValidatedBundle, load_bundle
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.presentation.cli import output
from pgschemadiff.presentation.report.html import render_report
from pgschemadiff.presentation.report.model import from_bundle
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pathlib import Path


def _read_bundle(bundle_dir: Path) -> ValidatedBundle:
    try:
        manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    except OSError:
        output.error("Error: Could not read migration bundle.", 1)

    try:
        return load_bundle(manifest_bytes, up_sql_bytes)
    except MigrationError as error:
        output.error(f"Error: Invalid migration bundle: {error}", 2)


def _write_report(out_file: Path, content: str) -> None:
    if out_file.exists() or out_file.is_symlink():
        output.error("Error: --out file already exists.", 2)
    if not out_file.parent.is_dir():
        output.error("Error: --out parent must be an existing directory.", 2)

    try:
        with out_file.open("x", encoding="utf-8", newline="\n") as report_file:
            report_file.write(content)
    except FileExistsError:
        output.error("Error: --out file already exists.", 2)
    except OSError:
        output.error("Error: Could not write HTML report.", 1)


def report_cmd(bundle_dir: Path, out_file: Path | None = None) -> None:
    """Render a checksum-validated migration bundle as offline HTML."""
    bundle = _read_bundle(bundle_dir)
    model = from_bundle(bundle, generated_at=datetime.now(UTC))
    content = render_report(model)
    if out_file is None:
        typer.echo(content, nl=False)
    else:
        _write_report(out_file, content)
