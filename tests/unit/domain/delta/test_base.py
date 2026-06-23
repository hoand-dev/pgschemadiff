"""Unit tests for ``pgschemadiff.domain.delta.base`` (task P2-DOM-01a).

Covers:
- DeltaOp StrEnum membership and value round-trip
- DeltaBase frozen behaviour and extra-field rejection
- DeltaBase construction with ObjectRef / QualifiedName target
- DeltaBase.sort_key stable ordering contract (top-level and sub-objects)
- DeltaBase.sort_key collision-freedom for sub-objects on different parents
- DeltaSet construction, iteration, len, containment
- DeltaSet.from_iterable alternative constructor (accepts any Iterable)
- DeltaSet lookup helpers: by_op, by_target, is_empty
- DeltaSet JSON round-trip (base-level fields preserved; lossy limitation documented)
- DeltaSet model_dump shape
- Package-level re-export via ``from pgschemadiff.domain.delta import ...``
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.delta import DeltaBase, DeltaOp, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

# ---------------------------------------------------------------------------
# Concrete test subclasses (DeltaBase is abstract — needs narrowed Literal op)
# ---------------------------------------------------------------------------


class _CreateDelta(DeltaBase):
    """Minimal concrete subclass for CREATE operations used in tests."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE


class _DropDelta(DeltaBase):
    """Minimal concrete subclass for DROP operations used in tests."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP


class _AlterDelta(DeltaBase):
    """Minimal concrete subclass for ALTER operations used in tests."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def table_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )


@pytest.fixture
def schema_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )


@pytest.fixture
def index_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace="myns", name="users_pkey"),
    )


@pytest.fixture
def create_delta(table_ref: ObjectRef) -> _CreateDelta:
    return _CreateDelta(target=table_ref)


@pytest.fixture
def drop_delta(table_ref: ObjectRef) -> _DropDelta:
    return _DropDelta(target=table_ref)


@pytest.fixture
def alter_delta(index_ref: ObjectRef) -> _AlterDelta:
    return _AlterDelta(target=index_ref)


# ===========================================================================
# DeltaOp tests
# ===========================================================================


@pytest.mark.unit
def test_delta_op_is_str_enum() -> None:
    """DeltaOp values are plain strings (StrEnum contract)."""
    assert isinstance(DeltaOp.CREATE, str)
    # Use .value comparisons so mypy sees matching literal types.
    assert DeltaOp.CREATE.value == "create"
    assert DeltaOp.DROP.value == "drop"
    assert DeltaOp.ALTER.value == "alter"
    assert DeltaOp.RENAME.value == "rename"
    assert DeltaOp.REPLACE.value == "replace"


@pytest.mark.unit
def test_delta_op_exact_members() -> None:
    """DeltaOp has exactly the five expected members — no accidental additions.

    NO_CHANGE was removed from the production enum (RF-A finding 6): no
    concrete comparator subclass carries it and there is no production
    consumer.  Tests that need a sentinel op should define a fixture-local
    value or use one of the real five ops.
    """
    expected = {"create", "drop", "alter", "rename", "replace"}
    actual = {m.value for m in DeltaOp}
    assert actual == expected


@pytest.mark.unit
def test_delta_op_round_trip_through_string() -> None:
    """Every DeltaOp member can be reconstructed from its string value."""
    for op in DeltaOp:
        assert DeltaOp(str(op)) is op


@pytest.mark.unit
def test_delta_op_hashable_and_usable_as_dict_key() -> None:
    mapping = {DeltaOp.CREATE: "c", DeltaOp.DROP: "d"}
    assert mapping[DeltaOp.CREATE] == "c"
    assert mapping[DeltaOp.DROP] == "d"


# ===========================================================================
# DeltaBase construction tests
# ===========================================================================


@pytest.mark.unit
def test_delta_base_constructs_with_table_target(table_ref: ObjectRef) -> None:
    delta = _CreateDelta(target=table_ref)
    assert delta.op is DeltaOp.CREATE
    assert delta.target is table_ref


@pytest.mark.unit
def test_delta_base_constructs_with_schema_target(schema_ref: ObjectRef) -> None:
    delta = _CreateDelta(target=schema_ref)
    assert delta.target.kind is ObjectKind.SCHEMA


@pytest.mark.unit
def test_delta_base_drop_op(table_ref: ObjectRef) -> None:
    delta = _DropDelta(target=table_ref)
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_delta_base_alter_op(index_ref: ObjectRef) -> None:
    delta = _AlterDelta(target=index_ref)
    assert delta.op is DeltaOp.ALTER


# ===========================================================================
# DeltaBase — immutability (frozen=True)
# ===========================================================================


@pytest.mark.unit
def test_delta_base_is_frozen(create_delta: _CreateDelta, table_ref: ObjectRef) -> None:
    """Mutation of any field on a frozen delta must raise ValidationError."""
    other_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="other", name="orders"),
    )
    with pytest.raises(ValidationError):
        create_delta.target = other_ref  # type: ignore[misc]


@pytest.mark.unit
def test_delta_base_op_is_frozen(create_delta: _CreateDelta) -> None:
    with pytest.raises(ValidationError):
        create_delta.op = DeltaOp.CREATE  # type: ignore[misc]


# ===========================================================================
# DeltaBase — extra="forbid"
# ===========================================================================


@pytest.mark.unit
def test_delta_base_rejects_extra_fields(table_ref: ObjectRef) -> None:
    """Extra keyword arguments must raise ValidationError (extra='forbid')."""
    with pytest.raises(ValidationError):
        _CreateDelta(target=table_ref, unexpected_field="oops")  # type: ignore[call-arg]


# ===========================================================================
# DeltaBase — sort_key (top-level objects)
# ===========================================================================


@pytest.mark.unit
def test_delta_base_sort_key_structure_top_level(create_delta: _CreateDelta) -> None:
    """sort_key for a top-level object is a 3-tuple (namespace, object_name, op_value)."""
    key = create_delta.sort_key
    assert len(key) == 3
    assert key == ("public", "users", "create")


@pytest.mark.unit
def test_delta_base_sort_key_uses_namespace(index_ref: ObjectRef) -> None:
    delta = _AlterDelta(target=index_ref)
    ns, name, op_val = delta.sort_key
    assert ns == "myns"
    assert name == "users_pkey"
    assert op_val == "alter"


@pytest.mark.unit
def test_delta_base_sort_key_ordering() -> None:
    """Deltas sort deterministically by (namespace, name, op)."""
    ref_a = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="a_schema", name="z_table"),
    )
    ref_b = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="b_schema", name="a_table"),
    )
    ref_c = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="a_schema", name="a_table"),
    )
    delta_a = _CreateDelta(target=ref_a)
    delta_b = _CreateDelta(target=ref_b)
    delta_c = _DropDelta(target=ref_c)

    deltas = [delta_a, delta_b, delta_c]
    sorted_deltas = sorted(deltas, key=lambda d: d.sort_key)

    # c: (a_schema, a_table, drop)
    # a: (a_schema, z_table, create)
    # b: (b_schema, a_table, create)
    assert sorted_deltas[0] is delta_c
    assert sorted_deltas[1] is delta_a
    assert sorted_deltas[2] is delta_b


@pytest.mark.unit
def test_delta_base_sort_key_differentiates_ops() -> None:
    """Same target with different ops produces different sort keys."""
    ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )
    create = _CreateDelta(target=ref)
    drop = _DropDelta(target=ref)
    assert create.sort_key != drop.sort_key
    assert create.sort_key[2] == "create"
    assert drop.sort_key[2] == "drop"


# ===========================================================================
# DeltaBase — sort_key (sub-objects, MERGE-BLOCKER 1 regression tests)
# ===========================================================================


@pytest.mark.unit
def test_delta_base_sort_key_sub_object_shape() -> None:
    """sort_key for a sub-object is a 4-tuple (parent_ns, parent_name, local_name, op)."""
    parent_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )
    col_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=parent_ref,
    )
    delta = _AlterDelta(target=col_ref)
    key = delta.sort_key
    assert len(key) == 4
    assert key == ("public", "users", "id", "alter")


@pytest.mark.unit
def test_delta_base_sort_key_sub_objects_different_parents_are_unique() -> None:
    """Two sub-objects with the same local name on different parents must not collide.

    Regression test for MERGE-BLOCKER 1: before the fix, both
    public.users.id and public.orders.id produced ('public', 'id', 'alter'),
    making them indistinguishable to the topo-sort tie-breaker.
    """
    users_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )
    orders_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="orders"),
    )
    col_users_id = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=users_ref,
    )
    col_orders_id = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=orders_ref,
    )
    delta_users = _AlterDelta(target=col_users_id)
    delta_orders = _AlterDelta(target=col_orders_id)

    assert delta_users.sort_key != delta_orders.sort_key
    assert delta_users.sort_key == ("public", "users", "id", "alter")
    assert delta_orders.sort_key == ("public", "orders", "id", "alter")


@pytest.mark.unit
def test_delta_base_sort_key_sub_objects_sort_stably() -> None:
    """Sub-object deltas sort deterministically and group by parent."""
    users_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )
    orders_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="orders"),
    )
    # Two columns on users, one on orders — all named differently
    users_id = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=users_ref,
    )
    users_name = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="name"),
        parent=users_ref,
    )
    orders_id = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=orders_ref,
    )
    d_users_id = _AlterDelta(target=users_id)
    d_users_name = _AlterDelta(target=users_name)
    d_orders_id = _AlterDelta(target=orders_id)

    sorted_deltas = sorted(
        [d_users_id, d_users_name, d_orders_id],
        key=lambda d: d.sort_key,
    )
    # orders.id ("public","orders","id","alter") < users.id ("public","users","id","alter")
    # < users.name ("public","users","name","alter")
    assert sorted_deltas[0] is d_orders_id
    assert sorted_deltas[1] is d_users_id
    assert sorted_deltas[2] is d_users_name


# ===========================================================================
# DeltaBase — equality and hash (frozen Pydantic models are hashable)
# ===========================================================================


@pytest.mark.unit
def test_delta_base_equality(table_ref: ObjectRef) -> None:
    a = _CreateDelta(target=table_ref)
    b = _CreateDelta(target=table_ref)
    assert a == b
    assert hash(a) == hash(b)


@pytest.mark.unit
def test_delta_base_inequality_different_op(table_ref: ObjectRef) -> None:
    # Upcast to DeltaBase so mypy doesn't flag the comparison as
    # always-unequal between two concrete literal-narrowed types.
    create: DeltaBase = _CreateDelta(target=table_ref)
    drop: DeltaBase = _DropDelta(target=table_ref)
    assert create != drop


# ===========================================================================
# DeltaBase — JSON round-trip
# ===========================================================================


@pytest.mark.unit
def test_delta_base_json_round_trip(table_ref: ObjectRef) -> None:
    delta = _CreateDelta(target=table_ref)
    payload = delta.model_dump_json()
    restored = _CreateDelta.model_validate_json(payload)
    assert restored == delta


# ===========================================================================
# DeltaSet construction
# ===========================================================================


@pytest.mark.unit
def test_delta_set_empty_by_default() -> None:
    ds = DeltaSet()
    assert len(ds) == 0
    assert ds.is_empty()


@pytest.mark.unit
def test_delta_set_with_deltas(
    create_delta: _CreateDelta,
    drop_delta: _DropDelta,
) -> None:
    ds = DeltaSet(deltas=(create_delta, drop_delta))
    assert len(ds) == 2
    assert not ds.is_empty()


@pytest.mark.unit
def test_delta_set_from_iterable(
    create_delta: _CreateDelta,
    drop_delta: _DropDelta,
) -> None:
    ds = DeltaSet.from_iterable([create_delta, drop_delta])
    assert len(ds) == 2


@pytest.mark.unit
def test_delta_set_from_empty_iterable() -> None:
    ds = DeltaSet.from_iterable([])
    assert ds.is_empty()


@pytest.mark.unit
def test_delta_set_from_iterable_accepts_tuple(
    create_delta: _CreateDelta,
    drop_delta: _DropDelta,
) -> None:
    """from_iterable must accept tuples (and any Iterable), not just lists."""
    ds = DeltaSet.from_iterable((create_delta, drop_delta))
    assert len(ds) == 2


@pytest.mark.unit
def test_delta_set_from_iterable_accepts_generator(table_ref: ObjectRef) -> None:
    """from_iterable must accept generator expressions."""
    refs = [table_ref, table_ref]
    ds = DeltaSet.from_iterable(_CreateDelta(target=r) for r in refs)
    assert len(ds) == 2


# ===========================================================================
# DeltaSet iteration
# ===========================================================================


@pytest.mark.unit
def test_delta_set_iteration(
    create_delta: _CreateDelta,
    drop_delta: _DropDelta,
) -> None:
    ds = DeltaSet(deltas=(create_delta, drop_delta))
    collected = list(ds)
    assert collected == [create_delta, drop_delta]


@pytest.mark.unit
def test_delta_set_preserves_order(table_ref: ObjectRef, index_ref: ObjectRef) -> None:
    """DeltaSet must preserve insertion order."""
    d1 = _CreateDelta(target=table_ref)
    d2 = _AlterDelta(target=index_ref)
    d3 = _DropDelta(target=table_ref)
    ds = DeltaSet(deltas=(d1, d2, d3))
    assert list(ds) == [d1, d2, d3]


# ===========================================================================
# DeltaSet containment
# ===========================================================================


@pytest.mark.unit
def test_delta_set_containment(
    create_delta: _CreateDelta,
    drop_delta: _DropDelta,
) -> None:
    ds = DeltaSet(deltas=(create_delta,))
    assert create_delta in ds
    assert drop_delta not in ds


# ===========================================================================
# DeltaSet — frozen (immutability)
# ===========================================================================


@pytest.mark.unit
def test_delta_set_is_frozen(create_delta: _CreateDelta) -> None:
    ds = DeltaSet(deltas=(create_delta,))
    with pytest.raises(ValidationError):
        ds.deltas = ()  # type: ignore[misc]


@pytest.mark.unit
def test_delta_set_rejects_extra_fields(create_delta: _CreateDelta) -> None:
    with pytest.raises(ValidationError):
        DeltaSet(deltas=(create_delta,), extra_field="oops")  # type: ignore[call-arg]


# ===========================================================================
# DeltaSet — lookup helpers
# ===========================================================================


@pytest.mark.unit
def test_delta_set_by_op_filters_correctly(
    create_delta: _CreateDelta,
    drop_delta: _DropDelta,
    alter_delta: _AlterDelta,
) -> None:
    ds = DeltaSet(deltas=(create_delta, drop_delta, alter_delta))
    creates = ds.by_op(DeltaOp.CREATE)
    drops = ds.by_op(DeltaOp.DROP)
    alters = ds.by_op(DeltaOp.ALTER)
    assert creates == (create_delta,)
    assert drops == (drop_delta,)
    assert alters == (alter_delta,)


@pytest.mark.unit
def test_delta_set_by_op_returns_empty_tuple_when_none_match(
    create_delta: _CreateDelta,
) -> None:
    ds = DeltaSet(deltas=(create_delta,))
    assert ds.by_op(DeltaOp.DROP) == ()


@pytest.mark.unit
def test_delta_set_by_target_filters_correctly(
    table_ref: ObjectRef,
    index_ref: ObjectRef,
    create_delta: _CreateDelta,  # targets table_ref
    drop_delta: _DropDelta,  # targets table_ref
    alter_delta: _AlterDelta,  # targets index_ref
) -> None:
    ds = DeltaSet(deltas=(create_delta, drop_delta, alter_delta))
    table_deltas = ds.by_target(table_ref)
    index_deltas = ds.by_target(index_ref)
    assert create_delta in table_deltas
    assert drop_delta in table_deltas
    assert alter_delta not in table_deltas
    assert alter_delta in index_deltas
    assert len(table_deltas) == 2
    assert len(index_deltas) == 1


@pytest.mark.unit
def test_delta_set_by_target_returns_empty_when_no_match(
    create_delta: _CreateDelta,
) -> None:
    ds = DeltaSet(deltas=(create_delta,))
    missing_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="other", name="missing"),
    )
    assert ds.by_target(missing_ref) == ()


# ===========================================================================
# DeltaSet — equality and hash
# ===========================================================================


@pytest.mark.unit
def test_delta_set_equality(
    create_delta: _CreateDelta,
    drop_delta: _DropDelta,
) -> None:
    ds_a = DeltaSet(deltas=(create_delta, drop_delta))
    ds_b = DeltaSet(deltas=(create_delta, drop_delta))
    assert ds_a == ds_b
    assert hash(ds_a) == hash(ds_b)


@pytest.mark.unit
def test_delta_set_inequality_different_order(
    create_delta: _CreateDelta,
    drop_delta: _DropDelta,
) -> None:
    ds_a = DeltaSet(deltas=(create_delta, drop_delta))
    ds_b = DeltaSet(deltas=(drop_delta, create_delta))
    assert ds_a != ds_b


# ===========================================================================
# DeltaSet — JSON round-trip (MERGE-BLOCKER 2 explicit documentation)
# ===========================================================================


@pytest.mark.unit
def test_delta_set_json_round_trip_base_level() -> None:
    """DeltaSet JSON round-trip preserves base-level fields for DeltaBase items.

    Until P2-DOM-01f lands the discriminated Delta union, DeltaSet holds plain
    DeltaBase instances.  A model_dump_json() -> model_validate_json() round-
    trip preserves op and target (the only fields DeltaBase carries).
    """
    ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )
    # Build a DeltaSet using base-level items (what -01a actually supports).
    ds = DeltaSet(
        deltas=(
            DeltaBase(op=DeltaOp.CREATE, target=ref),
            DeltaBase(op=DeltaOp.DROP, target=ref),
        )
    )
    payload = ds.model_dump_json()
    restored = DeltaSet.model_validate_json(payload)

    restored_list = list(restored)
    assert len(restored_list) == 2
    assert restored_list[0].op == DeltaOp.CREATE
    assert restored_list[1].op == DeltaOp.DROP
    assert restored_list[0].target == ref
    assert restored_list[1].target == ref


@pytest.mark.unit
def test_delta_set_json_round_trip_subclass_is_lossy() -> None:
    """Subclass payload is NOT preserved through DeltaSet JSON round-trip.

    This is the documented limitation described in the TODO(P2-DOM-01f) comment
    on DeltaSet.deltas.  A concrete subclass (_CreateDelta) stored in a
    DeltaSet is deserialized as plain DeltaBase (the declared field type),
    dropping any subclass-specific payload.  This test pins the current
    behavior so any change is intentional and visible.
    """
    ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="orders"),
    )
    original = _CreateDelta(target=ref)
    ds = DeltaSet(deltas=(original,))

    payload = ds.model_dump_json()
    restored = DeltaSet.model_validate_json(payload)

    # The op and target round-trip fine.
    restored_delta = next(iter(restored))
    assert restored_delta.op == DeltaOp.CREATE
    assert restored_delta.target == ref
    # The subclass type is lost: restored as DeltaBase, not _CreateDelta.
    # (This is expected and intentional until P2-DOM-01f.)
    assert type(restored_delta) is DeltaBase


@pytest.mark.unit
def test_delta_set_model_dump_shape(create_delta: _CreateDelta) -> None:
    """model_dump() emits the expected {'deltas': (...)} structure.

    Pydantic v2 preserves the Python tuple type in model_dump() (not converted
    to a list).  model_dump_json() serialises it as a JSON array.
    """
    ds = DeltaSet(deltas=(create_delta,))
    dumped = ds.model_dump()
    assert "deltas" in dumped
    # Pydantic v2 preserves tuple type in model_dump(); JSON serialisation
    # uses a JSON array (verified separately via model_dump_json).
    assert isinstance(dumped["deltas"], tuple)
    assert len(dumped["deltas"]) == 1


# ===========================================================================
# Package-level re-export — verified by the top-level imports in this module
# ===========================================================================


@pytest.mark.unit
def test_package_exports_delta_op() -> None:
    """DeltaOp is importable from the package root (verified via top-level import)."""
    # DeltaOp was imported from pgschemadiff.domain.delta at the top of this file.
    assert DeltaOp.CREATE.value == "create"


@pytest.mark.unit
def test_package_exports_delta_base() -> None:
    """DeltaBase is importable from the package root (verified via top-level import)."""
    assert issubclass(DeltaBase, object)


@pytest.mark.unit
def test_package_exports_delta_set() -> None:
    """DeltaSet is importable from the package root (verified via top-level import)."""
    assert issubclass(DeltaSet, object)
