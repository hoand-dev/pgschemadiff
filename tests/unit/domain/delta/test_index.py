"""Unit tests for ``pgschemadiff.domain.delta.index`` (task P2-DOM-01d).

Covers:
- Construction of each concrete index-level delta subclass
- ``op`` Literal is fixed/auto-defaulted and rejects wrong ops
- ``kind`` Literal is fixed/auto-defaulted and is the union discriminator
- Frozen behaviour (``frozen=True``) and ``extra="forbid"``
- All model validators (happy + raising paths):
  - CreateIndex: target must equal index.ref
  - DropIndex: target must equal index.ref
  - ReplaceIndex: target == new_index.ref, old_index.ref == new_index.ref,
    old_index != new_index (no-op rejection)
- ``sort_key`` shape for top-level objects: ``(namespace, name, op_value)``
- Discriminated-union round-trip via ``TypeAdapter[IndexDelta]``
  (``model_validate`` / ``model_dump`` selects the right subclass by ``kind``)
- Wrong-kind rejection via the TypeAdapter
- Package-level re-export (``from pgschemadiff.domain.delta import …``)
- Index is a top-level object (not sub-object): parent is None in target
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.delta import (
    CreateIndex,
    DropIndex,
    IndexDelta,
    ReplaceIndex,
)
from pgschemadiff.domain.delta.base import DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod, SortOrder

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _qname(namespace: str = "public", name: str = "users_email_idx") -> QualifiedName:
    return QualifiedName(namespace=namespace, name=name)


def _table_ref(namespace: str = "public", name: str = "users") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace=namespace, name=name))


def _index_ref(
    namespace: str = "public",
    name: str = "users_email_idx",
) -> ObjectRef:
    """Build a top-level ObjectRef for an index (no parent)."""
    return ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _key_col(column_name: str = "email") -> IndexKeyColumn:
    return IndexKeyColumn(column_name=column_name)


def _minimal_index(
    namespace: str = "public",
    name: str = "users_email_idx",
    table_name: str = "users",
) -> Index:
    """Return a minimal valid btree index on a single column."""
    ref = _index_ref(namespace, name)
    table_ref = _table_ref(namespace, table_name)
    key = _key_col("email")
    return Index(ref=ref, table_ref=table_ref, method=IndexMethod.BTREE, key_columns=(key,))


def _gin_index(
    namespace: str = "public",
    name: str = "posts_content_idx",
    table_name: str = "posts",
) -> Index:
    """Return a minimal GIN index on a text-search column."""
    ref = _index_ref(namespace, name)
    table_ref = _table_ref(namespace, table_name)
    key = _key_col("content")
    return Index(ref=ref, table_ref=table_ref, method=IndexMethod.GIN, key_columns=(key,))


def _partial_unique_index(
    namespace: str = "public",
    name: str = "users_active_email_idx",
    table_name: str = "users",
) -> Index:
    """Return a partial unique btree index."""
    ref = _index_ref(namespace, name)
    table_ref = _table_ref(namespace, table_name)
    key = _key_col("email")
    return Index(
        ref=ref,
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(key,),
        unique=True,
        predicate="is_active = true",
    )


@pytest.fixture
def idx_ref() -> ObjectRef:
    return _index_ref("public", "users_email_idx")


@pytest.fixture
def minimal_index() -> Index:
    return _minimal_index()


@pytest.fixture
def gin_index() -> Index:
    return _gin_index()


@pytest.fixture
def partial_unique_index() -> Index:
    return _partial_unique_index()


# ---------------------------------------------------------------------------
# TypeAdapter for the discriminated union
# ---------------------------------------------------------------------------

_IDX_DELTA_TA: TypeAdapter[IndexDelta] = TypeAdapter(IndexDelta)


# ===========================================================================
# CreateIndex
# ===========================================================================


@pytest.mark.unit
def test_create_index_constructs(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    assert delta.op is DeltaOp.CREATE
    assert delta.kind == "create_index"
    assert delta.index is minimal_index
    assert delta.target is idx_ref


@pytest.mark.unit
def test_create_index_op_defaults_to_create(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """op has a default of DeltaOp.CREATE so callers need not pass it."""
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    assert delta.op is DeltaOp.CREATE


@pytest.mark.unit
def test_create_index_kind_defaults(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """kind has a default of 'create_index' so callers need not pass it."""
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    assert delta.kind == "create_index"


@pytest.mark.unit
def test_create_index_rejects_wrong_op(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """Passing op=DROP to CreateIndex must raise ValidationError."""
    with pytest.raises(ValidationError):
        CreateIndex(target=idx_ref, index=minimal_index, op=DeltaOp.DROP)  # type: ignore[arg-type]


@pytest.mark.unit
def test_create_index_is_frozen(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    other = _gin_index()
    with pytest.raises(ValidationError):
        delta.index = other  # type: ignore[misc]


@pytest.mark.unit
def test_create_index_rejects_extra_fields(idx_ref: ObjectRef, minimal_index: Index) -> None:
    with pytest.raises(ValidationError):
        CreateIndex(target=idx_ref, index=minimal_index, surprise="oops")  # type: ignore[call-arg]


@pytest.mark.unit
def test_create_index_sort_key(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """Top-level index sort_key: (namespace, name, op_value) — 3-tuple."""
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    assert delta.sort_key == ("public", "users_email_idx", "create")


@pytest.mark.unit
def test_create_index_sort_key_cross_schema() -> None:
    """Indexes in a different schema produce a distinct sort_key prefix."""
    ref = _index_ref("billing", "invoices_amount_idx")
    idx = _minimal_index("billing", "invoices_amount_idx", "invoices")
    delta = CreateIndex(target=ref, index=idx)
    assert delta.sort_key == ("billing", "invoices_amount_idx", "create")


@pytest.mark.unit
def test_create_index_json_round_trip(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    payload = delta.model_dump_json()
    restored = CreateIndex.model_validate_json(payload)
    assert restored == delta


@pytest.mark.unit
def test_create_index_with_gin_method(gin_index: Index) -> None:
    """CreateIndex works with non-btree access methods."""
    ref = _index_ref("public", "posts_content_idx")
    delta = CreateIndex(target=ref, index=gin_index)
    assert delta.index.method is IndexMethod.GIN


@pytest.mark.unit
def test_create_index_with_partial_unique(partial_unique_index: Index) -> None:
    """CreateIndex carries unique flag and predicate from the Index."""
    ref = _index_ref("public", "users_active_email_idx")
    delta = CreateIndex(target=ref, index=partial_unique_index)
    assert delta.index.unique is True
    assert delta.index.predicate == "is_active = true"


# ---------------------------------------------------------------------------
# CreateIndex validators — happy + raising
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_index_rejects_mismatched_target(minimal_index: Index) -> None:
    """target must equal index.ref; mismatched ref raises ValidationError."""
    wrong_ref = _index_ref("public", "totally_different_idx")
    with pytest.raises(ValidationError, match=r"must equal index\.ref"):
        CreateIndex(target=wrong_ref, index=minimal_index)


@pytest.mark.unit
def test_create_index_target_matches_index_ref(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """When target == index.ref, construction succeeds."""
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    assert delta.target == delta.index.ref


# ===========================================================================
# DropIndex
# ===========================================================================


@pytest.mark.unit
def test_drop_index_constructs(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = DropIndex(target=idx_ref, index=minimal_index)
    assert delta.op is DeltaOp.DROP
    assert delta.kind == "drop_index"
    assert delta.index is minimal_index


@pytest.mark.unit
def test_drop_index_op_defaults_to_drop(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = DropIndex(target=idx_ref, index=minimal_index)
    assert delta.op is DeltaOp.DROP


@pytest.mark.unit
def test_drop_index_kind_defaults(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = DropIndex(target=idx_ref, index=minimal_index)
    assert delta.kind == "drop_index"


@pytest.mark.unit
def test_drop_index_rejects_wrong_op(idx_ref: ObjectRef, minimal_index: Index) -> None:
    with pytest.raises(ValidationError):
        DropIndex(target=idx_ref, index=minimal_index, op=DeltaOp.CREATE)  # type: ignore[arg-type]


@pytest.mark.unit
def test_drop_index_is_frozen(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = DropIndex(target=idx_ref, index=minimal_index)
    with pytest.raises(ValidationError):
        delta.op = DeltaOp.DROP  # type: ignore[misc]


@pytest.mark.unit
def test_drop_index_rejects_extra_fields(idx_ref: ObjectRef, minimal_index: Index) -> None:
    with pytest.raises(ValidationError):
        DropIndex(target=idx_ref, index=minimal_index, nope=True)  # type: ignore[call-arg]


@pytest.mark.unit
def test_drop_index_sort_key() -> None:
    ref = _index_ref("myns", "archive_idx")
    idx = _minimal_index("myns", "archive_idx", "archive")
    delta = DropIndex(target=ref, index=idx)
    assert delta.sort_key == ("myns", "archive_idx", "drop")


@pytest.mark.unit
def test_drop_index_json_round_trip(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = DropIndex(target=idx_ref, index=minimal_index)
    payload = delta.model_dump_json()
    restored = DropIndex.model_validate_json(payload)
    assert restored == delta


@pytest.mark.unit
def test_drop_index_with_include_columns() -> None:
    """DropIndex correctly carries an index with INCLUDE columns."""
    ref = _index_ref("public", "users_covering_idx")
    table_ref = _table_ref("public", "users")
    key = _key_col("id")
    idx = Index(
        ref=ref,
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(key,),
        include_columns=("email", "name"),
    )
    delta = DropIndex(target=ref, index=idx)
    assert delta.index.include_columns == ("email", "name")


# ---------------------------------------------------------------------------
# DropIndex validators
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_drop_index_rejects_mismatched_target(minimal_index: Index) -> None:
    """target must equal index.ref; mismatched ref raises ValidationError."""
    wrong_ref = _index_ref("public", "other_idx")
    with pytest.raises(ValidationError, match=r"must equal index\.ref"):
        DropIndex(target=wrong_ref, index=minimal_index)


@pytest.mark.unit
def test_drop_index_target_matches_index_ref(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """When target == index.ref, construction succeeds."""
    delta = DropIndex(target=idx_ref, index=minimal_index)
    assert delta.target == delta.index.ref


# ===========================================================================
# ReplaceIndex
# ===========================================================================


def _make_replace_pair(
    namespace: str = "public",
    index_name: str = "users_email_idx",
    table_name: str = "users",
) -> tuple[Index, Index]:
    """Return (old_index, new_index) pair with the same ref but different methods."""
    ref = _index_ref(namespace, index_name)
    table_ref = _table_ref(namespace, table_name)
    key = _key_col("email")
    old = Index(ref=ref, table_ref=table_ref, method=IndexMethod.BTREE, key_columns=(key,))
    new = Index(ref=ref, table_ref=table_ref, method=IndexMethod.HASH, key_columns=(key,))
    return old, new


@pytest.fixture
def replace_pair() -> tuple[Index, Index]:
    return _make_replace_pair()


@pytest.mark.unit
def test_replace_index_constructs(replace_pair: tuple[Index, Index]) -> None:
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.op is DeltaOp.REPLACE
    assert delta.kind == "replace_index"
    assert delta.old_index is old
    assert delta.new_index is new
    assert delta.target is ref


@pytest.mark.unit
def test_replace_index_op_defaults_to_replace(replace_pair: tuple[Index, Index]) -> None:
    """op has a default of DeltaOp.REPLACE so callers need not pass it."""
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.op is DeltaOp.REPLACE


@pytest.mark.unit
def test_replace_index_kind_defaults(replace_pair: tuple[Index, Index]) -> None:
    """kind has a default of 'replace_index'."""
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.kind == "replace_index"


@pytest.mark.unit
def test_replace_index_rejects_wrong_op(replace_pair: tuple[Index, Index]) -> None:
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    with pytest.raises(ValidationError):
        ReplaceIndex(
            target=ref,
            old_index=old,
            new_index=new,
            op=DeltaOp.ALTER,  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_replace_index_is_frozen(replace_pair: tuple[Index, Index]) -> None:
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    other = _gin_index()
    with pytest.raises(ValidationError):
        delta.new_index = other  # type: ignore[misc]


@pytest.mark.unit
def test_replace_index_rejects_extra_fields(replace_pair: tuple[Index, Index]) -> None:
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    with pytest.raises(ValidationError):
        ReplaceIndex(  # type: ignore[call-arg]
            target=ref,
            old_index=old,
            new_index=new,
            extra="bad",
        )


@pytest.mark.unit
def test_replace_index_sort_key(replace_pair: tuple[Index, Index]) -> None:
    """Top-level index sort_key: (namespace, name, op_value)."""
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.sort_key == ("public", "users_email_idx", "replace")


@pytest.mark.unit
def test_replace_index_sort_key_cross_schema() -> None:
    """Cross-schema replace produces a distinct sort_key prefix."""
    old, new = _make_replace_pair("billing", "invoices_amount_idx", "invoices")
    ref = _index_ref("billing", "invoices_amount_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.sort_key == ("billing", "invoices_amount_idx", "replace")


@pytest.mark.unit
def test_replace_index_json_round_trip(replace_pair: tuple[Index, Index]) -> None:
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    payload = delta.model_dump_json()
    restored = ReplaceIndex.model_validate_json(payload)
    assert restored == delta


@pytest.mark.unit
def test_replace_index_predicate_change() -> None:
    """ReplaceIndex carries a predicate change (partial → non-partial)."""
    ref = _index_ref("public", "users_email_idx")
    table_ref = _table_ref("public", "users")
    key = _key_col("email")
    old = Index(
        ref=ref,
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(key,),
        predicate="is_active = true",
    )
    new = Index(
        ref=ref,
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(key,),
        predicate=None,
    )
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.old_index.predicate == "is_active = true"
    assert delta.new_index.predicate is None


@pytest.mark.unit
def test_replace_index_include_column_change() -> None:
    """ReplaceIndex carries an INCLUDE column change."""
    ref = _index_ref("public", "users_covering_idx")
    table_ref = _table_ref("public", "users")
    key = _key_col("id")
    old = Index(
        ref=ref,
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(key,),
        include_columns=("email",),
    )
    new = Index(
        ref=ref,
        table_ref=table_ref,
        method=IndexMethod.BTREE,
        key_columns=(key,),
        include_columns=("email", "name"),
    )
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.old_index.include_columns == ("email",)
    assert delta.new_index.include_columns == ("email", "name")


@pytest.mark.unit
def test_replace_index_key_column_sort_order_change() -> None:
    """ReplaceIndex carries a key column sort order change."""
    ref = _index_ref("public", "users_created_idx")
    table_ref = _table_ref("public", "users")
    old_key = IndexKeyColumn(column_name="created_at", sort_order=SortOrder.ASC)
    new_key = IndexKeyColumn(column_name="created_at", sort_order=SortOrder.DESC)
    old = Index(ref=ref, table_ref=table_ref, method=IndexMethod.BTREE, key_columns=(old_key,))
    new = Index(ref=ref, table_ref=table_ref, method=IndexMethod.BTREE, key_columns=(new_key,))
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.old_index.key_columns[0].sort_order is SortOrder.ASC
    assert delta.new_index.key_columns[0].sort_order is SortOrder.DESC


# ---------------------------------------------------------------------------
# ReplaceIndex validators — happy + raising
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_replace_index_rejects_target_not_matching_new_ref(
    replace_pair: tuple[Index, Index],
) -> None:
    """target must equal new_index.ref; wrong target raises ValidationError."""
    old, new = replace_pair
    wrong_ref = _index_ref("public", "completely_different_idx")
    with pytest.raises(ValidationError, match=r"must equal\nnew_index\.ref|must equal"):
        ReplaceIndex(target=wrong_ref, old_index=old, new_index=new)


@pytest.mark.unit
def test_replace_index_rejects_mismatched_refs() -> None:
    """old_index.ref must equal new_index.ref; different-named indexes rejected."""
    old_ref = _index_ref("public", "idx_a")
    new_ref = _index_ref("public", "idx_b")
    table_ref = _table_ref("public", "users")
    key = _key_col("email")
    old = Index(ref=old_ref, table_ref=table_ref, method=IndexMethod.BTREE, key_columns=(key,))
    new = Index(ref=new_ref, table_ref=table_ref, method=IndexMethod.HASH, key_columns=(key,))
    with pytest.raises(ValidationError, match=r"must equal"):
        ReplaceIndex(target=new_ref, old_index=old, new_index=new)


@pytest.mark.unit
def test_replace_index_rejects_noop_replacement() -> None:
    """old_index == new_index (identical) must be rejected as a no-op."""
    ref = _index_ref("public", "users_email_idx")
    table_ref = _table_ref("public", "users")
    key = _key_col("email")
    idx = Index(ref=ref, table_ref=table_ref, method=IndexMethod.BTREE, key_columns=(key,))
    with pytest.raises(ValidationError, match=r"no-op replacement"):
        ReplaceIndex(target=ref, old_index=idx, new_index=idx)


@pytest.mark.unit
def test_replace_index_allows_valid_replacement(replace_pair: tuple[Index, Index]) -> None:
    """A valid replacement (different methods) succeeds."""
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.old_index != delta.new_index
    assert delta.old_index.ref == delta.new_index.ref


@pytest.mark.unit
def test_replace_index_target_equals_new_index_ref(replace_pair: tuple[Index, Index]) -> None:
    """After construction, target must point to new_index.ref."""
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.target == delta.new_index.ref


# ===========================================================================
# Discriminated-union (IndexDelta) round-trip — discriminated on ``kind``
# ===========================================================================


def _index_ref_dict(
    namespace: str = "public",
    name: str = "users_email_idx",
) -> dict[str, object]:
    """Return a raw dict representation of an index ObjectRef."""
    return {
        "kind": "index",
        "qname": {"namespace": namespace, "name": name},
        "parent": None,
        "arg_signature": None,
    }


def _index_dict(
    namespace: str = "public",
    name: str = "users_email_idx",
    table_name: str = "users",
    method: str = "btree",
) -> dict[str, object]:
    """Return a raw dict representation of a minimal Index."""
    return {
        "ref": _index_ref_dict(namespace, name),
        "table_ref": {
            "kind": "table",
            "qname": {"namespace": namespace, "name": table_name},
            "parent": None,
            "arg_signature": None,
        },
        "method": method,
        "key_columns": [
            {
                "column_name": "email",
                "expression": None,
                "opclass": None,
                "sort_order": "asc",
                "nulls_order": None,
            }
        ],
        "include_columns": [],
        "unique": False,
        "predicate": None,
        "comment": None,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        {
            "kind": "create_index",
            "op": "create",
            "target": _index_ref_dict(),
            "index": _index_dict(),
        },
        {
            "kind": "drop_index",
            "op": "drop",
            "target": _index_ref_dict("public", "users_pkey_idx"),
            "index": _index_dict("public", "users_pkey_idx"),
        },
        {
            "kind": "replace_index",
            "op": "replace",
            "target": _index_ref_dict(),
            "old_index": _index_dict(method="btree"),
            "new_index": _index_dict(method="hash"),
        },
    ],
    ids=["create_index", "drop_index", "replace_index"],
)
def test_index_delta_discriminated_union_round_trip(raw: dict[str, object]) -> None:
    """TypeAdapter[IndexDelta] routes to the right subclass by ``kind`` discriminator."""
    delta = _IDX_DELTA_TA.validate_python(raw)
    assert delta.kind == raw["kind"]
    dumped = _IDX_DELTA_TA.dump_python(delta, mode="json")
    restored = _IDX_DELTA_TA.validate_python(dumped)
    assert restored == delta


@pytest.mark.unit
def test_index_delta_unknown_kind_rejected() -> None:
    """An unknown ``kind`` value must raise ValidationError."""
    raw = {
        "kind": "create_table",  # valid table delta kind, but not in IndexDelta union
        "op": "create",
        "target": _index_ref_dict(),
    }
    with pytest.raises(ValidationError):
        _IDX_DELTA_TA.validate_python(raw)


@pytest.mark.unit
def test_index_delta_type_adapter_selects_create(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """TypeAdapter returns a CreateIndex instance for kind='create_index'."""
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    dumped = _IDX_DELTA_TA.dump_python(delta, mode="json")
    restored = _IDX_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, CreateIndex)
    assert restored.op is DeltaOp.CREATE
    assert restored.kind == "create_index"


@pytest.mark.unit
def test_index_delta_type_adapter_selects_drop(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """TypeAdapter returns a DropIndex instance for kind='drop_index'."""
    delta = DropIndex(target=idx_ref, index=minimal_index)
    dumped = _IDX_DELTA_TA.dump_python(delta, mode="json")
    restored = _IDX_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, DropIndex)
    assert restored.op is DeltaOp.DROP
    assert restored.kind == "drop_index"


@pytest.mark.unit
def test_index_delta_type_adapter_selects_replace(
    replace_pair: tuple[Index, Index],
) -> None:
    """TypeAdapter returns a ReplaceIndex instance for kind='replace_index'."""
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    dumped = _IDX_DELTA_TA.dump_python(delta, mode="json")
    restored = _IDX_DELTA_TA.validate_python(dumped)
    assert isinstance(restored, ReplaceIndex)
    assert restored.op is DeltaOp.REPLACE
    assert restored.kind == "replace_index"
    assert restored.old_index.method is IndexMethod.BTREE
    assert restored.new_index.method is IndexMethod.HASH


# ===========================================================================
# Top-level object — no parent in target
# ===========================================================================


@pytest.mark.unit
def test_create_index_target_has_no_parent(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """INDEX is not a SUB_OBJECT_KIND → target.parent must be None."""
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    assert delta.target.parent is None


@pytest.mark.unit
def test_drop_index_target_has_no_parent(idx_ref: ObjectRef, minimal_index: Index) -> None:
    delta = DropIndex(target=idx_ref, index=minimal_index)
    assert delta.target.parent is None


@pytest.mark.unit
def test_replace_index_target_has_no_parent(replace_pair: tuple[Index, Index]) -> None:
    old, new = replace_pair
    ref = _index_ref("public", "users_email_idx")
    delta = ReplaceIndex(target=ref, old_index=old, new_index=new)
    assert delta.target.parent is None


@pytest.mark.unit
def test_index_target_ref_kind_is_index(idx_ref: ObjectRef, minimal_index: Index) -> None:
    """target.kind must be ObjectKind.INDEX for index deltas."""
    delta = CreateIndex(target=idx_ref, index=minimal_index)
    assert delta.target.kind is ObjectKind.INDEX


# ===========================================================================
# Package-level re-export verification
# ===========================================================================


@pytest.mark.unit
def test_package_exports_create_index() -> None:
    """CreateIndex is importable from pgschemadiff.domain.delta."""
    assert issubclass(CreateIndex, object)


@pytest.mark.unit
def test_package_exports_drop_index() -> None:
    """DropIndex is importable from pgschemadiff.domain.delta."""
    assert issubclass(DropIndex, object)


@pytest.mark.unit
def test_package_exports_replace_index() -> None:
    """ReplaceIndex is importable from pgschemadiff.domain.delta."""
    assert issubclass(ReplaceIndex, object)


@pytest.mark.unit
def test_package_exports_index_delta() -> None:
    """IndexDelta is importable from pgschemadiff.domain.delta."""
    assert IndexDelta is not None
