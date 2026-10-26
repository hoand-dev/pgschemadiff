import asyncio
from time import perf_counter

import psycopg
import pytest

from pgschemadiff.application.diff.compare_schemas import (
    SchemaComparisonResult,
    compare_schemas_with_snapshots,
)
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.ports import SchemaInspector
from pgschemadiff.presentation.composition import open_inspectors
from tests.benchmark.workload import BenchWorkload, count_objects, seed_sql


class _TimingInspector:
    def __init__(self, inspector: SchemaInspector) -> None:
        self._inspector = inspector
        self.elapsed = 0.0

    async def inspect(self) -> Database:
        started = perf_counter()
        try:
            return await self._inspector.inspect()
        finally:
            self.elapsed += perf_counter() - started


@pytest.mark.benchmark
@pytest.mark.integration
def test_postgres_pipeline_at_ten_thousand_objects(
    pg_test_dsn: str,
    pg_test_dsn2: str,
) -> None:
    workload = BenchWorkload()
    with psycopg.connect(pg_test_dsn, autocommit=True) as connection:
        connection.execute(seed_sql(workload, "source"))
    with psycopg.connect(pg_test_dsn2, autocommit=True) as connection:
        connection.execute(seed_sql(workload, "target"))

    async def measure() -> tuple[
        SchemaComparisonResult,
        float,
        float,
        float,
        float,
        float,
        float,
    ]:
        started = perf_counter()
        async with open_inspectors(
            pg_test_dsn,
            pg_test_dsn2,
            schemas=[workload.schema],
        ) as (source_inspector, target_inspector):
            timed_source = _TimingInspector(source_inspector)
            timed_target = _TimingInspector(target_inspector)
            compare_started = perf_counter()
            comparison = await compare_schemas_with_snapshots(timed_source, timed_target)
            compare_elapsed = perf_counter() - compare_started
            diff_and_order = compare_elapsed - timed_source.elapsed - timed_target.elapsed

            generate_started = perf_counter()
            plan = generate_migration(
                comparison.deltas,
                max_risk=RiskLevel.DESTRUCTIVE,
                id_factory=lambda: "bench-e2e",
            )
            generate_elapsed = perf_counter() - generate_started

            render_started = perf_counter()
            render_bundle(plan)
            render_elapsed = perf_counter() - render_started
            total_elapsed = perf_counter() - started
            return (
                comparison,
                timed_source.elapsed,
                timed_target.elapsed,
                diff_and_order,
                generate_elapsed,
                render_elapsed,
                total_elapsed,
            )

    (
        comparison,
        inspect_source,
        inspect_target,
        diff_and_order,
        generate_elapsed,
        render_elapsed,
        total,
    ) = asyncio.run(measure())
    objects = count_objects(comparison.source)
    deltas = len(comparison.deltas)
    minimum_deltas, maximum_deltas = workload.delta_window

    print(
        f"bench e2e objects={objects} deltas={deltas} "
        f"inspect_source={inspect_source:.3f}s inspect_target={inspect_target:.3f}s "
        f"diff_and_order={diff_and_order:.3f}s generate={generate_elapsed:.3f}s "
        f"render={render_elapsed:.3f}s total={total:.3f}s"
    )
    assert objects >= 10_000
    assert minimum_deltas <= deltas <= maximum_deltas
    assert total < 10.0
