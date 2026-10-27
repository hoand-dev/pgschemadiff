"""PG18 generate/apply round-trip acceptance tests.

``compare_urls(source_url, target_url)`` compares current source to desired
target. Generated bundles therefore apply to the initially-empty source
database to make it converge with the seeded desired database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from typer.testing import CliRunner

from pgschemadiff.application.migration.apply import apply_migration
from pgschemadiff.application.migration.bundle import load_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.infrastructure.postgres.applier import open_executor
from pgschemadiff.presentation.cli.commands.diff import compare_urls
from pgschemadiff.presentation.cli.main import app
from pgschemadiff.shared.errors import ApplyMigrationError
from tests.integration._plans import generate_test_migration


def _seed_desired_schema(dsn: str) -> None:
    """Create the supported two-table schema used by both round trips."""
    with psycopg.connect(dsn) as connection:
        connection.execute("CREATE SCHEMA app")
        connection.execute(
            """
            CREATE TABLE app.accounts (
                id bigint NOT NULL,
                code text NOT NULL,
                name text NOT NULL DEFAULT 'unknown',
                CONSTRAINT accounts_pkey PRIMARY KEY (id),
                CONSTRAINT accounts_code_key UNIQUE (code),
                CONSTRAINT accounts_name_check CHECK (char_length(name) > 0)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE app.orders (
                id bigint NOT NULL,
                account_id bigint NOT NULL,
                amount bigint NOT NULL DEFAULT 0,
                CONSTRAINT orders_pkey PRIMARY KEY (id),
                CONSTRAINT orders_account_id_fkey
                    FOREIGN KEY (account_id) REFERENCES app.accounts (id)
            )
            """
        )
        connection.execute("CREATE INDEX orders_amount_idx ON app.orders USING btree (amount)")


@pytest.mark.integration
async def test_api_round_trip_applies_bundle_and_rejects_repeat(
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    """Apply generated changes to current source and converge with desired."""
    _seed_desired_schema(pg_test_dsn2)

    delta_set = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)
    assert not delta_set.is_empty()

    plan = generate_test_migration(
        delta_set,
        max_risk=RiskLevel.DANGEROUS,
        clock=lambda: datetime(2026, 10, 24, 12, 30, 45, tzinfo=UTC),
        id_factory=lambda: "pg18-api-round-trip",
    )
    bundle_dir = FilesystemMigrationWriter().write(plan, tmp_path)
    manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    bundle = load_bundle(manifest_bytes, up_sql_bytes)

    assert any(unit.transactional for unit in bundle.units)
    assert any(
        not unit.transactional and "CREATE INDEX CONCURRENTLY" in unit.statements[0].sql.upper()
        for unit in bundle.units
    )

    async with open_executor(pg_test_dsn) as executor:
        result = await apply_migration(bundle, executor, approve_destructive=False)
        assert result.status == "applied"
        with pytest.raises(ApplyMigrationError, match="already been applied"):
            await apply_migration(bundle, executor, approve_destructive=False)

    remaining = await compare_urls(pg_test_dsn, pg_test_dsn2, schemas=None)
    assert remaining.is_empty()


@pytest.mark.integration
def test_cli_round_trip_redacts_password_and_reports_empty_diff(
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    """Generate, apply, and diff through the CLI using real PG18 databases."""
    _seed_desired_schema(pg_test_dsn2)
    runner = CliRunner()

    generated = runner.invoke(
        app,
        ["generate", pg_test_dsn, pg_test_dsn2, "--out", str(tmp_path)],
    )
    assert generated.exit_code == 0, generated.output
    bundle_lines = generated.stdout.splitlines()
    assert len(bundle_lines) == 1
    bundle_dir = Path(bundle_lines[0])
    assert bundle_dir.is_dir()

    applied = runner.invoke(app, ["apply", str(bundle_dir), pg_test_dsn])
    assert applied.exit_code == 0, applied.output

    diffed = runner.invoke(app, ["diff", pg_test_dsn, pg_test_dsn2])
    assert diffed.exit_code == 0, diffed.output
    assert json.loads(diffed.stdout) == {"deltas": []}

    # Check the credential fragment, not the bare password: the default
    # Testcontainers password ("test") also occurs in pytest tmp paths.
    secrets = tuple(
        secret
        for dsn in (pg_test_dsn, pg_test_dsn2)
        for secret in (dsn, f"{urlsplit(dsn).username}:{urlsplit(dsn).password}@")
    )
    assert urlsplit(pg_test_dsn).password
    assert all(
        secret not in result.output for result in (generated, applied, diffed) for secret in secrets
    ), "CLI output exposed database credentials"
