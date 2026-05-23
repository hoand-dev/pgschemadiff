"""Unit tests for ``pgschemadiff.domain.identity`` (task P1-DOM-01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.identity import (
    SUB_OBJECT_KINDS,
    ObjectKind,
    ObjectRef,
    QualifiedName,
)

# ---------------------------------------------------------------------------
# ObjectKind
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_object_kind_is_str_enum() -> None:
    assert isinstance(ObjectKind.TABLE, str)
    assert ObjectKind.TABLE.value == "table"
    assert ObjectKind("materialized_view") is ObjectKind.MATERIALIZED_VIEW


@pytest.mark.unit
def test_object_kind_round_trips_through_string() -> None:
    for kind in ObjectKind:
        assert ObjectKind(str(kind)) is kind


@pytest.mark.unit
def test_sub_object_kinds_exact_membership() -> None:
    assert (
        frozenset(
            {
                ObjectKind.COLUMN,
                ObjectKind.CONSTRAINT,
                ObjectKind.TRIGGER,
                ObjectKind.POLICY,
            }
        )
        == SUB_OBJECT_KINDS
    )


# ---------------------------------------------------------------------------
# QualifiedName
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qualified_name_basic_fqn() -> None:
    q = QualifiedName(namespace="public", name="users")
    assert q.fqn == '"public"."users"'
    assert str(q) == '"public"."users"'


@pytest.mark.unit
def test_qualified_name_quotes_embedded_double_quotes() -> None:
    q = QualifiedName(namespace="weird", name='evil"name')
    assert q.fqn == '"weird"."evil""name"'


@pytest.mark.unit
def test_qualified_name_preserves_spaces_and_case_inside_quotes() -> None:
    q = QualifiedName(namespace="MySchema", name="my table")
    assert q.fqn == '"MySchema"."my table"'


@pytest.mark.unit
def test_qualified_name_rejects_empty_schema() -> None:
    with pytest.raises(ValidationError):
        QualifiedName(namespace="", name="users")


@pytest.mark.unit
def test_qualified_name_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        QualifiedName(namespace="public", name="")


@pytest.mark.unit
def test_qualified_name_is_frozen() -> None:
    q = QualifiedName(namespace="public", name="users")
    with pytest.raises(ValidationError):
        q.namespace = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_qualified_name_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        QualifiedName(namespace="public", name="users", bogus=1)  # type: ignore[call-arg]


@pytest.mark.unit
def test_qualified_name_equality_and_hash() -> None:
    a = QualifiedName(namespace="public", name="users")
    b = QualifiedName(namespace="public", name="users")
    c = QualifiedName(namespace="public", name="orders")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    assert {a, b, c} == {a, c}


@pytest.mark.unit
def test_qualified_name_json_round_trip() -> None:
    a = QualifiedName(namespace="public", name="users")
    payload = a.model_dump_json()
    b = QualifiedName.model_validate_json(payload)
    assert a == b


# ---------------------------------------------------------------------------
# ObjectRef — top-level
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_object_ref_table_constructs() -> None:
    ref = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="users"))
    assert ref.parent is None
    assert ref.arg_signature is None


@pytest.mark.unit
def test_object_ref_index_constructs() -> None:
    ref = ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace="public", name="users_pkey"),
    )
    assert ref.parent is None


@pytest.mark.unit
def test_object_ref_top_level_rejects_parent() -> None:
    parent = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="users"))
    with pytest.raises(ValidationError):
        ObjectRef(
            kind=ObjectKind.TABLE,
            qname=QualifiedName(namespace="public", name="orders"),
            parent=parent,
        )


# ---------------------------------------------------------------------------
# ObjectRef — sub-object invariants
# ---------------------------------------------------------------------------


@pytest.fixture
def parent_table() -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="users"))


@pytest.mark.unit
def test_object_ref_column_requires_parent() -> None:
    with pytest.raises(ValidationError):
        ObjectRef(kind=ObjectKind.COLUMN, qname=QualifiedName(namespace="public", name="email"))


@pytest.mark.unit
def test_object_ref_column_with_table_parent_ok(parent_table: ObjectRef) -> None:
    ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="email"),
        parent=parent_table,
    )
    assert ref.parent is parent_table


@pytest.mark.unit
def test_object_ref_column_rejects_non_table_parent() -> None:
    view_parent = ObjectRef(
        kind=ObjectKind.VIEW, qname=QualifiedName(namespace="public", name="v_users")
    )
    with pytest.raises(ValidationError):
        ObjectRef(
            kind=ObjectKind.COLUMN,
            qname=QualifiedName(namespace="public", name="email"),
            parent=view_parent,
        )


@pytest.mark.parametrize("kind", sorted(SUB_OBJECT_KINDS, key=str))
@pytest.mark.unit
def test_every_sub_object_kind_requires_table_parent(
    kind: ObjectKind, parent_table: ObjectRef
) -> None:
    ref = ObjectRef(
        kind=kind,
        qname=QualifiedName(namespace="public", name="x"),
        parent=parent_table,
    )
    assert ref.parent is parent_table


# ---------------------------------------------------------------------------
# ObjectRef — arg_signature invariants
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_object_ref_function_requires_arg_signature() -> None:
    with pytest.raises(ValidationError):
        ObjectRef(
            kind=ObjectKind.FUNCTION,
            qname=QualifiedName(namespace="public", name="now_plus"),
        )


@pytest.mark.unit
def test_object_ref_function_with_arg_signature_ok() -> None:
    ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="public", name="add"),
        arg_signature=("integer", "integer"),
    )
    assert ref.arg_signature == ("integer", "integer")


@pytest.mark.unit
def test_object_ref_procedure_requires_arg_signature() -> None:
    with pytest.raises(ValidationError):
        ObjectRef(kind=ObjectKind.PROCEDURE, qname=QualifiedName(namespace="public", name="do_x"))


@pytest.mark.unit
def test_object_ref_table_rejects_arg_signature() -> None:
    with pytest.raises(ValidationError):
        ObjectRef(
            kind=ObjectKind.TABLE,
            qname=QualifiedName(namespace="public", name="users"),
            arg_signature=("integer",),
        )


# ---------------------------------------------------------------------------
# ObjectRef — value identity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_object_ref_is_frozen() -> None:
    ref = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="users"))
    with pytest.raises(ValidationError):
        ref.kind = ObjectKind.VIEW  # type: ignore[misc]


@pytest.mark.unit
def test_object_ref_equality_and_hash() -> None:
    a = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="users"))
    b = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="users"))
    c = ObjectRef(kind=ObjectKind.VIEW, qname=QualifiedName(namespace="public", name="users"))
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    assert {a, b, c} == {a, c}


@pytest.mark.unit
def test_object_ref_json_round_trip() -> None:
    parent = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="users"))
    ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="email"),
        parent=parent,
    )
    payload = ref.model_dump_json()
    restored = ObjectRef.model_validate_json(payload)
    assert restored == ref
    assert restored.parent == parent
