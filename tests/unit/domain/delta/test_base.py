"""Unit tests for ``pgschemadiff.domain.delta.base`` (task P2-DOM-01a).

Covers:
- DeltaOp StrEnum membership and value round-trip
- DeltaBase frozen behaviour and extra-field rejection
- DeltaBase construction with ObjectRef / QualifiedName target
- DeltaBase.sort_key stable ordering contract
- DeltaSet construction, iteration, len, containment
- DeltaSet.from_iterable alternative constructor
- DeltaSet lookup helpers: by_op, by_target, is_empty
- Package-level re-export via ``from pgschemadiff.domain.delta import ...``
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.delta import DeltaBase, DeltaOp, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

# ---------------------------------------------------------------------------
# Concrete test subclass (DeltaBase is abstract — needs narrowed Literal op)
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
    assert DeltaOp.NO_CHANGE.value == "no_change"


@pytest.mark.unit
def test_delta_op_exact_members() -> None:
    """DeltaOp has exactly the six expected members — no accidental additions."""
    expected = {"create", "drop", "alter", "rename", "replace", "no_change"}
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
# DeltaBase — sort_key
# ===========================================================================


@pytest.mark.unit
def test_delta_base_sort_key_structure(create_delta: _CreateDelta) -> None:
    """sort_key is a 3-tuple (namespace, object_name, op_value)."""
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

    # c: (a_schema, a_table, create → drop)
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
