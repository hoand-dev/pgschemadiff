import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version

import pytest
from syrupy.assertion import SnapshotAssertion

from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.model import MigrationPlan
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.application.sql_emit.emitter import SqlStatement
from pgschemadiff.application.sql_emit.transaction import TransactionUnit
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import PrimaryKeyConstraint
from pgschemadiff.domain.delta import (
    AddConstraint,
    CreateIndex,
    CreateSchema,
    CreateTable,
    DeltaBase,
    DeltaSet,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table

_CREATED_AT = datetime(2026, 10, 24, 12, 30, 45, tzinfo=UTC)


def _ref(kind: ObjectKind, namespace: str, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace=namespace, name=name))


def _plan(*, realistic: bool) -> MigrationPlan:
    deltas: list[DeltaBase] = []
    if realistic:
        schema_ref = _ref(ObjectKind.SCHEMA, "public", "app")
        deltas.append(CreateSchema(target=schema_ref, pg_schema=Schema(ref=schema_ref)))

        table_ref = _ref(ObjectKind.TABLE, "app", "accounts")
        table = Table(
            ref=table_ref,
            columns=(
                Column(name="id", position=1, data_type="integer", nullable=False),
                Column(name="email", position=2, data_type="text", nullable=False),
            ),
        )
        deltas.append(CreateTable(target=table_ref, table=table))

        constraint = PrimaryKeyConstraint(
            name="accounts_pkey",
            columns=("id",),
            definition='PRIMARY KEY ("id")',
        )
        constraint_ref = ObjectRef(
            kind=ObjectKind.CONSTRAINT,
            qname=QualifiedName(namespace="app", name=constraint.name),
            parent=table_ref,
        )
        deltas.append(AddConstraint(target=constraint_ref, constraint=constraint))

        index_ref = _ref(ObjectKind.INDEX, "app", "accounts_email_idx")
        index = Index(
            ref=index_ref,
            table_ref=table_ref,
            method=IndexMethod.BTREE,
            key_columns=(IndexKeyColumn(column_name="email"),),
            definition=(
                'CREATE INDEX "accounts_email_idx" ON "app"."accounts" USING btree ("email")'
            ),
        )
        deltas.append(CreateIndex(target=index_ref, index=index))

    return generate_migration(
        DeltaSet.from_iterable(deltas),
        source_fingerprint="source-hash" if realistic else None,
        target_fingerprint="target-hash" if realistic else None,
        clock=lambda: _CREATED_AT,
        id_factory=lambda: "render-plan" if realistic else "empty-plan",
    )


@pytest.mark.parametrize(
    "realistic",
    [pytest.param(False, id="empty"), pytest.param(True, id="realistic")],
)
def test_render_bundle_snapshots_all_five_artifacts(
    realistic: bool,
    snapshot: SnapshotAssertion,
) -> None:
    bundle = render_bundle(_plan(realistic=realistic))

    assert bundle.dir_name == "20261024_123045_diff"
    assert tuple(name for name, _content in bundle.files) == (
        "up.sql",
        "down.sql",
        "manifest.json",
        "deltas.json",
        "README.md",
    )
    assert tuple((name, content.decode("utf-8")) for name, content in bundle.files) == snapshot


def test_deltas_json_matches_diff_cli_serialization() -> None:
    plan = _plan(realistic=True)

    content = dict(render_bundle(plan).files)["deltas.json"]

    assert content == (plan.delta_set.model_dump_json(indent=2) + "\n").encode("utf-8")


def test_manifest_ranges_and_checksums_match_up_sql() -> None:
    files = dict(render_bundle(_plan(realistic=True)).files)
    manifest = json.loads(files["manifest.json"])
    lines = files["up.sql"].decode("utf-8").splitlines()

    assert manifest["tool_version"] == version("pgschemadiff")
    assert manifest["checksums"]["up_sql_sha256"] == sha256(files["up.sql"]).hexdigest()
    for unit in manifest["units"]:
        statement_sql: list[bytes] = []
        assert unit["start_line"] == unit["statements"][0]["start_line"]
        assert unit["end_line"] == unit["statements"][-1]["end_line"]
        for statement in unit["statements"]:
            start = statement["start_line"]
            end = statement["end_line"]
            assert lines[start - 2] == f"-- delta: {statement['delta_id']}"
            statement_sql.append(("\n".join(lines[start - 1 : end]) + "\n").encode("utf-8"))
        assert unit["sql_sha256"] == sha256(b"".join(statement_sql)).hexdigest()


def test_up_sql_sets_session_and_wraps_transactional_units() -> None:
    files = dict(render_bundle(_plan(realistic=True)).files)
    manifest = json.loads(files["manifest.json"])
    lines = files["up.sql"].decode("utf-8").splitlines()

    assert next(line for line in lines if not line.startswith("--")) == (
        "SET standard_conforming_strings = on;"
    )
    for unit in manifest["units"]:
        for statement in unit["statements"]:
            assert lines[statement["end_line"]] == ";"
        header = (
            f"-- pgschemadiff unit: {unit['index']} "
            f"transactional={str(unit['transactional']).lower()} "
            f"max_risk={unit['max_risk']}"
        )
        header_line = lines.index(header)
        if unit["transactional"]:
            assert lines[header_line + 1] == "BEGIN;"
            assert lines[unit["end_line"] + 1] == "COMMIT;"
        else:
            assert lines[header_line + 1].startswith("-- delta: ")
            assert "BEGIN;" not in lines[header_line + 1 : unit["end_line"]]
            assert "COMMIT;" not in lines[header_line + 1 : unit["end_line"]]


def test_down_sql_has_only_irreversible_annotations() -> None:
    plan = _plan(realistic=True)
    content = dict(render_bundle(plan).files)["down.sql"]
    lines = content.decode("utf-8").splitlines()

    assert all(line.startswith("--") for line in lines)
    assert sum(" IRREVERSIBLE: " in line for line in lines) == len(plan.assessments)
    assert content.endswith(b"\n")
    assert not content.endswith(b"\n\n")


def test_rendered_text_files_use_utf8_lf_and_one_final_newline() -> None:
    for _name, content in render_bundle(_plan(realistic=True)).files:
        content.decode("utf-8")
        assert b"\r" not in content
        assert content.endswith(b"\n")
        assert not content.endswith(b"\n\n")


def test_readme_lists_checksums_and_rollback_warnings() -> None:
    files = dict(render_bundle(_plan(realistic=True)).files)
    readme = files["README.md"].decode("utf-8")

    for name in ("up.sql", "down.sql", "manifest.json", "deltas.json"):
        assert sha256(files[name]).hexdigest() in readme
    assert "INVALID index" in readme
    assert "non-transactional units cannot be rolled back" in readme.lower()


def test_sql_newlines_are_normalized_before_range_and_checksum_rendering() -> None:
    plan = _plan(realistic=True)
    first_unit = plan.units[0]
    first_statement, *other_statements = first_unit.transaction_unit.statements
    statement = SqlStatement(
        sql="SELECT 1;\r\nSELECT 2;\rSELECT 3;\n\n",
        transactional=True,
        delta=first_statement.delta,
    )
    unit = TransactionUnit(
        statements=(statement, *other_statements),
        transactional=first_unit.transaction_unit.transactional,
    )
    planned_unit = replace(first_unit, transaction_unit=unit)
    plan = replace(plan, units=(planned_unit, *plan.units[1:]))
    files = dict(render_bundle(plan).files)
    manifest = json.loads(files["manifest.json"])
    statement_range = manifest["units"][0]["statements"][0]
    lines = files["up.sql"].decode("utf-8").splitlines()

    sql = "\n".join(lines[statement_range["start_line"] - 1 : statement_range["end_line"]])
    assert sql == "SELECT 1;\nSELECT 2;\nSELECT 3;"
    remaining_sql = b"".join(
        (statement.sql.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n").encode(
            "utf-8"
        )
        for statement in other_statements
    )
    assert (
        manifest["units"][0]["sql_sha256"]
        == sha256((sql + "\n").encode("utf-8") + remaining_sql).hexdigest()
    )
