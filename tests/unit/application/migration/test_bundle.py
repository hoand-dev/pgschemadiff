import inspect
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest

from pgschemadiff.application.migration.bundle import ValidatedBundle, load_bundle
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.model import MigrationPlan
from pgschemadiff.application.migration.ports import BundleReader
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta import (
    AddEnumValue,
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
from pgschemadiff.shared.errors import MigrationError

_CREATED_AT = datetime(2026, 10, 24, 12, 30, 45, tzinfo=UTC)
_Manifest = dict[str, object]
_Mutation = Callable[[_Manifest], None]


def _ref(kind: ObjectKind, namespace: str, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace=namespace, name=name))


@pytest.fixture
def rendered_bundle() -> tuple[MigrationPlan, bytes, bytes]:
    schema_ref = _ref(ObjectKind.SCHEMA, "public", "app")
    table_ref = _ref(ObjectKind.TABLE, "app", "accounts")
    index_ref = _ref(ObjectKind.INDEX, "app", "accounts_id_idx")
    table = Table(
        ref=table_ref,
        columns=(Column(name="id", position=1, data_type="integer", nullable=False),),
    )
    index = Index(
        ref=index_ref,
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(IndexKeyColumn(column_name="id"),),
        definition='CREATE INDEX "accounts_id_idx" ON "app"."accounts" USING btree ("id")',
    )
    deltas: tuple[DeltaBase, ...] = (
        CreateSchema(target=schema_ref, pg_schema=Schema(ref=schema_ref)),
        CreateTable(target=table_ref, table=table),
        CreateIndex(target=index_ref, index=index),
    )
    plan = generate_migration(
        DeltaSet.from_iterable(deltas),
        source_fingerprint="source-fingerprint",
        target_fingerprint="target-fingerprint",
        clock=lambda: _CREATED_AT,
        id_factory=lambda: "bundle-test-id",
    )
    files = dict(render_bundle(plan).files)
    return plan, files["manifest.json"], files["up.sql"]


def _object(value: object) -> _Manifest:
    assert isinstance(value, dict)
    return cast("_Manifest", value)


def _list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _manifest(rendered_bundle: tuple[MigrationPlan, bytes, bytes]) -> _Manifest:
    return _object(json.loads(rendered_bundle[1]))


def _units(manifest: _Manifest) -> list[object]:
    return _list(manifest["units"])


def _unit(manifest: _Manifest, index: int = 0) -> _Manifest:
    return _object(_units(manifest)[index])


def _statements(manifest: _Manifest, unit_index: int = 0) -> list[object]:
    return _list(_unit(manifest, unit_index)["statements"])


def _statement(manifest: _Manifest, statement_index: int = 0, unit_index: int = 0) -> _Manifest:
    return _object(_statements(manifest, unit_index)[statement_index])


def _manifest_bytes(manifest: _Manifest) -> bytes:
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _load_mutated(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], mutate: _Mutation
) -> ValidatedBundle:
    manifest = deepcopy(_manifest(rendered_bundle))
    mutate(manifest)
    return load_bundle(_manifest_bytes(manifest), rendered_bundle[2])


def _checksum_up_sql(manifest: _Manifest, up_sql: bytes) -> None:
    checksums = _object(manifest["checksums"])
    checksums["up_sql_sha256"] = sha256(up_sql).hexdigest()


def _invalid_format_version(manifest: _Manifest) -> None:
    manifest["format_version"] = 2


def _missing_top_level_field(manifest: _Manifest) -> None:
    del manifest["id"]


def _extra_top_level_field(manifest: _Manifest) -> None:
    manifest["unexpected"] = None


def _missing_checksum_field(manifest: _Manifest) -> None:
    del _object(manifest["checksums"])["up_sql_sha256"]


def _missing_assessment_field(manifest: _Manifest) -> None:
    del _object(_list(manifest["assessments"])[0])["reason"]


def _extra_unit_field(manifest: _Manifest) -> None:
    _unit(manifest)["unexpected"] = "value"


def _extra_statement_field(manifest: _Manifest) -> None:
    _statement(manifest)["unexpected"] = "value"


def _extra_checksums_field(manifest: _Manifest) -> None:
    _object(manifest["checksums"])["down_sql_sha256"] = "0" * 64


def _set_root_field(manifest: _Manifest, key: str, value: object) -> None:
    manifest[key] = value


def _set_assessment_field(manifest: _Manifest, key: str, value: object) -> None:
    _object(_list(manifest["assessments"])[0])[key] = value


def _set_unit_field(manifest: _Manifest, key: str, value: object) -> None:
    _unit(manifest)[key] = value


def _set_statement_field(manifest: _Manifest, key: str, value: object) -> None:
    _statement(manifest)[key] = value


_FieldSetter = Callable[[_Manifest, str, object], None]
_INVALID_FIELD_TYPES: dict[str, tuple[_FieldSetter, str, object]] = {
    "format_version": (_set_root_field, "format_version", True),
    "delta_count": (_set_root_field, "delta_count", True),
    "assessments": (_set_root_field, "assessments", None),
    "units": (_set_root_field, "units", {}),
    "source_fingerprint": (_set_root_field, "source_fingerprint", 7),
    "tool_version": (_set_root_field, "tool_version", 7),
    "overall_max_risk": (_set_root_field, "overall_max_risk", True),
    "reversible": (_set_assessment_field, "reversible", 0),
    "unit_index": (_set_unit_field, "index", True),
    "transactional": (_set_unit_field, "transactional", 1),
    "unit_max_risk": (_set_unit_field, "max_risk", 7),
    "unit_delta_ids": (_set_unit_field, "delta_ids", None),
    "statement_start": (_set_statement_field, "start_line", True),
    "statement_end": (_set_statement_field, "end_line", "8"),
    "unit_checksum": (_set_unit_field, "sql_sha256", True),
}


def _bad_manifest_field_type(manifest: _Manifest, field: str) -> None:
    setter, key, value = _INVALID_FIELD_TYPES[field]
    setter(manifest, key, value)


def _bad_up_checksum_format(manifest: _Manifest) -> None:
    _object(manifest["checksums"])["up_sql_sha256"] = "A" * 64


def _bad_unit_checksum_format(manifest: _Manifest) -> None:
    _unit(manifest)["sql_sha256"] = "not-a-sha256"


def _noncontiguous_unit_index(manifest: _Manifest) -> None:
    _unit(manifest, 1)["index"] = 2


def _reverse_statement_range(manifest: _Manifest) -> None:
    first = _statement(manifest)
    first["start_line"] = cast("int", first["end_line"]) + 1


def _overlap_statement_ranges(manifest: _Manifest) -> None:
    first, second = (_object(item) for item in _statements(manifest))
    first["end_line"] = second["start_line"]


def _range_outside_unit(manifest: _Manifest) -> None:
    unit = _unit(manifest)
    _statement(manifest)["start_line"] = cast("int", unit["start_line"]) - 1


def _range_out_of_bounds(manifest: _Manifest) -> None:
    statement = _statement(manifest, statement_index=0, unit_index=1)
    statement["end_line"] = 10_000


def _range_not_positive(manifest: _Manifest) -> None:
    _statement(manifest)["start_line"] = 0


def _unit_span_mismatch(manifest: _Manifest) -> None:
    unit = _unit(manifest)
    unit["start_line"] = cast("int", unit["start_line"]) + 1


def _unit_ranges_overlap(manifest: _Manifest) -> None:
    first, second = (_object(item) for item in _units(manifest))
    second["start_line"] = first["end_line"]


def _unknown_statement_delta_id(manifest: _Manifest) -> None:
    _statement(manifest)["delta_id"] = "d9999"


def _remove_statement_terminator(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> tuple[bytes, bytes]:
    manifest = _manifest(rendered_bundle)
    lines = rendered_bundle[2].decode("utf-8").split("\n")
    end_line = cast("int", _statement(manifest)["end_line"])
    lines[end_line] = "-- terminator removed"
    up_sql = "\n".join(lines).encode("utf-8")
    _checksum_up_sql(manifest, up_sql)
    return _manifest_bytes(manifest), up_sql


def _mismatched_unit_delta_ids(manifest: _Manifest) -> None:
    _unit(manifest)["delta_ids"] = ["d0003"]


def _unrepresented_assessment(manifest: _Manifest) -> None:
    _statement(manifest)["delta_id"] = "d0002"
    _unit(manifest)["delta_ids"] = ["d0002"]


def _mismatched_unit_risk(manifest: _Manifest) -> None:
    unit = _unit(manifest)
    unit["max_risk"] = next(level.value for level in RiskLevel if level.value != unit["max_risk"])


def _mismatched_overall_risk(manifest: _Manifest) -> None:
    current = manifest["overall_max_risk"]
    manifest["overall_max_risk"] = next(
        level.value for level in RiskLevel if level.value != current
    )


def _unknown_assessment_risk(manifest: _Manifest) -> None:
    _object(_list(manifest["assessments"])[0])["level"] = "extreme"


def _unknown_unit_risk(manifest: _Manifest) -> None:
    _unit(manifest)["max_risk"] = "extreme"


def _reversible_assessment(manifest: _Manifest) -> None:
    _object(_list(manifest["assessments"])[0])["reversible"] = True


def _blank_reversibility_reason(manifest: _Manifest) -> None:
    _object(_list(manifest["assessments"])[0])["reversibility_reason"] = "  "


def _wrong_delta_count(manifest: _Manifest) -> None:
    manifest["delta_count"] = cast("int", manifest["delta_count"]) + 1


def _wrong_assessment_id(manifest: _Manifest) -> None:
    _object(_list(manifest["assessments"])[0])["delta_id"] = "d0002"


def _mismatched_unit_checksum(manifest: _Manifest) -> None:
    _unit(manifest)["sql_sha256"] = sha256(b"different sql").hexdigest()


def _multiple_statement_nontransactional_unit(manifest: _Manifest) -> None:
    _unit(manifest)["transactional"] = False


def _reordered_statements(manifest: _Manifest) -> None:
    first, second = (_object(item) for item in _statements(manifest))
    first_start, first_end = first["start_line"], first["end_line"]
    first["start_line"], first["end_line"] = second["start_line"], second["end_line"]
    second["start_line"], second["end_line"] = first_start, first_end


def test_load_round_trips_rendered_plan_and_extracts_exact_statement_sql(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    plan, manifest_bytes, up_sql = rendered_bundle

    bundle = load_bundle(manifest_bytes, up_sql)

    expected_sql = [
        statement.sql for unit in plan.units for statement in unit.transaction_unit.statements
    ]
    actual_sql = [statement.sql for unit in bundle.units for statement in unit.statements]
    assert actual_sql == expected_sql
    assert bundle.id == plan.id
    assert bundle.delta_count == len(plan.delta_set)
    assert bundle.overall_max_risk is plan.overall_max_risk
    assert bundle.source_fingerprint == plan.source_fingerprint
    assert bundle.target_fingerprint == plan.target_fingerprint
    assert [unit.transactional for unit in bundle.units] == [
        unit.transaction_unit.transactional for unit in plan.units
    ]
    assert all(isinstance(unit.max_risk, RiskLevel) for unit in bundle.units)


def test_enum_addition_round_trips_as_an_isolated_transactional_bundle_unit() -> None:
    enum_ref = _ref(ObjectKind.ENUM, "app", "mood")
    delta = AddEnumValue(target=enum_ref, label="happy", after="okay")
    plan = generate_migration(
        DeltaSet.from_iterable((delta,)),
        clock=lambda: _CREATED_AT,
        id_factory=lambda: "enum-addition-bundle",
    )
    files = dict(render_bundle(plan).files)

    bundle = load_bundle(files["manifest.json"], files["up.sql"])

    assert len(plan.units) == len(bundle.units) == 1
    assert plan.units[0].transaction_unit.transactional is True
    assert bundle.units[0].transactional is True
    assert (
        bundle.units[0].statements[0].sql
        == "ALTER TYPE \"app\".\"mood\" ADD VALUE 'happy' AFTER 'okay'"
    )


def test_empty_bundle_round_trips_without_risk_or_units() -> None:
    plan = generate_migration(
        DeltaSet(),
        clock=lambda: _CREATED_AT,
        id_factory=lambda: "empty-bundle",
    )
    files = dict(render_bundle(plan).files)

    bundle = load_bundle(files["manifest.json"], files["up.sql"])

    assert bundle.assessments == ()
    assert bundle.units == ()
    assert bundle.overall_max_risk is None


def test_validated_bundle_is_frozen(rendered_bundle: tuple[MigrationPlan, bytes, bytes]) -> None:
    bundle = load_bundle(rendered_bundle[1], rendered_bundle[2])

    with pytest.raises(FrozenInstanceError):
        bundle.id = "changed"  # type: ignore[misc]


def test_bundle_reader_is_a_sync_structural_port() -> None:
    class StubReader:
        def read(self, _bundle_dir: Path) -> tuple[bytes, bytes]:
            return b"manifest", b"sql"

    reader: BundleReader = StubReader()
    assert isinstance(reader, BundleReader)
    assert not inspect.iscoroutinefunction(BundleReader.read)
    assert reader.read(Path("bundle")) == (b"manifest", b"sql")


@pytest.mark.parametrize(
    "part", [pytest.param("manifest", id="manifest"), pytest.param("up_sql", id="up-sql")]
)
def test_rejects_invalid_utf8(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], part: str
) -> None:
    manifest_bytes, up_sql = rendered_bundle[1:]
    if part == "manifest":
        manifest_bytes = b"\xff"
    else:
        up_sql = b"\xff"
        manifest = _manifest(rendered_bundle)
        _checksum_up_sql(manifest, up_sql)
        manifest_bytes = _manifest_bytes(manifest)

    with pytest.raises(MigrationError, match="UTF-8"):
        load_bundle(manifest_bytes, up_sql)


@pytest.mark.parametrize(
    "part", [pytest.param("manifest", id="manifest"), pytest.param("up_sql", id="up-sql")]
)
def test_rejects_non_bytes_inputs(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], part: str
) -> None:
    manifest_bytes: object = rendered_bundle[1]
    up_sql: object = rendered_bundle[2]
    if part == "manifest":
        manifest_bytes = "not bytes"
    else:
        up_sql = "not bytes"

    with pytest.raises(MigrationError):
        load_bundle(cast("bytes", manifest_bytes), cast("bytes", up_sql))


def test_rejects_duplicate_json_keys(rendered_bundle: tuple[MigrationPlan, bytes, bytes]) -> None:
    manifest_bytes = rendered_bundle[1].replace(
        b'  "format_version": 1,',
        b'  "format_version": 1,\n  "format_version": 1,',
        1,
    )
    assert manifest_bytes != rendered_bundle[1]

    with pytest.raises(MigrationError, match="duplicate"):
        load_bundle(manifest_bytes, rendered_bundle[2])


def test_rejects_invalid_json(rendered_bundle: tuple[MigrationPlan, bytes, bytes]) -> None:
    with pytest.raises(MigrationError):
        load_bundle(b"{", rendered_bundle[2])


def test_rejects_non_object_manifest_root(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    with pytest.raises(MigrationError, match="root"):
        load_bundle(b"[]", rendered_bundle[2])


def test_rejects_unknown_format_version(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    with pytest.raises(MigrationError, match="format_version"):
        _load_mutated(rendered_bundle, _invalid_format_version)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_missing_top_level_field, id="missing-top-level"),
        pytest.param(_extra_top_level_field, id="extra-top-level"),
        pytest.param(_missing_checksum_field, id="missing-checksum"),
        pytest.param(_missing_assessment_field, id="missing-assessment-field"),
        pytest.param(_extra_unit_field, id="extra-unit-field"),
        pytest.param(_extra_statement_field, id="extra-statement-field"),
        pytest.param(_extra_checksums_field, id="extra-checksum-field"),
    ],
)
def test_rejects_missing_or_extra_fields(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], mutate: _Mutation
) -> None:
    with pytest.raises(MigrationError):
        _load_mutated(rendered_bundle, mutate)


@pytest.mark.parametrize(
    "field",
    [
        pytest.param("format_version", id="format-version"),
        pytest.param("delta_count", id="delta-count"),
        pytest.param("assessments", id="assessments"),
        pytest.param("units", id="units"),
        pytest.param("source_fingerprint", id="source-fingerprint"),
        pytest.param("tool_version", id="tool-version"),
        pytest.param("overall_max_risk", id="overall-risk"),
        pytest.param("reversible", id="reversible"),
        pytest.param("unit_index", id="unit-index"),
        pytest.param("transactional", id="transactional"),
        pytest.param("unit_max_risk", id="unit-max-risk"),
        pytest.param("unit_delta_ids", id="unit-delta-ids"),
        pytest.param("statement_start", id="statement-start"),
        pytest.param("statement_end", id="statement-end"),
        pytest.param("unit_checksum", id="unit-checksum"),
    ],
)
def test_rejects_invalid_field_types(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], field: str
) -> None:
    def mutate(manifest: _Manifest) -> None:
        _bad_manifest_field_type(manifest, field)

    with pytest.raises(MigrationError):
        _load_mutated(rendered_bundle, mutate)


@pytest.mark.parametrize("mutate", [_bad_up_checksum_format, _bad_unit_checksum_format])
def test_rejects_malformed_sha256(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], mutate: _Mutation
) -> None:
    with pytest.raises(MigrationError, match="SHA-256"):
        _load_mutated(rendered_bundle, mutate)


def test_rejects_whole_file_checksum_mismatch(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    changed_sql = rendered_bundle[2].replace(
        b"-- pgschemadiff migration", b"-- xgschemadiff migration", 1
    )

    with pytest.raises(MigrationError, match=r"up\.sql"):
        load_bundle(rendered_bundle[1], changed_sql)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda up_sql: up_sql.replace(b"\n", b"\r\n"), id="crlf"),
        pytest.param(lambda up_sql: up_sql[:-1], id="missing-final-lf"),
        pytest.param(lambda up_sql: up_sql + b"\n", id="extra-final-lf"),
        pytest.param(lambda up_sql: b"\xef\xbb\xbf" + up_sql, id="utf8-bom"),
    ],
)
def test_rejects_noncanonical_up_sql(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
    change: Callable[[bytes], bytes],
) -> None:
    up_sql = change(rendered_bundle[2])
    manifest = _manifest(rendered_bundle)
    _checksum_up_sql(manifest, up_sql)

    with pytest.raises(MigrationError, match="canonical"):
        load_bundle(_manifest_bytes(manifest), up_sql)


def test_rejects_noncontiguous_unit_indexes(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    with pytest.raises(MigrationError, match="unit index"):
        _load_mutated(rendered_bundle, _noncontiguous_unit_index)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_reverse_statement_range, id="reversed"),
        pytest.param(_overlap_statement_ranges, id="statement-overlap"),
        pytest.param(_range_outside_unit, id="outside-unit"),
        pytest.param(_range_out_of_bounds, id="out-of-bounds"),
        pytest.param(_range_not_positive, id="not-positive"),
        pytest.param(_unit_span_mismatch, id="unit-span"),
        pytest.param(_unit_ranges_overlap, id="unit-overlap"),
        pytest.param(_reordered_statements, id="statement-order"),
    ],
)
def test_rejects_invalid_line_ranges(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], mutate: _Mutation
) -> None:
    with pytest.raises(MigrationError):
        _load_mutated(rendered_bundle, mutate)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_unknown_statement_delta_id, id="unknown-statement-delta"),
        pytest.param(_mismatched_unit_delta_ids, id="unit-delta-ids"),
        pytest.param(_unrepresented_assessment, id="unrepresented-assessment"),
    ],
)
def test_rejects_inconsistent_delta_ids(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], mutate: _Mutation
) -> None:
    with pytest.raises(MigrationError):
        _load_mutated(rendered_bundle, mutate)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_mismatched_unit_risk, id="unit-risk"),
        pytest.param(_mismatched_overall_risk, id="overall-risk"),
    ],
)
def test_rejects_inconsistent_risk_metadata(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], mutate: _Mutation
) -> None:
    with pytest.raises(MigrationError, match="risk"):
        _load_mutated(rendered_bundle, mutate)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_unknown_assessment_risk, id="unknown-assessment-risk"),
        pytest.param(_unknown_unit_risk, id="unknown-unit-risk"),
        pytest.param(_reversible_assessment, id="reversible-assessment"),
        pytest.param(_blank_reversibility_reason, id="blank-reversibility-reason"),
        pytest.param(_wrong_delta_count, id="delta-count"),
        pytest.param(_wrong_assessment_id, id="assessment-id"),
    ],
)
def test_rejects_invalid_assessment_or_risk_metadata(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes], mutate: _Mutation
) -> None:
    with pytest.raises(MigrationError):
        _load_mutated(rendered_bundle, mutate)


def test_rejects_unit_checksum_mismatch(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    with pytest.raises(MigrationError, match="SQL checksum"):
        _load_mutated(rendered_bundle, _mismatched_unit_checksum)


def test_rejects_missing_standalone_terminator_line(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    manifest_bytes, up_sql = _remove_statement_terminator(rendered_bundle)

    with pytest.raises(MigrationError, match="standalone"):
        load_bundle(manifest_bytes, up_sql)


def test_rejects_nontransactional_unit_with_multiple_statements(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    assert len(_statements(_manifest(rendered_bundle))) == 2

    with pytest.raises(MigrationError, match="non-transactional"):
        _load_mutated(rendered_bundle, _multiple_statement_nontransactional_unit)


def test_does_not_parse_statement_sql(
    rendered_bundle: tuple[MigrationPlan, bytes, bytes],
) -> None:
    manifest = _manifest(rendered_bundle)
    up_lines = rendered_bundle[2].decode("utf-8").split("\n")
    units = [_object(item) for item in _units(manifest)]
    first_statement = _object(_list(units[0]["statements"])[0])
    start = cast("int", first_statement["start_line"])
    end = cast("int", first_statement["end_line"])
    up_lines[start - 1 : end] = ["definitely not valid SQL"]
    up_sql = "\n".join(up_lines).encode("utf-8")

    for unit in units:
        statement_sql = []
        for item in _list(unit["statements"]):
            statement = _object(item)
            statement_start = cast("int", statement["start_line"])
            statement_end = cast("int", statement["end_line"])
            statement_sql.append("\n".join(up_lines[statement_start - 1 : statement_end]) + "\n")
        unit["sql_sha256"] = sha256("".join(statement_sql).encode("utf-8")).hexdigest()
    _checksum_up_sql(manifest, up_sql)

    bundle = load_bundle(_manifest_bytes(manifest), up_sql)

    assert bundle.units[0].statements[0].sql == "definitely not valid SQL"
