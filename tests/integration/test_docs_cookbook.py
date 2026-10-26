"""Executable checks for the SQL and CLI output in the migration cookbook."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from pgschemadiff.presentation.cli.main import app
from tests import docs_cookbook

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
COOKBOOK_ROOT = ROOT / "docs" / "guide" / "cookbook"
runner = CliRunner()


def _normalize_output(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines()).strip()


def _seed_database(dsn: str, script: str) -> None:
    # ponytail: cookbook SQL has no semicolons inside literals; add a SQL script parser if it does.
    with psycopg.connect(dsn) as connection:
        for statement in script.split(";"):
            if statement.strip():
                connection.execute(statement)


@pytest.mark.parametrize(
    "recipe_path",
    docs_cookbook.recipe_paths(COOKBOOK_ROOT),
    ids=lambda path: path.stem,
)
def test_cookbook_recipe_matches_cli_and_applies(
    recipe_path: Path,
    pg_test_dsn: str,
    pg_test_dsn2: str,
    tmp_path: Path,
) -> None:
    blocks = docs_cookbook.validate_recipe(recipe_path)
    _seed_database(pg_test_dsn, blocks["sql current"][0])
    _seed_database(pg_test_dsn2, blocks["sql desired"][0])

    renames_path: Path | None = None
    rename_blocks = blocks.get("yaml renames", [])
    assert len(rename_blocks) <= 1, recipe_path
    if rename_blocks:
        renames_path = tmp_path / "renames.yaml"
        renames_path.write_text(rename_blocks[0], encoding="utf-8")

    diff_args = ["diff", pg_test_dsn, pg_test_dsn2, "--format", "summary"]
    generate_args = [
        "generate",
        pg_test_dsn,
        pg_test_dsn2,
        "--out",
        str(tmp_path),
        "--max-risk",
        "destructive",
    ]
    if renames_path is not None:
        diff_args.extend(("--renames", str(renames_path)))
        generate_args.extend(("--renames", str(renames_path)))

    diff_result = runner.invoke(app, diff_args)
    assert diff_result.exit_code == 0, diff_result.output
    assert _normalize_output(diff_result.stdout) == _normalize_output(blocks["text summary"][0])

    generate_result = runner.invoke(app, generate_args)
    assert generate_result.exit_code == 0, generate_result.output
    bundle_path = Path(generate_result.stdout.strip())
    up_sql = (bundle_path / "up.sql").read_text(encoding="utf-8")
    # Excerpt statements may land in different units, so check line by line.
    for excerpt in blocks.get("sql up", []):
        for line in filter(None, (line.strip() for line in excerpt.splitlines())):
            assert line in up_sql, f"{recipe_path}: missing SQL excerpt line {line!r}"

    apply_result = runner.invoke(
        app,
        ["apply", str(bundle_path), pg_test_dsn, "--yes"],
    )
    assert apply_result.exit_code == 0, apply_result.output

    # Renamed objects no longer exist under their old names, so no --renames.
    final_result = runner.invoke(app, diff_args[:5])
    assert final_result.exit_code == 0, final_result.output
    assert _normalize_output(final_result.stdout) == "No schema changes."
