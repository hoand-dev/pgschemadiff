"""End-to-end coverage for reports generated from PostgreSQL bundles."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from typer.testing import CliRunner

from pgschemadiff.presentation.cli.main import app

pytestmark = pytest.mark.integration
runner = CliRunner()


def _seed_database(dsn: str, schema_name: str, *, include_email: bool) -> None:
    email_column = sql.SQL(", email text") if include_email else sql.SQL("")
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(
            sql.SQL("CREATE TABLE {}.accounts (id integer PRIMARY KEY{})").format(
                sql.Identifier(schema_name),
                email_column,
            )
        )


def test_report_renders_every_delta_from_a_generated_pg18_bundle(
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    schema_name = f"report_{uuid.uuid4().hex[:12]}"
    _seed_database(pg_test_dsn, schema_name, include_email=False)
    _seed_database(pg_test_dsn2, schema_name, include_email=True)

    generate_result = runner.invoke(
        app,
        [
            "generate",
            pg_test_dsn,
            pg_test_dsn2,
            "--out",
            str(tmp_path),
            "--schema",
            schema_name,
            "--max-risk",
            "destructive",
        ],
    )

    assert generate_result.exit_code == 0, generate_result.output
    bundle_dir = Path(generate_result.stdout.strip())
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))

    report_result = runner.invoke(app, ["report", str(bundle_dir)])

    assert report_result.exit_code == 0, report_result.output
    assert (
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
    ) in report_result.stdout
    for assessment in manifest["assessments"]:
        assert assessment["delta_id"] in report_result.stdout
