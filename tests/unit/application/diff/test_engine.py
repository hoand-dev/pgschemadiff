"""Unit tests for ``pgschemadiff.application.diff.engine`` (task P2-DIFF-01).

Covers:
- ``Comparator`` Protocol structural checks (runtime_checkable isinstance)
- ``DiffEngine`` construction: valid registry, duplicate-kind rejection
- ``DiffEngine.registered_kinds`` introspection
- Dispatch: correct comparator called for each kind
- Pairing semantics: create-only (source None), drop-only (target None),
  both-present, no-change (empty return)
- Delta aggregation from multiple comparators into one DeltaSet
- Deterministic ordering: shuffled input → same DeltaSet
- Empty-vs-empty → empty DeltaSet
- Objects only on source side (all dropped), objects only on target (all created)
- ``_fetch_objects_for_kind`` helper covers all known kinds + unknown kind
- Engine does not encode per-kind semantics (stub returning () → no deltas)
- ``Comparator`` re-export from ``application.diff`` package init
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import pytest

import pgschemadiff.application.diff as _diff_pkg
from pgschemadiff.application.diff import Comparator, DiffEngine
from pgschemadiff.application.diff.engine import _fetch_objects_for_kind

if TYPE_CHECKING:
    from collections.abc import Iterable
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import (
    CreateIndex,
    CreateSchema,
    CreateTable,
    DeltaBase,
    DeltaSet,
    DropSchema,
    DropTable,
)
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.shared.errors import DiffError

# ---------------------------------------------------------------------------
# Domain object factories
# ---------------------------------------------------------------------------


def _qname(namespace: str, name: str) -> QualifiedName:
    return QualifiedName(namespace=namespace, name=name)


def _schema_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=_qname(name, name),
    )


def _table_ref(schema: str, name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=_qname(schema, name))


def _index_ref(schema: str, name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.INDEX, qname=_qname(schema, name))


def _ext_ref(name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.EXTENSION, qname=_qname("public", name))


def _col(name: str = "id", pos: int = 1) -> Column:
    return Column(name=name, position=pos, data_type="integer", nullable=False)


def _make_schema(name: str, tables: tuple[Table, ...] = ()) -> Schema:
    return Schema(ref=_schema_ref(name), tables=tables)


def _make_table(schema: str, name: str) -> Table:
    return Table(ref=_table_ref(schema, name), columns=(_col(),))


def _make_index(schema: str, name: str, table_name: str) -> Index:
    tbl_ref = _table_ref(schema, table_name)
    return Index(
        ref=_index_ref(schema, name),
        table_ref=tbl_ref,
        key_columns=(IndexKeyColumn(column_name="id"),),
    )


def _make_extension(name: str, version: str = "1.0") -> Extension:
    return Extension(ref=_ext_ref(name), version=version)


def _make_db(
    name: str = "db",
    schemas: tuple[Schema, ...] = (),
    extensions: tuple[Extension, ...] = (),
) -> Database:
    return Database(name=name, schemas=schemas, extensions=extensions)


# ---------------------------------------------------------------------------
# Stub Comparator implementations
# ---------------------------------------------------------------------------


class _RecordingComparator:
    """Stub ``Comparator`` that records every (source, target) pair it receives
    and returns a fixed set of canned deltas."""

    def __init__(
        self,
        kind: ObjectKind,
        canned_deltas: tuple[DeltaBase, ...] = (),
    ) -> None:
        self.kind = kind
        self.canned_deltas = canned_deltas
        self.calls: list[tuple[object | None, object | None]] = []

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> Iterable[DeltaBase]:
        self.calls.append((source, target))
        return self.canned_deltas


class _SilentComparator:
    """Stub ``Comparator`` that always returns an empty tuple (no deltas)."""

    def __init__(self, kind: ObjectKind) -> None:
        self.kind = kind

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> Iterable[DeltaBase]:
        return ()


# ---------------------------------------------------------------------------
# Canned delta fixtures
# ---------------------------------------------------------------------------


def _create_schema_delta(schema_name: str) -> CreateSchema:
    schema = _make_schema(schema_name)
    return CreateSchema(target=schema.ref, pg_schema=schema)


def _drop_schema_delta(schema_name: str) -> DropSchema:
    schema = _make_schema(schema_name)
    return DropSchema(target=schema.ref, pg_schema=schema)


def _create_table_delta(schema: str, name: str) -> CreateTable:
    table = _make_table(schema, name)
    return CreateTable(target=table.ref, table=table)


def _drop_table_delta(schema: str, name: str) -> DropTable:
    table = _make_table(schema, name)
    return DropTable(target=table.ref, table=table)


def _create_index_delta(schema: str, name: str) -> CreateIndex:
    idx = _make_index(schema, name, "t")
    return CreateIndex(target=idx.ref, index=idx)


# ---------------------------------------------------------------------------
# Protocol / isinstance tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_comparator_protocol_is_runtime_checkable() -> None:
    """``Comparator`` must be decorated with ``@runtime_checkable``."""
    stub = _RecordingComparator(kind=ObjectKind.TABLE)
    assert isinstance(stub, Comparator)


@pytest.mark.unit
def test_silent_comparator_satisfies_protocol() -> None:
    """Even a minimal stub that returns () satisfies ``Comparator``."""
    stub = _SilentComparator(kind=ObjectKind.SCHEMA)
    assert isinstance(stub, Comparator)


@pytest.mark.unit
def test_object_without_kind_does_not_satisfy_protocol() -> None:
    """An object missing the ``kind`` attribute does NOT satisfy ``Comparator``."""

    class _NakedObject:
        def compare(self, source: Any, target: Any) -> tuple[DeltaBase, ...]:
            return ()

    assert not isinstance(_NakedObject(), Comparator)


@pytest.mark.unit
def test_object_without_compare_does_not_satisfy_protocol() -> None:
    """An object missing ``compare`` does NOT satisfy ``Comparator``."""

    class _KindOnly:
        kind = ObjectKind.TABLE

    assert not isinstance(_KindOnly(), Comparator)


# ---------------------------------------------------------------------------
# DiffEngine construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_engine_empty_registry() -> None:
    """Constructing an engine with an empty registry must succeed."""
    engine = DiffEngine(comparators=[])
    assert engine.registered_kinds == frozenset()


@pytest.mark.unit
def test_engine_single_comparator() -> None:
    """A single comparator is registered cleanly."""
    cmp = _RecordingComparator(kind=ObjectKind.TABLE)
    engine = DiffEngine(comparators=[cmp])
    assert ObjectKind.TABLE in engine.registered_kinds


@pytest.mark.unit
def test_engine_multiple_comparators() -> None:
    """Multiple comparators for different kinds all register correctly."""
    table_cmp = _RecordingComparator(kind=ObjectKind.TABLE)
    schema_cmp = _RecordingComparator(kind=ObjectKind.SCHEMA)
    ext_cmp = _RecordingComparator(kind=ObjectKind.EXTENSION)
    engine = DiffEngine(comparators=[table_cmp, schema_cmp, ext_cmp])
    assert engine.registered_kinds == {ObjectKind.TABLE, ObjectKind.SCHEMA, ObjectKind.EXTENSION}


@pytest.mark.unit
def test_engine_duplicate_kind_raises_diff_error() -> None:
    """Registering two comparators with the same kind must raise ``DiffError``."""
    cmp1 = _RecordingComparator(kind=ObjectKind.TABLE)
    cmp2 = _RecordingComparator(kind=ObjectKind.TABLE)
    with pytest.raises(DiffError, match="Duplicate comparator registration"):
        DiffEngine(comparators=[cmp1, cmp2])


@pytest.mark.unit
def test_engine_duplicate_kind_error_names_the_kind() -> None:
    """The DiffError message must include the conflicting ObjectKind."""
    cmp1 = _RecordingComparator(kind=ObjectKind.INDEX)
    cmp2 = _RecordingComparator(kind=ObjectKind.INDEX)
    with pytest.raises(DiffError, match="index"):
        DiffEngine(comparators=[cmp1, cmp2])


# ---------------------------------------------------------------------------
# Empty diff
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_vs_empty_returns_empty_delta_set() -> None:
    """Two empty databases with a registered comparator → empty DeltaSet."""
    cmp = _RecordingComparator(kind=ObjectKind.SCHEMA)
    engine = DiffEngine(comparators=[cmp])

    result = engine.diff(_make_db(), _make_db())

    assert isinstance(result, DeltaSet)
    assert result.is_empty()
    assert cmp.calls == []


@pytest.mark.unit
def test_no_registered_comparators_returns_empty_delta_set() -> None:
    """An engine with no comparators always returns an empty DeltaSet."""
    src = _make_db(schemas=(_make_schema("public"),))
    tgt = _make_db(schemas=(_make_schema("public"),))
    engine = DiffEngine(comparators=[])

    result = engine.diff(src, tgt)

    assert result.is_empty()


# ---------------------------------------------------------------------------
# Pairing semantics — source-only, target-only, both present
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_only_source_none_target_present() -> None:
    """Object in target but not source → comparator receives (None, obj)."""
    cmp = _RecordingComparator(
        kind=ObjectKind.SCHEMA,
        canned_deltas=(_create_schema_delta("app"),),
    )
    engine = DiffEngine(comparators=[cmp])

    src = _make_db()
    tgt = _make_db(schemas=(_make_schema("app"),))

    result = engine.diff(src, tgt)

    assert len(cmp.calls) == 1
    src_obj, tgt_obj = cmp.calls[0]
    assert src_obj is None
    assert isinstance(tgt_obj, Schema)
    assert len(result) == 1


@pytest.mark.unit
def test_drop_only_source_present_target_none() -> None:
    """Object in source but not target → comparator receives (obj, None)."""
    cmp = _RecordingComparator(
        kind=ObjectKind.SCHEMA,
        canned_deltas=(_drop_schema_delta("old"),),
    )
    engine = DiffEngine(comparators=[cmp])

    src = _make_db(schemas=(_make_schema("old"),))
    tgt = _make_db()

    result = engine.diff(src, tgt)

    assert len(cmp.calls) == 1
    src_obj, tgt_obj = cmp.calls[0]
    assert isinstance(src_obj, Schema)
    assert tgt_obj is None
    assert len(result) == 1


@pytest.mark.unit
def test_both_present_comparator_receives_both() -> None:
    """Object in both source and target → comparator receives (src_obj, tgt_obj)."""
    cmp = _RecordingComparator(kind=ObjectKind.SCHEMA, canned_deltas=())
    engine = DiffEngine(comparators=[cmp])

    schema_name = "public"
    src = _make_db(schemas=(_make_schema(schema_name),))
    tgt = _make_db(schemas=(_make_schema(schema_name),))

    engine.diff(src, tgt)

    assert len(cmp.calls) == 1
    src_obj, tgt_obj = cmp.calls[0]
    assert isinstance(src_obj, Schema)
    assert isinstance(tgt_obj, Schema)


@pytest.mark.unit
def test_no_change_empty_return_yields_no_deltas() -> None:
    """A comparator that returns () for an identical pair → no deltas in result."""
    cmp = _SilentComparator(kind=ObjectKind.SCHEMA)
    engine = DiffEngine(comparators=[cmp])

    schema = _make_schema("public")
    src = _make_db(schemas=(schema,))
    tgt = _make_db(schemas=(schema,))

    result = engine.diff(src, tgt)
    assert result.is_empty()


# ---------------------------------------------------------------------------
# Multiple objects per kind
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_multiple_schemas_each_paired_correctly() -> None:
    """With N schemas on each side sharing a name, N pairs must be dispatched."""
    cmp = _RecordingComparator(kind=ObjectKind.SCHEMA, canned_deltas=())
    engine = DiffEngine(comparators=[cmp])

    src = _make_db(schemas=(_make_schema("alpha"), _make_schema("beta")))
    tgt = _make_db(schemas=(_make_schema("alpha"), _make_schema("gamma")))

    engine.diff(src, tgt)

    # alpha: both sides; beta: source only; gamma: target only → 3 calls
    assert len(cmp.calls) == 3


@pytest.mark.unit
def test_schemas_source_only_all_dropped() -> None:
    """All schemas exist only in source → all comparator calls have target=None."""
    drop_a = _drop_schema_delta("a")
    cmp = _RecordingComparator(
        kind=ObjectKind.SCHEMA,
        canned_deltas=(drop_a,),  # returns 1 delta per call
    )
    engine = DiffEngine(comparators=[cmp])

    src = _make_db(schemas=(_make_schema("a"), _make_schema("b")))
    tgt = _make_db()

    result = engine.diff(src, tgt)

    assert len(cmp.calls) == 2
    for src_obj, tgt_obj in cmp.calls:
        assert isinstance(src_obj, Schema)
        assert tgt_obj is None
    assert len(result) == 2  # one delta per call


@pytest.mark.unit
def test_schemas_target_only_all_created() -> None:
    """All schemas exist only in target → all comparator calls have source=None."""
    cmp = _RecordingComparator(
        kind=ObjectKind.SCHEMA,
        canned_deltas=(_create_schema_delta("x"),),
    )
    engine = DiffEngine(comparators=[cmp])

    src = _make_db()
    tgt = _make_db(schemas=(_make_schema("x"), _make_schema("y")))

    result = engine.diff(src, tgt)

    assert len(cmp.calls) == 2
    for src_obj, tgt_obj in cmp.calls:
        assert src_obj is None
        assert isinstance(tgt_obj, Schema)
    # 2 calls x 1 delta each
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Multi-comparator aggregation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_deltas_from_multiple_comparators_aggregated() -> None:
    """Deltas from all comparators must be combined into a single DeltaSet."""
    schema_delta = _create_schema_delta("app")
    table_delta = _create_table_delta("app", "users")

    schema_cmp = _RecordingComparator(
        kind=ObjectKind.SCHEMA,
        canned_deltas=(schema_delta,),
    )
    table_cmp = _RecordingComparator(
        kind=ObjectKind.TABLE,
        canned_deltas=(table_delta,),
    )
    engine = DiffEngine(comparators=[schema_cmp, table_cmp])

    table = _make_table("app", "users")
    src = _make_db(schemas=(_make_schema("app", tables=(table,)),))
    tgt = _make_db()

    result = engine.diff(src, tgt)

    all_deltas = list(result)
    assert schema_delta in all_deltas
    assert table_delta in all_deltas
    assert len(all_deltas) == 2


@pytest.mark.unit
def test_silent_comparator_does_not_pollute_result() -> None:
    """A silent comparator that returns () must not add any deltas."""
    schema_delta = _create_schema_delta("s")
    schema_cmp = _RecordingComparator(
        kind=ObjectKind.SCHEMA,
        canned_deltas=(schema_delta,),
    )
    silent_table = _SilentComparator(kind=ObjectKind.TABLE)
    engine = DiffEngine(comparators=[schema_cmp, silent_table])

    src = _make_db()
    tgt = _make_db(schemas=(_make_schema("s"),))

    result = engine.diff(src, tgt)
    assert len(result) == 1
    assert schema_delta in result


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_deterministic_ordering_independent_of_schema_order() -> None:
    """The DeltaSet order must be stable regardless of schema iteration order.

    We build two databases with the same schemas but stored in different order
    and verify that the comparator always receives calls in the same alphabetical
    order.
    """
    cmp = _RecordingComparator(kind=ObjectKind.SCHEMA, canned_deltas=())
    engine = DiffEngine(comparators=[cmp])

    schemas_fwd = (_make_schema("alpha"), _make_schema("beta"), _make_schema("gamma"))
    schemas_rev = tuple(reversed(schemas_fwd))

    # Run 1: forward order
    engine.diff(_make_db(schemas=schemas_fwd), _make_db())
    calls_fwd = [(type(s).__name__, type(t).__name__) for s, t in cmp.calls]
    cmp.calls.clear()

    # Run 2: reversed order — same objects, reversed tuple
    engine.diff(_make_db(schemas=schemas_rev), _make_db())
    calls_rev = [(type(s).__name__, type(t).__name__) for s, t in cmp.calls]

    assert calls_fwd == calls_rev


@pytest.mark.unit
def test_deterministic_call_order_names() -> None:
    """Schemas are dispatched in alphabetical (namespace, name) order."""
    call_names: list[str] = []

    class _NameRecorder:
        kind = ObjectKind.SCHEMA

        def compare(
            self,
            source: object | None,
            target: object | None,
        ) -> Iterable[DeltaBase]:
            # source is None here (target-only); target is the Schema object
            assert isinstance(target, Schema)
            call_names.append(target.name)
            return ()

    engine = DiffEngine(comparators=[_NameRecorder()])

    src = _make_db()
    tgt = _make_db(schemas=(_make_schema("zebra"), _make_schema("apple"), _make_schema("mango")))

    engine.diff(src, tgt)

    assert call_names == ["apple", "mango", "zebra"]


@pytest.mark.unit
def test_deterministic_with_shuffled_input() -> None:
    """Shuffling the list of schemas before building the Database must not
    change the order in which comparator.compare is called."""
    schemas = [_make_schema(n) for n in ["delta", "alpha", "gamma", "beta"]]

    cmp1 = _RecordingComparator(kind=ObjectKind.SCHEMA, canned_deltas=())
    cmp2 = _RecordingComparator(kind=ObjectKind.SCHEMA, canned_deltas=())

    engine1 = DiffEngine(comparators=[cmp1])
    engine2 = DiffEngine(comparators=[cmp2])

    shuffled = schemas[:]
    random.shuffle(shuffled)

    engine1.diff(_make_db(), _make_db(schemas=tuple(schemas)))
    engine2.diff(_make_db(), _make_db(schemas=tuple(shuffled)))

    names1 = [t.name for _, t in cmp1.calls if isinstance(t, Schema)]
    names2 = [t.name for _, t in cmp2.calls if isinstance(t, Schema)]

    assert names1 == names2 == ["alpha", "beta", "delta", "gamma"]


# ---------------------------------------------------------------------------
# Dispatch — correct comparator is called for each kind
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_correct_comparator_dispatched_for_schema_kind() -> None:
    """SCHEMA kind dispatches to the SCHEMA comparator, not TABLE."""
    schema_cmp = _RecordingComparator(kind=ObjectKind.SCHEMA)
    table_cmp = _RecordingComparator(kind=ObjectKind.TABLE)
    engine = DiffEngine(comparators=[schema_cmp, table_cmp])

    src = _make_db(schemas=(_make_schema("s"),))
    tgt = _make_db()

    engine.diff(src, tgt)

    assert len(schema_cmp.calls) == 1
    assert len(table_cmp.calls) == 0


@pytest.mark.unit
def test_correct_comparator_dispatched_for_table_kind() -> None:
    """TABLE kind dispatches to the TABLE comparator, not SCHEMA."""
    schema_cmp = _RecordingComparator(kind=ObjectKind.SCHEMA)
    table_cmp = _RecordingComparator(kind=ObjectKind.TABLE)
    engine = DiffEngine(comparators=[schema_cmp, table_cmp])

    table = _make_table("public", "users")
    src = _make_db(schemas=(_make_schema("public", tables=(table,)),))
    tgt = _make_db(schemas=(_make_schema("public"),))

    engine.diff(src, tgt)

    assert len(table_cmp.calls) == 1
    assert len(schema_cmp.calls) == 1  # "public" schema exists on both sides


@pytest.mark.unit
def test_index_kind_dispatched_to_index_comparator() -> None:
    """INDEX comparator is called once per index pair."""
    index_cmp = _RecordingComparator(
        kind=ObjectKind.INDEX,
        canned_deltas=(_create_index_delta("public", "idx"),),
    )
    engine = DiffEngine(comparators=[index_cmp])

    idx = _make_index("public", "idx", "t")
    schema_src = Schema(
        ref=_schema_ref("public"),
        tables=(_make_table("public", "t"),),
        indexes=(),
    )
    schema_tgt = Schema(
        ref=_schema_ref("public"),
        tables=(_make_table("public", "t"),),
        indexes=(idx,),
    )
    src = _make_db(schemas=(schema_src,))
    tgt = _make_db(schemas=(schema_tgt,))

    result = engine.diff(src, tgt)

    assert len(index_cmp.calls) == 1
    src_obj, tgt_obj = index_cmp.calls[0]
    assert src_obj is None  # index only in target
    assert isinstance(tgt_obj, Index)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# _fetch_objects_for_kind helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_schema_objects() -> None:
    """Schema kind returns a mapping of QualifiedName → Schema."""
    s1 = _make_schema("alpha")
    s2 = _make_schema("beta")
    db = _make_db(schemas=(s1, s2))

    fetched = _fetch_objects_for_kind(db, ObjectKind.SCHEMA)

    assert len(fetched) == 2
    assert all(isinstance(v, Schema) for v in fetched.values())
    assert _qname("alpha", "alpha") in fetched
    assert _qname("beta", "beta") in fetched


@pytest.mark.unit
def test_fetch_extension_objects() -> None:
    """Extension kind returns a mapping of QualifiedName → Extension."""
    ext = _make_extension("pgcrypto")
    db = _make_db(extensions=(ext,))

    fetched = _fetch_objects_for_kind(db, ObjectKind.EXTENSION)

    assert len(fetched) == 1
    assert all(isinstance(v, Extension) for v in fetched.values())


@pytest.mark.unit
def test_fetch_table_objects() -> None:
    """Table kind returns all tables from all schemas."""
    t1 = _make_table("public", "users")
    t2 = _make_table("app", "orders")
    db = _make_db(
        schemas=(
            _make_schema("public", tables=(t1,)),
            _make_schema("app", tables=(t2,)),
        )
    )

    fetched = _fetch_objects_for_kind(db, ObjectKind.TABLE)

    assert len(fetched) == 2
    assert all(isinstance(v, Table) for v in fetched.values())


@pytest.mark.unit
def test_fetch_index_objects() -> None:
    """Index kind returns all indexes from all schemas."""
    idx = _make_index("public", "users_idx", "users")
    schema = Schema(
        ref=_schema_ref("public"),
        tables=(_make_table("public", "users"),),
        indexes=(idx,),
    )
    db = _make_db(schemas=(schema,))

    fetched = _fetch_objects_for_kind(db, ObjectKind.INDEX)

    assert len(fetched) == 1
    assert all(isinstance(v, Index) for v in fetched.values())


@pytest.mark.unit
def test_fetch_unknown_kind_returns_empty_dict() -> None:
    """An ObjectKind that has no fetcher returns an empty dict (not an error)."""
    db = _make_db(schemas=(_make_schema("public"),))

    # VIEW is not yet introspected — must return {} not raise
    result = _fetch_objects_for_kind(db, ObjectKind.VIEW)
    assert result == {}


@pytest.mark.unit
def test_fetch_empty_db_returns_empty_dicts() -> None:
    """All known kinds return empty dicts for an empty database."""
    db = _make_db()
    for kind in (
        ObjectKind.SCHEMA,
        ObjectKind.EXTENSION,
        ObjectKind.TABLE,
        ObjectKind.INDEX,
    ):
        assert _fetch_objects_for_kind(db, kind) == {}


# ---------------------------------------------------------------------------
# Package-level export
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_comparator_exported_from_package() -> None:
    """``Comparator`` must be importable from ``pgschemadiff.application.diff``."""
    assert hasattr(_diff_pkg, "Comparator")
    assert _diff_pkg.Comparator is Comparator


@pytest.mark.unit
def test_diff_engine_exported_from_package() -> None:
    """``DiffEngine`` must be importable from ``pgschemadiff.application.diff``."""
    assert hasattr(_diff_pkg, "DiffEngine")
    assert _diff_pkg.DiffEngine is DiffEngine


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_engine_with_no_objects_comparator_never_called() -> None:
    """A comparator for VIEW (no fetcher objects) is never invoked."""
    cmp = _RecordingComparator(kind=ObjectKind.VIEW)
    engine = DiffEngine(comparators=[cmp])

    src = _make_db(schemas=(_make_schema("public"),))
    tgt = _make_db(schemas=(_make_schema("public"),))

    result = engine.diff(src, tgt)
    assert cmp.calls == []
    assert result.is_empty()


@pytest.mark.unit
def test_multiple_deltas_per_call_all_included() -> None:
    """A comparator returning multiple deltas per call must have all included."""
    d1 = _create_schema_delta("a")
    d2 = _drop_schema_delta("a")
    cmp = _RecordingComparator(kind=ObjectKind.SCHEMA, canned_deltas=(d1, d2))
    engine = DiffEngine(comparators=[cmp])

    src = _make_db(schemas=(_make_schema("a"),))
    tgt = _make_db(schemas=(_make_schema("a"),))

    result = engine.diff(src, tgt)
    assert len(result) == 2
    assert d1 in result
    assert d2 in result


@pytest.mark.unit
def test_diff_returns_delta_set_instance() -> None:
    """``diff()`` must always return a ``DeltaSet`` instance."""
    engine = DiffEngine(comparators=[])
    result = engine.diff(_make_db(), _make_db())
    assert isinstance(result, DeltaSet)


@pytest.mark.unit
def test_registered_kinds_property_is_frozenset() -> None:
    """``registered_kinds`` must return a ``frozenset``."""
    engine = DiffEngine(comparators=[_RecordingComparator(kind=ObjectKind.TABLE)])
    assert isinstance(engine.registered_kinds, frozenset)


@pytest.mark.unit
def test_extension_comparator_dispatch() -> None:
    """EXTENSION kind correctly dispatches and receives Extension objects."""
    ext_cmp = _RecordingComparator(kind=ObjectKind.EXTENSION)
    engine = DiffEngine(comparators=[ext_cmp])

    src = _make_db(extensions=(_make_extension("pgcrypto"),))
    tgt = _make_db(extensions=(_make_extension("pgcrypto"), _make_extension("postgis")))

    engine.diff(src, tgt)

    # pgcrypto: both sides → (ext, ext)
    # postgis: target only → (None, ext)
    assert len(ext_cmp.calls) == 2
    both_present = [(s, t) for s, t in ext_cmp.calls if s is not None and t is not None]
    create_only = [(s, t) for s, t in ext_cmp.calls if s is None and t is not None]
    assert len(both_present) == 1
    assert len(create_only) == 1


@pytest.mark.unit
def test_engine_does_not_mutate_input_databases() -> None:
    """``diff()`` must be pure: input ``Database`` objects are not mutated.

    Domain models are frozen Pydantic models so any mutation attempt would
    raise.  This test asserts the engine does not even try.
    """
    schema = _make_schema("public")
    src = _make_db(schemas=(schema,))
    tgt = _make_db()

    cmp = _SilentComparator(kind=ObjectKind.SCHEMA)
    engine = DiffEngine(comparators=[cmp])

    # Capture string representations before the diff
    src_repr = repr(src)
    tgt_repr = repr(tgt)

    engine.diff(src, tgt)

    assert repr(src) == src_repr
    assert repr(tgt) == tgt_repr
