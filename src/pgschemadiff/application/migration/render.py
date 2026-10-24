"""Pure rendering of migration plans into deterministic bundle files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from hashlib import sha256
from importlib.metadata import version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pgschemadiff.application.migration.model import MigrationPlan
    from pgschemadiff.application.sql_emit.emitter import SqlStatement
    from pgschemadiff.domain.delta import DeltaBase


@dataclass(frozen=True)
class RenderedBundle:
    """Ordered bundle filename and content pairs, ready for a filesystem adapter."""

    dir_name: str
    files: tuple[tuple[str, bytes], ...]


def _timestamp(plan: MigrationPlan) -> str:
    return plan.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _directory_name(plan: MigrationPlan) -> str:
    timestamp = plan.created_at.astimezone(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{plan.slug}"


def _normalize_sql(sql: str) -> str:
    return sql.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _statement_bytes(statement: SqlStatement) -> bytes:
    return (_normalize_sql(statement.sql) + "\n").encode("utf-8")


def _render_up(
    plan: MigrationPlan,
) -> tuple[bytes, list[dict[str, object]]]:
    lines = [
        f"-- pgschemadiff migration: {plan.id}",
        f"-- created_at: {_timestamp(plan)}",
        f"-- max_risk: {plan.overall_max_risk.value if plan.overall_max_risk else 'none'}",
        "SET standard_conforming_strings = on;",
    ]
    delta_id_by_identity = {
        id(record.assessment.delta): record.delta_id for record in plan.assessments
    }
    rendered_units: list[dict[str, object]] = []

    for planned_unit in plan.units:
        if rendered_units:
            lines.append("")
        unit = planned_unit.transaction_unit
        lines.append(
            f"-- pgschemadiff unit: {planned_unit.index} "
            f"transactional={str(unit.transactional).lower()} "
            f"max_risk={planned_unit.max_risk.value}"
        )
        if unit.transactional:
            lines.append("BEGIN;")

        statement_ranges: list[dict[str, str | int]] = []
        unit_sql: list[bytes] = []
        unit_start_line = 0
        unit_end_line = 0
        for statement in unit.statements:
            delta_id = delta_id_by_identity[id(statement.delta)]
            lines.append(f"-- delta: {delta_id}")
            sql_lines = _normalize_sql(statement.sql).split("\n")
            start_line = len(lines) + 1
            lines.extend(sql_lines)
            end_line = len(lines)
            if not statement_ranges:
                unit_start_line = start_line
            unit_end_line = end_line
            # Keep psql's terminator outside recorded SQL ranges and checksums.
            lines.append(";")
            statement_ranges.append(
                {"delta_id": delta_id, "start_line": start_line, "end_line": end_line}
            )
            unit_sql.append(_statement_bytes(statement))

        if unit.transactional:
            lines.append("COMMIT;")

        rendered_units.append(
            {
                "index": planned_unit.index,
                "transactional": unit.transactional,
                "start_line": unit_start_line,
                "end_line": unit_end_line,
                "max_risk": planned_unit.max_risk.value,
                "delta_ids": list(planned_unit.delta_ids),
                "statements": statement_ranges,
                "sql_sha256": sha256(b"".join(unit_sql)).hexdigest(),
            }
        )

    return ("\n".join(lines) + "\n").encode("utf-8"), rendered_units


def _render_down(plan: MigrationPlan) -> bytes:
    lines = [
        f"-- pgschemadiff rollback unavailable: {plan.id}",
        "-- MVP-A emits no inverse SQL; following entries are annotations only.",
    ]
    lines.extend(
        f"-- {record.delta_id} IRREVERSIBLE: {record.reversibility_reason}"
        for record in plan.assessments
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _target_label(delta: DeltaBase) -> str:
    if delta.target.parent is None:
        return delta.target.qname.fqn
    return f"{delta.target.parent.qname.fqn}.{delta.target.qname.name}"


def _render_manifest(
    plan: MigrationPlan,
    units: list[dict[str, object]],
    up_sql: bytes,
) -> bytes:
    manifest = {
        "format_version": 1,
        "tool_version": version("pgschemadiff"),
        "id": plan.id,
        "slug": plan.slug,
        "created_at": _timestamp(plan),
        "source_fingerprint": plan.source_fingerprint,
        "target_fingerprint": plan.target_fingerprint,
        "delta_count": len(plan.delta_set),
        "overall_max_risk": (
            plan.overall_max_risk.value if plan.overall_max_risk is not None else None
        ),
        "assessments": [
            {
                "delta_id": record.delta_id,
                "kind": record.assessment.delta.model_dump()["kind"],
                "target": _target_label(record.assessment.delta),
                "level": record.assessment.level.value,
                "reason": record.assessment.reason,
                "reversible": record.reversible,
                "reversibility_reason": record.reversibility_reason,
            }
            for record in plan.assessments
        ],
        "units": units,
        "checksums": {"up_sql_sha256": sha256(up_sql).hexdigest()},
    }
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _render_readme(plan: MigrationPlan, files: dict[str, bytes]) -> bytes:
    lines = [
        f"# Migration {plan.id}",
        "",
        f"- Created at: {_timestamp(plan)}",
    ]
    if plan.source_fingerprint is not None:
        lines.append(f"- Source fingerprint: `{plan.source_fingerprint}`")
    if plan.target_fingerprint is not None:
        lines.append(f"- Target fingerprint: `{plan.target_fingerprint}`")
    lines.extend(
        (
            f"- Delta count: {len(plan.delta_set)}",
            "- Overall max risk: "
            f"{plan.overall_max_risk.value if plan.overall_max_risk else 'none'}",
            "",
            "## Execution units",
            "",
            "| Unit | Transactional | Max risk | Delta IDs |",
            "|---:|:---:|---|---|",
        )
    )
    if plan.units:
        lines.extend(
            f"| {unit.index} | {str(unit.transaction_unit.transactional).lower()} "
            f"| {unit.max_risk.value} | {', '.join(unit.delta_ids)} |"
            for unit in plan.units
        )
    else:
        lines.append("| — | — | — | — |")
    lines.extend(
        (
            "",
            "## Files",
            "",
            "- `up.sql`",
            "- `down.sql`",
            "- `manifest.json`",
            "- `deltas.json`",
            "- `README.md`",
            "",
            "## SHA-256",
            "",
        )
    )
    lines.extend(
        f"- `{name}`: `{sha256(files[name]).hexdigest()}`"
        for name in ("up.sql", "down.sql", "manifest.json", "deltas.json")
    )
    lines.extend(
        (
            "",
            "## Warnings",
            "",
            "- Rollback SQL is unavailable; `down.sql` contains annotations only.",
            "- A failed `CREATE INDEX CONCURRENTLY` leaves an INVALID index; "
            "drop it before retrying.",
            "- Non-transactional units cannot be rolled back.",
        )
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_bundle(plan: MigrationPlan) -> RenderedBundle:
    """Render all bundle artifacts into ordered UTF-8 byte payloads."""
    up_sql, units = _render_up(plan)
    down_sql = _render_down(plan)
    deltas_json = (plan.delta_set.model_dump_json(indent=2) + "\n").encode("utf-8")
    files = {
        "up.sql": up_sql,
        "down.sql": down_sql,
        "deltas.json": deltas_json,
    }
    manifest_json = _render_manifest(plan, units, up_sql)
    files["manifest.json"] = manifest_json
    readme = _render_readme(plan, files)
    return RenderedBundle(
        dir_name=_directory_name(plan),
        files=(
            ("up.sql", up_sql),
            ("down.sql", down_sql),
            ("manifest.json", manifest_json),
            ("deltas.json", deltas_json),
            ("README.md", readme),
        ),
    )
