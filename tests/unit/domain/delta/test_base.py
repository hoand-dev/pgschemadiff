"""Unit tests for ``pgschemadiff.domain.delta.base`` (tasks P2-DOM-01a, P2-DOM-01f).

Covers:
- DeltaOp StrEnum membership and value round-trip
- DeltaBase frozen behaviour and extra-field rejection
- DeltaBase construction with ObjectRef / QualifiedName target
- DeltaBase.sort_key stable ordering contract (top-level and sub-objects)
- DeltaBase.sort_key collision-freedom for sub-objects on different parents
- DeltaSet construction, iteration, len, containment
- DeltaSet.from_iterable alternative constructor (accepts any Iterable)
- DeltaSet lookup helpers: by_op, by_target, is_empty
- DeltaSet JSON round-trip (lossless: concrete subclass and payload preserved
  via the kind-discriminated Delta union introduced in P2-DOM-01f)
- DeltaSet model_dump shape
- Package-level re-export via ``from pgschemadiff.domain.delta import ...``

Note: DeltaSet.deltas is typed as tuple[Delta, ...] (the global discriminated
union) since P2-DOM-01f.  Tests that exercise DeltaSet must use REAL concrete
delta subclasses — the private _CreateDelta/_DropDelta/_AlterDelta test stubs
are still used for DeltaBase-only tests (sort_key, equality, immutability) but
are NOT stored in DeltaSet instances.
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.delta import DeltaBase, DeltaOp, DeltaSet
from pgschemadiff.domain.delta.schema import AlterExtension, CreateSchema, DropSchema
from pgschemadiff.domain.delta.table import AlterTableAttrs
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema

# ---------------------------------------------------------------------------
# Concrete test subclasses for DeltaBase-only tests (NOT stored in DeltaSet)
# These are used exclusively for sort_key, equality, immutability tests where
# we want minimal delta objects without constructing full domain aggregates.
# ---------------------------------------------------------------------------


class _CreateDelta(DeltaBase):
    """Minimal concrete subclass for CREATE operations used in DeltaBase tests."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE


class _DropDelta(DeltaBase):
    """Minimal concrete subclass for DROP operations used in DeltaBase tests."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP


class _AlterDelta(DeltaBase):
    """Minimal concrete subclass for ALTER operations used in DeltaBase tests."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER


# ---------------------------------------------------------------------------
# Shared helpers — produce real domain aggregates
# ---------------------------------------------------------------------------


def _schema_ref(namespace: str = "public", name: str = "public") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _schema(namespace: str = "public", name: str = "public", owner: str = "postgres") -> Schema:
    ref = _schema_ref(namespace, name)
    return Schema(ref=ref, owner=owner)


def _extension_ref(name: str = "pgcrypto", namespace: str = "public") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.EXTENSION,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _extension(
    name: str = "pgcrypto",
    version: str = "1.3",
    namespace: str = "public",
) -> Extension:
    ref = _extension_ref(name, namespace)
    return Extension(ref=ref, version=version)


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
    return _schema_ref()


@pytest.fixture
def ext_ref() -> ObjectRef:
    return _extension_ref()


@pytest.fixture
def index_ref() -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace="myns", name="users_pkey"),
    )


# Real concrete deltas for DeltaBase-only tests (sort_key, equality etc.)
@pytest.fixture
def create_delta_base(table_ref: ObjectRef) -> _CreateDelta:
    return _CreateDelta(target=table_ref)


@pytest.fixture
def drop_delta_base(table_ref: ObjectRef) -> _DropDelta:
    return _DropDelta(target=table_ref)


@pytest.fixture
def alter_delta_base(index_ref: ObjectRef) -> _AlterDelta:
    return _AlterDelta(target=index_ref)


# Real concrete deltas for DeltaSet tests (must be in the Delta union)


@pytest.fixture
def create_delta(schema_ref: ObjectRef) -> CreateSchema:
    """CREATE op delta on a schema ref (op=CREATE, kind="create_schema")."""
    s = Schema(ref=schema_ref, owner="postgres")
    return CreateSchema(target=schema_ref, pg_schema=s)


@pytest.fixture
def drop_delta(schema_ref: ObjectRef) -> DropSchema:
    """DROP op delta on a schema ref (op=DROP, kind="drop_schema")."""
    s = Schema(ref=schema_ref, owner="postgres")
    return DropSchema(target=schema_ref, pg_schema=s)


@pytest.fixture
def alter_delta(ext_ref: ObjectRef) -> AlterExtension:
    """ALTER op delta on an extension ref (op=ALTER, kind="alter_extension")."""
    return AlterExtension(target=ext_ref, new_version="2.0")


@pytest.fixture
def alter_table_delta(table_ref: ObjectRef) -> AlterTableAttrs:
    """ALTER op delta on a table ref, used for by_target tests."""
    return AlterTableAttrs(target=table_ref, new_owner="alice")


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
def test_delta_base_is_frozen(create_delta_base: _CreateDelta, table_ref: ObjectRef) -> None:
    """Mutation of any field on a frozen delta must raise ValidationError."""
    other_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="other", name="orders"),
    )
    with pytest.raises(ValidationError):
        create_delta_base.target = other_ref  # type: ignore[misc]


@pytest.mark.unit
def test_delta_base_op_is_frozen(create_delta_base: _CreateDelta) -> None:
    with pytest.raises(ValidationError):
        create_delta_base.op = DeltaOp.CREATE  # type: ignore[misc]


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
def test_delta_base_sort_key_structure_top_level(create_delta_base: _CreateDelta) -> None:
    """sort_key for a top-level object is a 3-tuple (namespace, object_name, op_value)."""
    key = create_delta_base.sort_key
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
# DeltaSet construction  (uses real concrete deltas from the Delta union)
# ===========================================================================


@pytest.mark.unit
def test_delta_set_empty_by_default() -> None:
    ds = DeltaSet()
    assert len(ds) == 0
    assert ds.is_empty()


@pytest.mark.unit
def test_delta_set_with_deltas(
    create_delta: CreateSchema,
    drop_delta: DropSchema,
) -> None:
    ds = DeltaSet(deltas=(create_delta, drop_delta))
    assert len(ds) == 2
    assert not ds.is_empty()


@pytest.mark.unit
def test_delta_set_from_iterable(
    create_delta: CreateSchema,
    drop_delta: DropSchema,
) -> None:
    ds = DeltaSet.from_iterable([create_delta, drop_delta])
    assert len(ds) == 2


@pytest.mark.unit
def test_delta_set_from_empty_iterable() -> None:
    ds = DeltaSet.from_iterable([])
    assert ds.is_empty()


@pytest.mark.unit
def test_delta_set_from_iterable_accepts_tuple(
    create_delta: CreateSchema,
    drop_delta: DropSchema,
) -> None:
    """from_iterable must accept tuples (and any Iterable), not just lists."""
    ds = DeltaSet.from_iterable((create_delta, drop_delta))
    assert len(ds) == 2


@pytest.mark.unit
def test_delta_set_from_iterable_accepts_generator() -> None:
    """from_iterable must accept generator expressions."""
    schema_ref = _schema_ref("public", "public")
    s = Schema(ref=schema_ref, owner="postgres")
    ds = DeltaSet.from_iterable(CreateSchema(target=schema_ref, pg_schema=s) for _ in range(2))
    assert len(ds) == 2


# ===========================================================================
# DeltaSet iteration
# ===========================================================================


@pytest.mark.unit
def test_delta_set_iteration(
    create_delta: CreateSchema,
    drop_delta: DropSchema,
) -> None:
    ds = DeltaSet(deltas=(create_delta, drop_delta))
    collected = list(ds)
    assert collected == [create_delta, drop_delta]


@pytest.mark.unit
def test_delta_set_preserves_order(
    create_delta: CreateSchema,
    alter_delta: AlterExtension,
    drop_delta: DropSchema,
) -> None:
    """DeltaSet must preserve insertion order."""
    ds = DeltaSet(deltas=(create_delta, alter_delta, drop_delta))
    assert list(ds) == [create_delta, alter_delta, drop_delta]


# ===========================================================================
# DeltaSet containment
# ===========================================================================


@pytest.mark.unit
def test_delta_set_containment(
    create_delta: CreateSchema,
    drop_delta: DropSchema,
) -> None:
    ds = DeltaSet(deltas=(create_delta,))
    assert create_delta in ds
    assert drop_delta not in ds


# ===========================================================================
# DeltaSet — frozen (immutability)
# ===========================================================================


@pytest.mark.unit
def test_delta_set_is_frozen(create_delta: CreateSchema) -> None:
    ds = DeltaSet(deltas=(create_delta,))
    with pytest.raises(ValidationError):
        ds.deltas = ()  # type: ignore[misc]


@pytest.mark.unit
def test_delta_set_rejects_extra_fields(create_delta: CreateSchema) -> None:
    with pytest.raises(ValidationError):
        DeltaSet(deltas=(create_delta,), extra_field="oops")  # type: ignore[call-arg]


# ===========================================================================
# DeltaSet — lookup helpers
# ===========================================================================


@pytest.mark.unit
def test_delta_set_by_op_filters_correctly(
    create_delta: CreateSchema,
    drop_delta: DropSchema,
    alter_delta: AlterExtension,
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
    create_delta: CreateSchema,
) -> None:
    ds = DeltaSet(deltas=(create_delta,))
    assert ds.by_op(DeltaOp.DROP) == ()


@pytest.mark.unit
def test_delta_set_by_target_filters_correctly(
    schema_ref: ObjectRef,
    ext_ref: ObjectRef,
    create_delta: CreateSchema,  # targets schema_ref (CREATE)
    drop_delta: DropSchema,  # targets schema_ref (DROP)
    alter_delta: AlterExtension,  # targets ext_ref (ALTER)
) -> None:
    ds = DeltaSet(deltas=(create_delta, drop_delta, alter_delta))
    schema_deltas = ds.by_target(schema_ref)
    ext_deltas = ds.by_target(ext_ref)
    assert create_delta in schema_deltas
    assert drop_delta in schema_deltas
    assert alter_delta not in schema_deltas
    assert alter_delta in ext_deltas
    assert len(schema_deltas) == 2
    assert len(ext_deltas) == 1


@pytest.mark.unit
def test_delta_set_by_target_returns_empty_when_no_match(
    create_delta: CreateSchema,
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
    create_delta: CreateSchema,
    drop_delta: DropSchema,
) -> None:
    ds_a = DeltaSet(deltas=(create_delta, drop_delta))
    ds_b = DeltaSet(deltas=(create_delta, drop_delta))
    assert ds_a == ds_b
    assert hash(ds_a) == hash(ds_b)


@pytest.mark.unit
def test_delta_set_inequality_different_order(
    create_delta: CreateSchema,
    drop_delta: DropSchema,
) -> None:
    ds_a = DeltaSet(deltas=(create_delta, drop_delta))
    ds_b = DeltaSet(deltas=(drop_delta, create_delta))
    assert ds_a != ds_b


# ===========================================================================
# DeltaSet — JSON round-trip (lossless since P2-DOM-01f)
# ===========================================================================


@pytest.mark.unit
def test_delta_set_json_round_trip_preserves_subclass() -> None:
    """DeltaSet JSON round-trip preserves the concrete subclass type and payload.

    Since P2-DOM-01f, DeltaSet.deltas is typed as tuple[Delta, ...] where
    Delta is the kind-discriminated global union.  A model_dump_json() ->
    model_validate_json() round-trip is now LOSSLESS: the concrete subclass
    (e.g. AlterTableAttrs) AND its payload (new_owner) survive serialisation.
    """
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="orders"),
    )
    original = AlterTableAttrs(target=table_ref, new_owner="alice")
    ds = DeltaSet(deltas=(original,))

    payload = ds.model_dump_json()
    restored = DeltaSet.model_validate_json(payload)

    restored_delta = next(iter(restored))
    # The concrete subclass type is preserved (was lossy before P2-DOM-01f).
    assert type(restored_delta) is AlterTableAttrs
    assert restored_delta.op == DeltaOp.ALTER
    assert restored_delta.target == table_ref
    # Payload field is preserved.
    assert isinstance(restored_delta, AlterTableAttrs)
    assert restored_delta.new_owner == "alice"


@pytest.mark.unit
def test_delta_set_json_round_trip_multiple_kinds() -> None:
    """DeltaSet JSON round-trip with mixed concrete delta kinds is lossless."""
    schema_ref = _schema_ref("myns", "myns")
    s = Schema(ref=schema_ref, owner="alice")
    ext_ref = _extension_ref("postgis", "myns")

    create = CreateSchema(target=schema_ref, pg_schema=s)
    drop_ext = AlterExtension(target=ext_ref, new_version="3.5")

    ds = DeltaSet(deltas=(create, drop_ext))
    restored = DeltaSet.model_validate_json(ds.model_dump_json())

    restored_list = list(restored)
    assert type(restored_list[0]) is CreateSchema
    assert type(restored_list[1]) is AlterExtension
    assert isinstance(restored_list[0], CreateSchema)
    assert restored_list[0].pg_schema.owner == "alice"
    assert isinstance(restored_list[1], AlterExtension)
    assert restored_list[1].new_version == "3.5"


@pytest.mark.unit
def test_delta_set_model_dump_shape(create_delta: CreateSchema) -> None:
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
# DeltaSet — rejects non-Delta objects
# ===========================================================================


@pytest.mark.unit
def test_delta_set_rejects_bare_delta_base() -> None:
    """DeltaSet.deltas = tuple[Delta, ...] rejects bare DeltaBase (no 'kind' field)."""
    ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )
    bare = DeltaBase(op=DeltaOp.CREATE, target=ref)
    with pytest.raises(ValidationError):
        DeltaSet(deltas=(bare,))  # type: ignore[arg-type]


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
