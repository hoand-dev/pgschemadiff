from dataclasses import FrozenInstanceError

import pytest

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import CheckConstraint, PrimaryKeyConstraint
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.function import Function
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import Table
from pgschemadiff.domain.view import View
from tests.benchmark.workload import BenchWorkload, build_snapshots, count_objects, seed_sql


def _ref(kind: ObjectKind, name: str) -> ObjectRef:
    return ObjectRef(
        kind=kind,
        qname=QualifiedName(namespace="bench", name=name),
        arg_signature=() if kind is ObjectKind.FUNCTION else None,
    )


def test_count_objects_counts_schema_members_and_nested_objects() -> None:
    table_ref = _ref(ObjectKind.TABLE, "t0000")
    table = Table(
        ref=table_ref,
        columns=(
            Column(name="id", position=1, data_type="integer", nullable=False),
            Column(name="value", position=2, data_type="text"),
        ),
        constraints=(
            PrimaryKeyConstraint(name="t0000_pkey", columns=("id",)),
            CheckConstraint(name="t0000_check", expression="id >= 0"),
        ),
    )
    index = Index(
        ref=_ref(ObjectKind.INDEX, "t0000_idx"),
        table_ref=table_ref,
        key_columns=(IndexKeyColumn(column_name="value"),),
    )
    view = View(
        ref=_ref(ObjectKind.VIEW, "v0000"),
        columns=(("id", "integer"),),
        definition="SELECT id FROM bench.t0000",
    )
    function = Function(
        ref=_ref(ObjectKind.FUNCTION, "f0000"),
        return_type="integer",
        language="sql",
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=1,
        rows=0,
        body="SELECT 1",
    )
    sequence = Sequence(
        ref=_ref(ObjectKind.SEQUENCE, "s0000"),
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=100,
        cache=1,
        cycle=False,
    )
    schema = Schema(
        ref=_ref(ObjectKind.SCHEMA, "bench"),
        tables=(table,),
        indexes=(index,),
        views=(view,),
        functions=(function,),
        sequences=(sequence,),
    )

    assert count_objects(Database(name="tiny", schemas=(schema,))) == 9


def test_bench_workload_is_frozen() -> None:
    workload = BenchWorkload(tables=20)

    with pytest.raises(FrozenInstanceError):
        workload.tables = 10  # type: ignore[misc]


def test_build_snapshots_apply_configured_differences() -> None:
    workload = BenchWorkload(tables=20, views=4, functions=4, sequences=2)

    source, target = build_snapshots(workload)

    assert len(source.schemas[0].tables) == len(target.schemas[0].tables) == 20
    assert count_objects(source) == 315
    assert count_objects(target) == 310
    source_table = source.table_by_qname(QualifiedName(namespace="bench", name="t0001"))
    target_table = target.table_by_qname(QualifiedName(namespace="bench", name="t0001"))
    assert source_table is not None
    assert target_table is not None
    assert source_table.columns[-1].name == "c10"
    assert source_table.columns[1].data_type == "bigint"
    assert target_table.columns[1].data_type == "integer"
    assert source_table.constraints[0].definition == "PRIMARY KEY (id)"
    assert source_table.constraints[1].definition == "CHECK (c01 >= 0)"
    source_index = next(
        index for index in source.schemas[0].indexes if index.ref.qname.name == "t0001_idx"
    )
    target_index = next(
        index for index in target.schemas[0].indexes if index.ref.qname.name == "t0001_idx"
    )
    assert source_index.key_columns[0].column_name == "c02"
    assert target_index.key_columns[0].column_name == "c01"
    assert source.schemas[0].views[0].definition != target.schemas[0].views[0].definition
    assert source.schemas[0].functions[0].body != target.schemas[0].functions[0].body


def test_seed_sql_creates_expected_table_counts_for_both_sides() -> None:
    workload = BenchWorkload(tables=20, views=4, functions=4, sequences=2)

    source_sql = seed_sql(workload, "source")
    target_sql = seed_sql(workload, "target")

    assert "FOR i IN 0..19 LOOP" in source_sql
    assert "FOR i IN 1..20 LOOP" in target_sql
    assert source_sql.count("CREATE TABLE") == target_sql.count("CREATE TABLE") == 1
    assert source_sql != target_sql
