"""PostgreSQL integration coverage for migration source fingerprints."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from typer.testing import CliRunner

from pgschemadiff.application.diff.fingerprint import schema_fingerprint
from pgschemadiff.presentation import composition
from pgschemadiff.presentation.cli.main import app

pytestmark = pytest.mark.integration
runner = CliRunner()


def _seed_schema(dsn: str, schema_name: str, *, include_label: bool) -> None:
    label_column = sql.SQL(", label text") if include_label else sql.SQL("")
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(
            sql.SQL("CREATE TABLE {}.items (id integer PRIMARY KEY{})").format(
                sql.Identifier(schema_name), label_column
            )
        )


async def _fingerprints_for_repeated_inspection(dsn: str, schema_name: str) -> tuple[str, str]:
    async with composition.open_inspector(dsn, schemas=[schema_name]) as inspector:
        first = schema_fingerprint(await inspector.inspect())
        second = schema_fingerprint(await inspector.inspect())
    return first, second


async def _fingerprint(dsn: str, schema_name: str) -> str:
    async with composition.open_inspector(dsn, schemas=[schema_name]) as inspector:
        return schema_fingerprint(await inspector.inspect())


def test_source_guard_rejects_wrong_database_then_applies_and_verifies(
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    schema_name = f"guard_{uuid.uuid4().hex[:10]}"
    _seed_schema(pg_test_dsn, schema_name, include_label=False)
    _seed_schema(pg_test_dsn2, schema_name, include_label=True)

    generated = runner.invoke(
        app,
        [
            "generate",
            pg_test_dsn,
            pg_test_dsn2,
            "--out",
            str(tmp_path),
            "--schema",
            schema_name,
        ],
    )
    assert generated.exit_code == 0, generated.output
    bundle_dir = Path(generated.stdout.strip())

    wrong_target = runner.invoke(app, ["apply", str(bundle_dir), pg_test_dsn2, "--yes"])
    assert wrong_target.exit_code == 2, wrong_target.output
    assert "Database schema does not match the bundle's source state" in wrong_target.stderr

    source_apply = runner.invoke(app, ["apply", str(bundle_dir), pg_test_dsn, "--yes"])
    assert source_apply.exit_code == 0, source_apply.output
    assert "Verified: database now matches the desired schema." in source_apply.stdout


def test_fingerprint_is_stable_and_ignores_database_name(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    schema_name = f"fingerprint_{uuid.uuid4().hex[:10]}"
    _seed_schema(pg_test_dsn, schema_name, include_label=True)
    _seed_schema(pg_test_dsn2, schema_name, include_label=True)

    first, repeated = asyncio.run(_fingerprints_for_repeated_inspection(pg_test_dsn, schema_name))
    other_database = asyncio.run(_fingerprint(pg_test_dsn2, schema_name))

    assert first == repeated
    assert first == other_database
