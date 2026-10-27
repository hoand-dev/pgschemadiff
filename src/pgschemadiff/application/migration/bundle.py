"""Load and validate immutable migration bundles from in-memory bytes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.shared.errors import MigrationError

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_RISK_LEVELS = tuple(RiskLevel)


@dataclass(frozen=True)
class BundleAssessment:
    """Validated risk and rollback metadata for one bundle delta."""

    delta_id: str
    kind: str
    target: str
    level: RiskLevel
    reason: str
    reversible: bool
    reversibility_reason: str


@dataclass(frozen=True)
class BundleStatement:
    """One SQL statement extracted from its manifest-declared line range."""

    delta_id: str
    start_line: int
    end_line: int
    sql: str


@dataclass(frozen=True)
class BundleUnit:
    """A validated ordered transaction unit from a migration bundle."""

    index: int
    transactional: bool
    start_line: int
    end_line: int
    max_risk: RiskLevel
    delta_ids: tuple[str, ...]
    statements: tuple[BundleStatement, ...]
    sql_sha256: str


@dataclass(frozen=True)
class ValidatedBundle:
    """Immutable migration bundle metadata and SQL ranges ready for application."""

    format_version: int
    tool_version: str
    id: str
    slug: str
    created_at: str
    source_fingerprint: str | None
    target_fingerprint: str | None
    delta_count: int
    overall_max_risk: RiskLevel | None
    assessments: tuple[BundleAssessment, ...]
    units: tuple[BundleUnit, ...]
    up_sql_sha256: str
    inspected_schemas: tuple[str, ...] | None = None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError(f"Migration manifest contains duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _require_object(value: object, fields: frozenset[str], context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MigrationError(f"Migration manifest {context} must be an object.")
    result = cast("dict[str, object]", value)
    missing = fields - result.keys()
    extra = result.keys() - fields
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unexpected fields: {', '.join(sorted(extra))}")
        raise MigrationError(f"Migration manifest {context} has {'; '.join(details)}.")
    return result


def _require_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise MigrationError(f"Migration manifest {context} must be an array.")
    return cast("list[object]", value)


def _require_string(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise MigrationError(f"Migration manifest {context} must be a string.")
    return value


def _require_optional_string(value: object, context: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, context)


def _require_int(value: object, context: str) -> int:
    if type(value) is not int:
        raise MigrationError(f"Migration manifest {context} must be an integer.")
    return value


def _require_bool(value: object, context: str) -> bool:
    if type(value) is not bool:
        raise MigrationError(f"Migration manifest {context} must be a boolean.")
    return value


def _require_risk(value: object, context: str) -> RiskLevel:
    if not isinstance(value, str):
        raise MigrationError(f"Migration manifest {context} must be a known risk level.")
    try:
        return RiskLevel(value)
    except ValueError as error:
        raise MigrationError(f"Migration manifest {context} has unknown risk level.") from error


def _require_sha256(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise MigrationError(f"Migration manifest {context} must be a lowercase SHA-256 value.")
    return value


def _require_fingerprint(value: object, context: str) -> str:
    if not isinstance(value, str) or _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise MigrationError(f"Migration manifest {context} must be a sha256 fingerprint.")
    return value


def _load_manifest(manifest_bytes: bytes) -> dict[str, object]:
    try:
        manifest_text = manifest_bytes.decode("utf-8", errors="strict")
        parsed: object = json.loads(manifest_text, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise MigrationError("Migration manifest must be strict UTF-8 JSON.") from error
    if not isinstance(parsed, dict):
        raise MigrationError("Migration manifest root must be an object.")
    return cast("dict[str, object]", parsed)


def _load_assessments(value: object) -> tuple[BundleAssessment, ...]:
    fields = frozenset(
        {
            "delta_id",
            "kind",
            "target",
            "level",
            "reason",
            "reversible",
            "reversibility_reason",
        }
    )
    assessments: list[BundleAssessment] = []
    for index, entry in enumerate(_require_list(value, "assessments"), start=1):
        context = f"assessment {index - 1}"
        item = _require_object(entry, fields, context)
        delta_id = _require_string(item["delta_id"], f"{context}.delta_id")
        if delta_id != f"d{index:04d}":
            raise MigrationError("Migration assessment delta IDs must be unique and ordered.")
        reversible = _require_bool(item["reversible"], f"{context}.reversible")
        reversibility_reason = _require_string(
            item["reversibility_reason"], f"{context}.reversibility_reason"
        )
        if reversible or not reversibility_reason.strip():
            raise MigrationError(
                "Migration assessments must declare irreversible deltas and a reason."
            )
        assessments.append(
            BundleAssessment(
                delta_id=delta_id,
                kind=_require_string(item["kind"], f"{context}.kind"),
                target=_require_string(item["target"], f"{context}.target"),
                level=_require_risk(item["level"], f"{context}.level"),
                reason=_require_string(item["reason"], f"{context}.reason"),
                reversible=reversible,
                reversibility_reason=reversibility_reason,
            )
        )
    return tuple(assessments)


def _line_range(
    start_value: object,
    end_value: object,
    *,
    context: str,
    line_count: int,
) -> tuple[int, int]:
    start_line = _require_int(start_value, f"{context}.start_line")
    end_line = _require_int(end_value, f"{context}.end_line")
    if start_line < 1 or end_line < start_line or end_line > line_count:
        raise MigrationError(f"Migration manifest {context} has an invalid line range.")
    return start_line, end_line


def _load_statements(
    value: object,
    *,
    unit_index: int,
    unit_range: tuple[int, int],
    lines: tuple[str, ...],
    assessments_by_id: dict[str, BundleAssessment],
) -> tuple[BundleStatement, ...]:
    statement_fields = frozenset({"delta_id", "start_line", "end_line"})
    statement_entries = _require_list(value, f"unit {unit_index}.statements")
    if not statement_entries:
        raise MigrationError("Migration units must contain at least one statement.")

    statements: list[BundleStatement] = []
    previous_statement_end = 0
    for statement_index, statement_entry in enumerate(statement_entries):
        context = f"unit {unit_index} statement {statement_index}"
        item = _require_object(statement_entry, statement_fields, context)
        delta_id = _require_string(item["delta_id"], f"{context}.delta_id")
        if delta_id not in assessments_by_id:
            raise MigrationError(f"Migration statement references unknown delta ID {delta_id!r}.")
        start_line, end_line = _line_range(
            item["start_line"],
            item["end_line"],
            context=context,
            line_count=len(lines),
        )
        if start_line <= previous_statement_end:
            raise MigrationError(
                "Migration statement line ranges must be ordered and non-overlapping."
            )
        if start_line < unit_range[0] or end_line > unit_range[1]:
            raise MigrationError(
                f"Migration statement range in unit {unit_index} is not contained."
            )
        if end_line >= len(lines) or lines[end_line] != ";":
            raise MigrationError(
                "Migration statement range must be followed by a standalone ';' line."
            )
        statements.append(
            BundleStatement(
                delta_id=delta_id,
                start_line=start_line,
                end_line=end_line,
                sql="\n".join(lines[start_line - 1 : end_line]),
            )
        )
        previous_statement_end = end_line
    return tuple(statements)


def _load_units(
    value: object,
    *,
    lines: tuple[str, ...],
    assessments: tuple[BundleAssessment, ...],
) -> tuple[BundleUnit, ...]:
    fields = frozenset(
        {
            "index",
            "transactional",
            "start_line",
            "end_line",
            "max_risk",
            "delta_ids",
            "statements",
            "sql_sha256",
        }
    )
    assessments_by_id = {assessment.delta_id: assessment for assessment in assessments}
    units: list[BundleUnit] = []
    represented_delta_ids: set[str] = set()
    previous_unit_end = 0

    for expected_index, entry in enumerate(_require_list(value, "units")):
        context = f"unit {expected_index}"
        item = _require_object(entry, fields, context)
        unit_index = _require_int(item["index"], f"{context}.index")
        if unit_index != expected_index:
            raise MigrationError("Migration unit indexes must be zero-based and contiguous.")
        transactional = _require_bool(item["transactional"], f"{context}.transactional")
        start_line, end_line = _line_range(
            item["start_line"],
            item["end_line"],
            context=context,
            line_count=len(lines),
        )
        if start_line <= previous_unit_end:
            raise MigrationError("Migration unit line ranges must be ordered and non-overlapping.")
        statements = _load_statements(
            item["statements"],
            unit_index=unit_index,
            unit_range=(start_line, end_line),
            lines=lines,
            assessments_by_id=assessments_by_id,
        )
        if start_line != statements[0].start_line or end_line != statements[-1].end_line:
            raise MigrationError("Migration unit range must span its first through last statement.")
        if not transactional and len(statements) != 1:
            raise MigrationError("A non-transactional migration unit must contain one statement.")

        delta_ids = tuple(
            _require_string(delta_id, f"{context}.delta_ids")
            for delta_id in _require_list(item["delta_ids"], f"{context}.delta_ids")
        )
        statement_delta_ids = tuple(dict.fromkeys(statement.delta_id for statement in statements))
        if delta_ids != statement_delta_ids:
            raise MigrationError(
                "Migration unit delta_ids must match ordered unique statement delta IDs."
            )

        max_risk = _require_risk(item["max_risk"], f"{context}.max_risk")
        expected_risk = max(
            (assessments_by_id[delta_id].level for delta_id in delta_ids),
            key=_RISK_LEVELS.index,
        )
        if max_risk is not expected_risk:
            raise MigrationError("Migration unit max_risk does not match linked assessments.")

        unit_checksum = _require_sha256(item["sql_sha256"], f"{context}.sql_sha256")
        statement_bytes = b"".join(
            (statement.sql + "\n").encode("utf-8") for statement in statements
        )
        if sha256(statement_bytes).hexdigest() != unit_checksum:
            raise MigrationError(f"Migration unit {expected_index} SQL checksum does not match.")

        represented_delta_ids.update(delta_ids)
        units.append(
            BundleUnit(
                index=unit_index,
                transactional=transactional,
                start_line=start_line,
                end_line=end_line,
                max_risk=max_risk,
                delta_ids=delta_ids,
                statements=statements,
                sql_sha256=unit_checksum,
            )
        )
        previous_unit_end = end_line

    if represented_delta_ids != set(assessments_by_id):
        raise MigrationError("Migration units must represent every assessment exactly by delta ID.")
    return tuple(units)


def load_bundle(manifest_bytes: bytes, up_sql_bytes: bytes) -> ValidatedBundle:
    """Validate a v1 bundle and extract statement SQL from its declared ranges."""
    if not isinstance(manifest_bytes, bytes) or not isinstance(up_sql_bytes, bytes):
        raise MigrationError("Migration manifest and up.sql must be supplied as bytes.")

    manifest = _load_manifest(manifest_bytes)
    format_version = _require_int(manifest.get("format_version"), "format_version")
    if format_version not in {1, 2}:
        raise MigrationError(f"Unsupported migration bundle format_version {format_version}.")

    fields = frozenset(
        {
            "format_version",
            "tool_version",
            "id",
            "slug",
            "created_at",
            "source_fingerprint",
            "target_fingerprint",
            "delta_count",
            "overall_max_risk",
            "assessments",
            "units",
            "checksums",
        }
    )
    if format_version == 2:
        fields = fields | {"inspected_schemas"}
    manifest = _require_object(manifest, fields, "root")

    tool_version = _require_string(manifest["tool_version"], "tool_version")
    bundle_id = _require_string(manifest["id"], "id")
    slug = _require_string(manifest["slug"], "slug")
    created_at = _require_string(manifest["created_at"], "created_at")
    if format_version == 1:
        source_fingerprint = _require_optional_string(
            manifest["source_fingerprint"], "source_fingerprint"
        )
        target_fingerprint = _require_optional_string(
            manifest["target_fingerprint"], "target_fingerprint"
        )
        inspected_schemas = None
    else:
        source_fingerprint = _require_fingerprint(
            manifest["source_fingerprint"], "source_fingerprint"
        )
        target_fingerprint = _require_fingerprint(
            manifest["target_fingerprint"], "target_fingerprint"
        )
        schemas_value = manifest["inspected_schemas"]
        inspected_schemas = (
            None
            if schemas_value is None
            else tuple(
                _require_string(schema, "inspected_schemas")
                for schema in _require_list(schemas_value, "inspected_schemas")
            )
        )
    delta_count = _require_int(manifest["delta_count"], "delta_count")
    if delta_count < 0:
        raise MigrationError("Migration manifest delta_count must not be negative.")

    assessments = _load_assessments(manifest["assessments"])
    if delta_count != len(assessments):
        raise MigrationError("Migration manifest delta_count does not match assessments.")
    overall_value = manifest["overall_max_risk"]
    overall_max_risk = (
        None if overall_value is None else _require_risk(overall_value, "overall_max_risk")
    )
    expected_overall = max(
        (assessment.level for assessment in assessments),
        key=_RISK_LEVELS.index,
        default=None,
    )
    if overall_max_risk is not expected_overall:
        raise MigrationError("Migration overall_max_risk does not match assessments.")

    checksums = _require_object(manifest["checksums"], frozenset({"up_sql_sha256"}), "checksums")
    up_sql_sha256 = _require_sha256(checksums["up_sql_sha256"], "checksums.up_sql_sha256")
    if sha256(up_sql_bytes).hexdigest() != up_sql_sha256:
        raise MigrationError("Migration up.sql checksum does not match.")

    try:
        up_sql_text = up_sql_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise MigrationError("Migration up.sql must be strict UTF-8.") from error
    if (
        up_sql_text.startswith("\ufeff")
        or "\r" in up_sql_text
        or not up_sql_text.endswith("\n")
        or up_sql_text.endswith("\n\n")
    ):
        raise MigrationError("Migration up.sql must use canonical LF with one final newline.")
    lines = tuple(up_sql_text[:-1].split("\n"))
    units = _load_units(manifest["units"], lines=lines, assessments=assessments)

    return ValidatedBundle(
        format_version=format_version,
        tool_version=tool_version,
        id=bundle_id,
        slug=slug,
        created_at=created_at,
        source_fingerprint=source_fingerprint,
        target_fingerprint=target_fingerprint,
        delta_count=delta_count,
        overall_max_risk=overall_max_risk,
        assessments=assessments,
        units=units,
        up_sql_sha256=up_sql_sha256,
        inspected_schemas=inspected_schemas,
    )
