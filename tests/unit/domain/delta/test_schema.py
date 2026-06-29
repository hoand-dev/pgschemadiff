"""Unit tests for ``pgschemadiff.domain.delta.schema`` (task P2-DOM-01f).

Covers:
- Construction of each concrete schema/extension delta subclass
- ``op`` Literal is fixed/auto-defaulted and rejects wrong ops
- ``kind`` Literal is fixed/auto-defaulted and is the union discriminator
- Frozen behaviour (``frozen=True``) and ``extra="forbid"``
- All model validators (happy + raising paths):
  - CreateSchema: target.kind must be SCHEMA and target == schema.ref
  - DropSchema: target must equal schema.ref
  - CreateExtension: target.kind must be EXTENSION and target == extension.ref
  - DropExtension: target must equal extension.ref
  - AlterExtension: target.kind must be EXTENSION; at least one new_* non-None
- ``sort_key`` shape for top-level objects: ``(namespace, name, op_value)``
  (3-tuple because neither SCHEMA nor EXTENSION is in SUB_OBJECT_KINDS)
- SchemaDelta discriminated-union round-trip via ``TypeAdapter[SchemaDelta]``
- ExtensionDelta discriminated-union round-trip via ``TypeAdapter[ExtensionDelta]``
- Global ``Delta`` union TypeAdapter: validates one delta per category by kind
  and round-trips losslessly (capstone assertion for the whole delta foundation)
- Package-level re-export (``from pgschemadiff.domain.delta import …``)
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

import pgschemadiff.domain.delta as _delta_pkg
from pgschemadiff.domain.constraint import PrimaryKeyConstraint
from pgschemadiff.domain.delta import (
    AddConstraint,
    AlterExtension,
    AlterTableAttrs,
    CreateExtension,
    CreateIndex,
    CreateSchema,
    Delta,
    DropExtension,
    DropSchema,
    ExtensionDelta,
    SchemaDelta,
)
from pgschemadiff.domain.delta.base import DeltaOp
from pgschemadiff.domain.delta.column import SetColumnNullability
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod
from pgschemadiff.domain.schema import Schema

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _schema_ref(namespace: str = "public", name: str = "public") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _schema(
    namespace: str = "public",
    name: str = "public",
    owner: str = "postgres",
) -> Schema:
    return Schema(ref=_schema_ref(namespace, name), owner=owner)


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
    return Extension(ref=_extension_ref(name, namespace), version=version)


# --- Pytest fixtures ---


@pytest.fixture
def schema_ref() -> ObjectRef:
    return _schema_ref()


@pytest.fixture
def schema_obj() -> Schema:
    return _schema()


@pytest.fixture
def ext_ref() -> ObjectRef:
    return _extension_ref()


@pytest.fixture
def ext_obj() -> Extension:
    return _extension()


# ---------------------------------------------------------------------------
# TypeAdapters
# ---------------------------------------------------------------------------

_SCHEMA_DELTA_TA: TypeAdapter[SchemaDelta] = TypeAdapter(SchemaDelta)
_EXT_DELTA_TA: TypeAdapter[ExtensionDelta] = TypeAdapter(ExtensionDelta)
_DELTA_TA: TypeAdapter[Delta] = TypeAdapter(Delta)


# ===========================================================================
# CreateSchema
# ===========================================================================


@pytest.mark.unit
def test_create_schema_constructs(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    delta = CreateSchema(target=schema_ref, pg_schema=schema_obj)
    assert delta.op is DeltaOp.CREATE
    assert delta.kind == "create_schema"
    assert delta.pg_schema is schema_obj
    assert delta.target is schema_ref


@pytest.mark.unit
def test_create_schema_op_defaults_to_create(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    """op defaults to DeltaOp.CREATE; callers need not pass it."""
    delta = CreateSchema(target=schema_ref, pg_schema=schema_obj)
    assert delta.op is DeltaOp.CREATE


@pytest.mark.unit
def test_create_schema_kind_defaults(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    """kind defaults to 'create_schema'; callers need not pass it."""
    delta = CreateSchema(target=schema_ref, pg_schema=schema_obj)
    assert delta.kind == "create_schema"


@pytest.mark.unit
def test_create_schema_rejects_wrong_op(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    """Passing op=DROP to CreateSchema must raise ValidationError."""
    with pytest.raises(ValidationError):
        CreateSchema(target=schema_ref, schema=schema_obj, op=DeltaOp.DROP)  # type: ignore[call-arg, arg-type]


@pytest.mark.unit
def test_create_schema_is_frozen(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    delta = CreateSchema(target=schema_ref, pg_schema=schema_obj)
    with pytest.raises(ValidationError):
        delta.pg_schema = schema_obj  # type: ignore[misc]


@pytest.mark.unit
def test_create_schema_rejects_extra_fields(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    with pytest.raises(ValidationError):
        CreateSchema(target=schema_ref, schema=schema_obj, unexpected="oops")  # type: ignore[call-arg]


@pytest.mark.unit
def test_create_schema_validator_rejects_wrong_target_kind() -> None:
    """target.kind must be SCHEMA; a TABLE ref must be rejected."""
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )
    schema_obj = _schema()
    with pytest.raises(ValidationError, match=r"ObjectKind\.SCHEMA"):
        CreateSchema(target=table_ref, pg_schema=schema_obj)


@pytest.mark.unit
def test_create_schema_validator_rejects_mismatched_target() -> None:
    """target must equal schema.ref; a different schema ref must be rejected."""
    ref_a = _schema_ref("public", "public")
    ref_b = _schema_ref("other", "other")
    schema_obj = Schema(ref=ref_b, owner="postgres")
    with pytest.raises(ValidationError, match=r"must equal schema\.ref"):
        CreateSchema(target=ref_a, pg_schema=schema_obj)


@pytest.mark.unit
def test_create_schema_sort_key(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    """sort_key is a 3-tuple (namespace, name, 'create') for top-level objects."""
    delta = CreateSchema(target=schema_ref, pg_schema=schema_obj)
    assert delta.sort_key == ("public", "public", "create")


@pytest.mark.unit
def test_create_schema_sort_key_non_public() -> None:
    """sort_key uses the actual namespace and name."""
    ref = _schema_ref("reporting", "reporting")
    s = Schema(ref=ref, owner="alice")
    delta = CreateSchema(target=ref, pg_schema=s)
    assert delta.sort_key == ("reporting", "reporting", "create")


# ===========================================================================
# DropSchema
# ===========================================================================


@pytest.mark.unit
def test_drop_schema_constructs(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    delta = DropSchema(target=schema_ref, pg_schema=schema_obj)
    assert delta.op is DeltaOp.DROP
    assert delta.kind == "drop_schema"
    assert delta.pg_schema is schema_obj
    assert delta.target is schema_ref


@pytest.mark.unit
def test_drop_schema_op_defaults_to_drop(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    delta = DropSchema(target=schema_ref, pg_schema=schema_obj)
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_drop_schema_kind_defaults(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    delta = DropSchema(target=schema_ref, pg_schema=schema_obj)
    assert delta.kind == "drop_schema"


@pytest.mark.unit
def test_drop_schema_rejects_wrong_op(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    with pytest.raises(ValidationError):
        DropSchema(target=schema_ref, schema=schema_obj, op=DeltaOp.CREATE)  # type: ignore[call-arg, arg-type]


@pytest.mark.unit
def test_drop_schema_is_frozen(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    delta = DropSchema(target=schema_ref, pg_schema=schema_obj)
    with pytest.raises(ValidationError):
        delta.pg_schema = schema_obj  # type: ignore[misc]


@pytest.mark.unit
def test_drop_schema_validator_rejects_mismatched_target() -> None:
    """target must equal schema.ref."""
    ref_a = _schema_ref("public", "public")
    ref_b = _schema_ref("other", "other")
    schema_obj = Schema(ref=ref_b, owner="postgres")
    with pytest.raises(ValidationError, match=r"must equal schema\.ref"):
        DropSchema(target=ref_a, pg_schema=schema_obj)


@pytest.mark.unit
def test_drop_schema_sort_key(schema_ref: ObjectRef, schema_obj: Schema) -> None:
    delta = DropSchema(target=schema_ref, pg_schema=schema_obj)
    assert delta.sort_key == ("public", "public", "drop")


# ===========================================================================
# CreateExtension
# ===========================================================================


@pytest.mark.unit
def test_create_extension_constructs(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = CreateExtension(target=ext_ref, extension=ext_obj)
    assert delta.op is DeltaOp.CREATE
    assert delta.kind == "create_extension"
    assert delta.extension is ext_obj
    assert delta.target is ext_ref


@pytest.mark.unit
def test_create_extension_op_defaults_to_create(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = CreateExtension(target=ext_ref, extension=ext_obj)
    assert delta.op is DeltaOp.CREATE


@pytest.mark.unit
def test_create_extension_kind_defaults(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = CreateExtension(target=ext_ref, extension=ext_obj)
    assert delta.kind == "create_extension"


@pytest.mark.unit
def test_create_extension_rejects_wrong_op(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    with pytest.raises(ValidationError):
        CreateExtension(target=ext_ref, extension=ext_obj, op=DeltaOp.DROP)  # type: ignore[arg-type]


@pytest.mark.unit
def test_create_extension_is_frozen(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = CreateExtension(target=ext_ref, extension=ext_obj)
    with pytest.raises(ValidationError):
        delta.extension = ext_obj  # type: ignore[misc]


@pytest.mark.unit
def test_create_extension_rejects_extra_fields(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    with pytest.raises(ValidationError):
        CreateExtension(target=ext_ref, extension=ext_obj, unexpected="oops")  # type: ignore[call-arg]


@pytest.mark.unit
def test_create_extension_validator_rejects_wrong_target_kind() -> None:
    """target.kind must be EXTENSION; a TABLE ref must be rejected."""
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="users"),
    )
    ext_obj = _extension()
    with pytest.raises(ValidationError, match=r"ObjectKind\.EXTENSION"):
        CreateExtension(target=table_ref, extension=ext_obj)


@pytest.mark.unit
def test_create_extension_validator_rejects_mismatched_target() -> None:
    """target must equal extension.ref."""
    ref_a = _extension_ref("pgcrypto")
    ref_b = _extension_ref("postgis")
    ext_obj = Extension(ref=ref_b, version="3.4")
    with pytest.raises(ValidationError, match=r"must equal extension\.ref"):
        CreateExtension(target=ref_a, extension=ext_obj)


@pytest.mark.unit
def test_create_extension_sort_key(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    """sort_key is a 3-tuple (namespace, extension_name, 'create')."""
    delta = CreateExtension(target=ext_ref, extension=ext_obj)
    assert delta.sort_key == ("public", "pgcrypto", "create")


# ===========================================================================
# DropExtension
# ===========================================================================


@pytest.mark.unit
def test_drop_extension_constructs(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = DropExtension(target=ext_ref, extension=ext_obj)
    assert delta.op is DeltaOp.DROP
    assert delta.kind == "drop_extension"
    assert delta.extension is ext_obj
    assert delta.target is ext_ref


@pytest.mark.unit
def test_drop_extension_op_defaults_to_drop(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = DropExtension(target=ext_ref, extension=ext_obj)
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_drop_extension_kind_defaults(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = DropExtension(target=ext_ref, extension=ext_obj)
    assert delta.kind == "drop_extension"


@pytest.mark.unit
def test_drop_extension_rejects_wrong_op(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    with pytest.raises(ValidationError):
        DropExtension(target=ext_ref, extension=ext_obj, op=DeltaOp.CREATE)  # type: ignore[arg-type]


@pytest.mark.unit
def test_drop_extension_is_frozen(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = DropExtension(target=ext_ref, extension=ext_obj)
    with pytest.raises(ValidationError):
        delta.extension = ext_obj  # type: ignore[misc]


@pytest.mark.unit
def test_drop_extension_validator_rejects_mismatched_target() -> None:
    """target must equal extension.ref."""
    ref_a = _extension_ref("pgcrypto")
    ref_b = _extension_ref("postgis")
    ext_obj = Extension(ref=ref_b, version="3.4")
    with pytest.raises(ValidationError, match=r"must equal extension\.ref"):
        DropExtension(target=ref_a, extension=ext_obj)


@pytest.mark.unit
def test_drop_extension_sort_key(ext_ref: ObjectRef, ext_obj: Extension) -> None:
    delta = DropExtension(target=ext_ref, extension=ext_obj)
    assert delta.sort_key == ("public", "pgcrypto", "drop")


# ===========================================================================
# AlterExtension
# ===========================================================================


@pytest.mark.unit
def test_alter_extension_new_version(ext_ref: ObjectRef) -> None:
    delta = AlterExtension(target=ext_ref, new_version="2.0")
    assert delta.op is DeltaOp.ALTER
    assert delta.kind == "alter_extension"
    assert delta.new_version == "2.0"
    assert delta.new_schema is None


@pytest.mark.unit
def test_alter_extension_new_schema(ext_ref: ObjectRef) -> None:
    delta = AlterExtension(target=ext_ref, new_schema="reporting")
    assert delta.new_schema == "reporting"
    assert delta.new_version is None


@pytest.mark.unit
def test_alter_extension_both_fields(ext_ref: ObjectRef) -> None:
    delta = AlterExtension(target=ext_ref, new_version="2.0", new_schema="reporting")
    assert delta.new_version == "2.0"
    assert delta.new_schema == "reporting"


@pytest.mark.unit
def test_alter_extension_op_defaults_to_alter(ext_ref: ObjectRef) -> None:
    delta = AlterExtension(target=ext_ref, new_version="2.0")
    assert delta.op is DeltaOp.ALTER


@pytest.mark.unit
def test_alter_extension_kind_defaults(ext_ref: ObjectRef) -> None:
    delta = AlterExtension(target=ext_ref, new_version="2.0")
    assert delta.kind == "alter_extension"


@pytest.mark.unit
def test_alter_extension_rejects_wrong_op(ext_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        AlterExtension(target=ext_ref, new_version="2.0", op=DeltaOp.DROP)  # type: ignore[arg-type]


@pytest.mark.unit
def test_alter_extension_is_frozen(ext_ref: ObjectRef) -> None:
    delta = AlterExtension(target=ext_ref, new_version="2.0")
    with pytest.raises(ValidationError):
        delta.new_version = "3.0"  # type: ignore[misc]


@pytest.mark.unit
def test_alter_extension_rejects_extra_fields(ext_ref: ObjectRef) -> None:
    with pytest.raises(ValidationError):
        AlterExtension(target=ext_ref, new_version="2.0", unexpected="oops")  # type: ignore[call-arg]


@pytest.mark.unit
def test_alter_extension_validator_rejects_wrong_target_kind() -> None:
    """target.kind must be EXTENSION; a SCHEMA ref must be rejected."""
    schema_ref = _schema_ref()
    with pytest.raises(ValidationError, match=r"ObjectKind\.EXTENSION"):
        AlterExtension(target=schema_ref, new_version="2.0")


@pytest.mark.unit
def test_alter_extension_validator_rejects_all_none(ext_ref: ObjectRef) -> None:
    """Both new_version and new_schema being None is a no-op; must be rejected."""
    with pytest.raises(ValidationError, match=r"no-op"):
        AlterExtension(target=ext_ref)


@pytest.mark.unit
def test_alter_extension_sort_key(ext_ref: ObjectRef) -> None:
    """sort_key is a 3-tuple (namespace, extension_name, 'alter')."""
    delta = AlterExtension(target=ext_ref, new_version="2.0")
    assert delta.sort_key == ("public", "pgcrypto", "alter")


# ===========================================================================
# SchemaDelta — discriminated union via TypeAdapter
# ===========================================================================


@pytest.mark.unit
def test_schema_delta_type_adapter_routes_create_schema(
    schema_ref: ObjectRef, schema_obj: Schema
) -> None:
    """TypeAdapter[SchemaDelta] instantiates CreateSchema from kind='create_schema'."""
    data = {
        "kind": "create_schema",
        "op": "create",
        "target": schema_ref.model_dump(),
        "pg_schema": schema_obj.model_dump(),
    }
    delta = _SCHEMA_DELTA_TA.validate_python(data)
    assert type(delta) is CreateSchema
    assert delta.op is DeltaOp.CREATE


@pytest.mark.unit
def test_schema_delta_type_adapter_routes_drop_schema(
    schema_ref: ObjectRef, schema_obj: Schema
) -> None:
    """TypeAdapter[SchemaDelta] instantiates DropSchema from kind='drop_schema'."""
    data = {
        "kind": "drop_schema",
        "op": "drop",
        "target": schema_ref.model_dump(),
        "pg_schema": schema_obj.model_dump(),
    }
    delta = _SCHEMA_DELTA_TA.validate_python(data)
    assert type(delta) is DropSchema
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_schema_delta_json_round_trip_create_schema(
    schema_ref: ObjectRef, schema_obj: Schema
) -> None:
    """CreateSchema survives dump_json + validate_json through SchemaDelta TypeAdapter."""
    original = CreateSchema(target=schema_ref, pg_schema=schema_obj)
    raw = _SCHEMA_DELTA_TA.dump_json(original)
    restored = _SCHEMA_DELTA_TA.validate_json(raw)
    assert type(restored) is CreateSchema
    assert restored == original


@pytest.mark.unit
def test_schema_delta_json_round_trip_drop_schema(
    schema_ref: ObjectRef, schema_obj: Schema
) -> None:
    original = DropSchema(target=schema_ref, pg_schema=schema_obj)
    raw = _SCHEMA_DELTA_TA.dump_json(original)
    restored = _SCHEMA_DELTA_TA.validate_json(raw)
    assert type(restored) is DropSchema
    assert restored == original


@pytest.mark.unit
def test_schema_delta_type_adapter_rejects_unknown_kind() -> None:
    """TypeAdapter[SchemaDelta] rejects a payload with an unknown 'kind' value."""
    data = {
        "kind": "create_table",
        "op": "create",
        "target": {
            "kind": "schema",
            "qname": {"namespace": "public", "name": "public"},
        },
    }
    with pytest.raises(ValidationError):
        _SCHEMA_DELTA_TA.validate_python(data)


# ===========================================================================
# ExtensionDelta — discriminated union via TypeAdapter
# ===========================================================================


@pytest.mark.unit
def test_extension_delta_type_adapter_routes_create_extension(
    ext_ref: ObjectRef, ext_obj: Extension
) -> None:
    data = {
        "kind": "create_extension",
        "op": "create",
        "target": ext_ref.model_dump(),
        "extension": ext_obj.model_dump(),
    }
    delta = _EXT_DELTA_TA.validate_python(data)
    assert type(delta) is CreateExtension
    assert delta.op is DeltaOp.CREATE


@pytest.mark.unit
def test_extension_delta_type_adapter_routes_drop_extension(
    ext_ref: ObjectRef, ext_obj: Extension
) -> None:
    data = {
        "kind": "drop_extension",
        "op": "drop",
        "target": ext_ref.model_dump(),
        "extension": ext_obj.model_dump(),
    }
    delta = _EXT_DELTA_TA.validate_python(data)
    assert type(delta) is DropExtension
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_extension_delta_type_adapter_routes_alter_extension(ext_ref: ObjectRef) -> None:
    data = {
        "kind": "alter_extension",
        "op": "alter",
        "target": ext_ref.model_dump(),
        "new_version": "2.0",
    }
    delta = _EXT_DELTA_TA.validate_python(data)
    assert type(delta) is AlterExtension
    assert delta.new_version == "2.0"


@pytest.mark.unit
def test_extension_delta_json_round_trip_create_extension(
    ext_ref: ObjectRef, ext_obj: Extension
) -> None:
    original = CreateExtension(target=ext_ref, extension=ext_obj)
    raw = _EXT_DELTA_TA.dump_json(original)
    restored = _EXT_DELTA_TA.validate_json(raw)
    assert type(restored) is CreateExtension
    assert restored == original


@pytest.mark.unit
def test_extension_delta_json_round_trip_alter_extension(ext_ref: ObjectRef) -> None:
    original = AlterExtension(target=ext_ref, new_version="3.1", new_schema="reporting")
    raw = _EXT_DELTA_TA.dump_json(original)
    restored = _EXT_DELTA_TA.validate_json(raw)
    assert type(restored) is AlterExtension
    assert restored.new_version == "3.1"
    assert restored.new_schema == "reporting"


# ===========================================================================
# Global Delta union — capstone assertion (P2-DOM-01f)
#
# Validates one delta from EACH of the six categories by kind and round-trips
# it losslessly through the global TypeAdapter[Delta].
# ===========================================================================


def _table_ref(namespace: str = "public", name: str = "users") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace=namespace, name=name))


def _index_ref(name: str = "users_pkey", namespace: str = "public") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.INDEX, qname=QualifiedName(namespace=namespace, name=name))


def _column_ref(
    col_name: str = "email",
    table_name: str = "users",
    namespace: str = "public",
) -> ObjectRef:
    parent = _table_ref(namespace, table_name)
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=namespace, name=col_name),
        parent=parent,
    )


def _constraint_ref(
    c_name: str = "users_pkey",
    table_name: str = "users",
    namespace: str = "public",
) -> ObjectRef:
    parent = _table_ref(namespace, table_name)
    return ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=namespace, name=c_name),
        parent=parent,
    )


@pytest.mark.unit
def test_global_delta_union_all_six_categories_round_trip_losslessly() -> None:
    """Global Delta union TypeAdapter: one delta per category — all lossless.

    This is the capstone assertion for the whole delta foundation (P2-DOM-01f).
    A TypeAdapter[Delta] validates and round-trips a concrete delta from each
    of the six object categories.  Type, payload, and target are all preserved.
    """
    # --- Category 1: Table ---
    table_ref = _table_ref()
    table_delta = AlterTableAttrs(target=table_ref, new_owner="alice")

    # --- Category 2: Column ---
    col_ref = _column_ref()
    col_delta = SetColumnNullability(target=col_ref, nullable=False)

    # --- Category 3: Index ---
    idx_ref = _index_ref()
    idx_delta = CreateIndex(
        target=idx_ref,
        index=Index(
            ref=idx_ref,
            table_ref=table_ref,
            method=IndexMethod.BTREE,
            key_columns=(IndexKeyColumn(column_name="id"),),
            unique=True,
        ),
    )

    # --- Category 4: Constraint ---
    constr_ref = _constraint_ref()
    pk = PrimaryKeyConstraint(name="users_pkey", columns=("id",))
    constr_delta = AddConstraint(target=constr_ref, constraint=pk)

    # --- Category 5: Schema ---
    sch_ref = _schema_ref()
    sch_obj = _schema()
    schema_delta = CreateSchema(target=sch_ref, pg_schema=sch_obj)

    # --- Category 6: Extension ---
    ext_ref_obj = _extension_ref()
    ext_delta = AlterExtension(target=ext_ref_obj, new_version="2.0")

    all_deltas: list[Delta] = [
        table_delta,
        col_delta,
        idx_delta,
        constr_delta,
        schema_delta,
        ext_delta,
    ]
    expected_types = [
        AlterTableAttrs,
        SetColumnNullability,
        CreateIndex,
        AddConstraint,
        CreateSchema,
        AlterExtension,
    ]

    for original, expected_type in zip(all_deltas, expected_types, strict=True):
        raw = _DELTA_TA.dump_json(original)
        restored = _DELTA_TA.validate_json(raw)
        assert type(restored) is expected_type, (
            f"Expected {expected_type.__name__}, got {type(restored).__name__} "
            f"for delta with kind={original.kind!r}"
        )
        assert restored == original, (  # type: ignore[unreachable]
            f"Round-trip not equal for {expected_type.__name__}: "
            f"original={original!r}, restored={restored!r}"
        )


@pytest.mark.unit
def test_global_delta_union_kind_create_schema() -> None:
    """TypeAdapter[Delta] routes 'create_schema' kind to CreateSchema."""
    sch_ref = _schema_ref()
    sch = _schema()
    original = CreateSchema(target=sch_ref, pg_schema=sch)
    raw = _DELTA_TA.dump_json(original)
    restored = _DELTA_TA.validate_json(raw)
    assert type(restored) is CreateSchema


@pytest.mark.unit
def test_global_delta_union_kind_drop_schema() -> None:
    """TypeAdapter[Delta] routes 'drop_schema' kind to DropSchema."""
    sch_ref = _schema_ref()
    sch = _schema()
    original = DropSchema(target=sch_ref, pg_schema=sch)
    raw = _DELTA_TA.dump_json(original)
    restored = _DELTA_TA.validate_json(raw)
    assert type(restored) is DropSchema


@pytest.mark.unit
def test_global_delta_union_kind_create_extension() -> None:
    """TypeAdapter[Delta] routes 'create_extension' kind to CreateExtension."""
    ext_ref = _extension_ref()
    ext = _extension()
    original = CreateExtension(target=ext_ref, extension=ext)
    raw = _DELTA_TA.dump_json(original)
    restored = _DELTA_TA.validate_json(raw)
    assert type(restored) is CreateExtension


@pytest.mark.unit
def test_global_delta_union_kind_drop_extension() -> None:
    """TypeAdapter[Delta] routes 'drop_extension' kind to DropExtension."""
    ext_ref = _extension_ref()
    ext = _extension()
    original = DropExtension(target=ext_ref, extension=ext)
    raw = _DELTA_TA.dump_json(original)
    restored = _DELTA_TA.validate_json(raw)
    assert type(restored) is DropExtension


@pytest.mark.unit
def test_global_delta_union_kind_alter_extension() -> None:
    """TypeAdapter[Delta] routes 'alter_extension' kind to AlterExtension."""
    ext_ref = _extension_ref()
    original = AlterExtension(target=ext_ref, new_schema="reporting")
    raw = _DELTA_TA.dump_json(original)
    restored = _DELTA_TA.validate_json(raw)
    assert type(restored) is AlterExtension
    assert isinstance(restored, AlterExtension)
    assert restored.new_schema == "reporting"


@pytest.mark.unit
def test_global_delta_union_rejects_unknown_kind() -> None:
    """TypeAdapter[Delta] rejects payloads with unknown 'kind' values."""
    data = {
        "kind": "totally_unknown_kind",
        "op": "create",
        "target": {
            "kind": "table",
            "qname": {"namespace": "public", "name": "users"},
        },
    }
    with pytest.raises(ValidationError):
        _DELTA_TA.validate_python(data)


# ===========================================================================
# Package-level re-export
# ===========================================================================


@pytest.mark.unit
def test_package_exports_create_schema() -> None:
    assert _delta_pkg.CreateSchema is CreateSchema


@pytest.mark.unit
def test_package_exports_drop_schema() -> None:
    assert _delta_pkg.DropSchema is DropSchema


@pytest.mark.unit
def test_package_exports_create_extension() -> None:
    assert _delta_pkg.CreateExtension is CreateExtension


@pytest.mark.unit
def test_package_exports_drop_extension() -> None:
    assert _delta_pkg.DropExtension is DropExtension


@pytest.mark.unit
def test_package_exports_alter_extension() -> None:
    assert _delta_pkg.AlterExtension is AlterExtension


@pytest.mark.unit
def test_package_exports_schema_delta() -> None:
    assert _delta_pkg.SchemaDelta is SchemaDelta


@pytest.mark.unit
def test_package_exports_extension_delta() -> None:
    assert _delta_pkg.ExtensionDelta is ExtensionDelta


@pytest.mark.unit
def test_package_exports_delta() -> None:
    assert _delta_pkg.Delta is Delta
