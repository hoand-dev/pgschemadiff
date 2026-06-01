"""Unit tests for ``pgschemadiff.domain.index`` (task P1-DOM-05)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod, NullsOrder, SortOrder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _index_ref(name: str, namespace: str = "public") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.INDEX, qname=QualifiedName(namespace=namespace, name=name))


def _table_ref(name: str, namespace: str = "public") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace=namespace, name=name))


# ---------------------------------------------------------------------------
# IndexMethod
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_method_values() -> None:
    assert IndexMethod.BTREE == "btree"
    assert IndexMethod.HASH == "hash"
    assert IndexMethod.GIST == "gist"
    assert IndexMethod.GIN == "gin"
    assert IndexMethod.BRIN == "brin"
    assert IndexMethod.SPGIST == "spgist"


@pytest.mark.unit
def test_index_method_round_trips() -> None:
    for m in IndexMethod:
        assert IndexMethod(str(m)) is m


# ---------------------------------------------------------------------------
# SortOrder / NullsOrder
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sort_order_values() -> None:
    assert SortOrder.ASC == "asc"
    assert SortOrder.DESC == "desc"


@pytest.mark.unit
def test_nulls_order_values() -> None:
    assert NullsOrder.FIRST == "first"
    assert NullsOrder.LAST == "last"


# ---------------------------------------------------------------------------
# IndexKeyColumn
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_key_column_by_name() -> None:
    key = IndexKeyColumn(column_name="email")
    assert key.column_name == "email"
    assert key.expression is None
    assert key.opclass is None
    assert key.sort_order is SortOrder.ASC
    assert key.nulls_order is None


@pytest.mark.unit
def test_index_key_column_by_expression() -> None:
    key = IndexKeyColumn(expression="lower(email)")
    assert key.expression == "lower(email)"
    assert key.column_name is None


@pytest.mark.unit
def test_index_key_column_neither_name_nor_expression_rejected() -> None:
    with pytest.raises(ValidationError, match="must specify either"):
        IndexKeyColumn()


@pytest.mark.unit
def test_index_key_column_both_name_and_expression_rejected() -> None:
    with pytest.raises(ValidationError, match="must not specify both"):
        IndexKeyColumn(column_name="x", expression="lower(x)")


@pytest.mark.unit
def test_index_key_column_with_full_options() -> None:
    key = IndexKeyColumn(
        column_name="name",
        opclass="text_pattern_ops",
        sort_order=SortOrder.DESC,
        nulls_order=NullsOrder.LAST,
    )
    assert key.opclass == "text_pattern_ops"
    assert key.sort_order is SortOrder.DESC
    assert key.nulls_order is NullsOrder.LAST


@pytest.mark.unit
def test_index_key_column_is_frozen() -> None:
    key = IndexKeyColumn(column_name="x")
    with pytest.raises(ValidationError):
        key.column_name = "y"  # type: ignore[misc]


@pytest.mark.unit
def test_index_key_column_json_round_trip() -> None:
    key = IndexKeyColumn(
        expression="lower(email)",
        opclass="text_pattern_ops",
        sort_order=SortOrder.DESC,
        nulls_order=NullsOrder.FIRST,
    )
    assert IndexKeyColumn.model_validate_json(key.model_dump_json()) == key


# ---------------------------------------------------------------------------
# Index — construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_minimal() -> None:
    ref = _index_ref("users_pkey")
    table_ref = _table_ref("users")
    key = IndexKeyColumn(column_name="id")
    idx = Index(ref=ref, table_ref=table_ref, key_columns=(key,))
    assert idx.method is IndexMethod.BTREE
    assert idx.unique is False
    assert idx.predicate is None
    assert idx.include_columns == ()
    assert idx.comment is None


@pytest.mark.unit
def test_index_unique() -> None:
    ref = _index_ref("users_email_key")
    table_ref = _table_ref("users")
    key = IndexKeyColumn(column_name="email")
    idx = Index(ref=ref, table_ref=table_ref, key_columns=(key,), unique=True)
    assert idx.unique is True


@pytest.mark.unit
def test_index_partial() -> None:
    ref = _index_ref("active_users_idx")
    table_ref = _table_ref("users")
    key = IndexKeyColumn(column_name="email")
    idx = Index(
        ref=ref,
        table_ref=table_ref,
        key_columns=(key,),
        predicate="(deleted_at IS NULL)",
    )
    assert idx.predicate == "(deleted_at IS NULL)"


@pytest.mark.unit
def test_index_with_include_columns() -> None:
    ref = _index_ref("covering_idx")
    table_ref = _table_ref("orders")
    key = IndexKeyColumn(column_name="order_id")
    idx = Index(
        ref=ref,
        table_ref=table_ref,
        key_columns=(key,),
        include_columns=("status", "created_at"),
    )
    assert idx.include_columns == ("status", "created_at")


@pytest.mark.unit
def test_index_multiple_key_columns() -> None:
    ref = _index_ref("compound_idx")
    table_ref = _table_ref("t")
    keys = (
        IndexKeyColumn(column_name="a", sort_order=SortOrder.ASC),
        IndexKeyColumn(column_name="b", sort_order=SortOrder.DESC),
    )
    idx = Index(ref=ref, table_ref=table_ref, key_columns=keys)
    assert len(idx.key_columns) == 2


@pytest.mark.unit
def test_index_gin_method() -> None:
    ref = _index_ref("tags_gin")
    table_ref = _table_ref("posts")
    key = IndexKeyColumn(column_name="tags")
    idx = Index(ref=ref, table_ref=table_ref, key_columns=(key,), method=IndexMethod.GIN)
    assert idx.method is IndexMethod.GIN


@pytest.mark.unit
def test_index_qname_shortcut() -> None:
    ref = _index_ref("my_idx")
    table_ref = _table_ref("t")
    key = IndexKeyColumn(column_name="x")
    idx = Index(ref=ref, table_ref=table_ref, key_columns=(key,))
    assert idx.qname == QualifiedName(namespace="public", name="my_idx")


# ---------------------------------------------------------------------------
# Index — ref kind validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_rejects_non_index_ref() -> None:
    bad_ref = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="t"))
    table_ref = _table_ref("t")
    key = IndexKeyColumn(column_name="x")
    with pytest.raises(ValidationError, match="must have kind INDEX"):
        Index(ref=bad_ref, table_ref=table_ref, key_columns=(key,))


@pytest.mark.unit
def test_index_rejects_non_table_table_ref() -> None:
    ref = _index_ref("my_idx")
    bad_table_ref = ObjectRef(
        kind=ObjectKind.VIEW, qname=QualifiedName(namespace="public", name="v")
    )
    key = IndexKeyColumn(column_name="x")
    with pytest.raises(ValidationError, match="must have kind TABLE"):
        Index(ref=ref, table_ref=bad_table_ref, key_columns=(key,))


@pytest.mark.unit
def test_index_empty_key_columns_rejected() -> None:
    ref = _index_ref("idx")
    table_ref = _table_ref("t")
    with pytest.raises(ValidationError):
        Index(ref=ref, table_ref=table_ref, key_columns=())


# ---------------------------------------------------------------------------
# Index — immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_is_frozen() -> None:
    ref = _index_ref("idx")
    table_ref = _table_ref("t")
    key = IndexKeyColumn(column_name="x")
    idx = Index(ref=ref, table_ref=table_ref, key_columns=(key,))
    with pytest.raises(ValidationError):
        idx.unique = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Index — JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_json_round_trip() -> None:
    ref = _index_ref("users_email_lower_idx")
    table_ref = _table_ref("users")
    keys = (
        IndexKeyColumn(expression="lower(email)", opclass="text_pattern_ops"),
        IndexKeyColumn(column_name="created_at", sort_order=SortOrder.DESC),
    )
    idx = Index(
        ref=ref,
        table_ref=table_ref,
        key_columns=keys,
        include_columns=("name",),
        unique=True,
        predicate="(active = true)",
        comment="Index for case-insensitive email lookups",
    )
    restored = Index.model_validate_json(idx.model_dump_json())
    assert restored == idx


# ---------------------------------------------------------------------------
# Index — equality / hash
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_equality_and_hash() -> None:
    ref = _index_ref("idx")
    table_ref = _table_ref("t")
    key = IndexKeyColumn(column_name="x")
    a = Index(ref=ref, table_ref=table_ref, key_columns=(key,))
    b = Index(ref=ref, table_ref=table_ref, key_columns=(key,))
    assert a == b
    assert hash(a) == hash(b)
