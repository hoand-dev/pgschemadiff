import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from pgschemadiff.application.diff.compare_schemas import (
    SchemaComparisonResult,
    compare_schemas_with_snapshots,
)
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.database import Database
from tests.benchmark.workload import BenchWorkload, build_snapshots, count_objects


class _SnapshotInspector:
    def __init__(self, snapshot: Database) -> None:
        self._snapshot = snapshot

    async def inspect(self) -> Database:
        return self._snapshot


def _run_pipeline(source: Database, target: Database) -> SchemaComparisonResult:
    comparison = asyncio.run(
        compare_schemas_with_snapshots(
            _SnapshotInspector(source),
            _SnapshotInspector(target),
        )
    )
    plan = generate_migration(
        comparison.deltas,
        max_risk=RiskLevel.DESTRUCTIVE,
        clock=lambda: datetime(2026, 10, 26, tzinfo=UTC),
        id_factory=lambda: "bench-pipeline",
    )
    render_bundle(plan)
    return comparison


@pytest.mark.benchmark
def test_in_memory_pipeline_at_ten_thousand_objects(benchmark: Any) -> None:
    workload = BenchWorkload()
    source, target = build_snapshots(workload)
    assert count_objects(source) >= 10_000

    comparison = _run_pipeline(source, target)
    minimum_deltas, maximum_deltas = workload.delta_window
    assert minimum_deltas <= len(comparison.deltas) <= maximum_deltas

    benchmark.pedantic(lambda: _run_pipeline(source, target), rounds=3, iterations=1)
    assert benchmark.stats is not None
    assert benchmark.stats["max"] < 10.0
