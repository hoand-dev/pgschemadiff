"""Unit tests for ``pgschemadiff.application.diff.comparators.index`` (task P2-DIFF-04).

Covers:
- ``isinstance(IndexComparator(), Comparator)`` is ``True`` (Protocol match)
- ``IndexComparator.kind == ObjectKind.INDEX``
- ``compare(None, target)`` → ``(CreateIndex(...),)``
- ``compare(source, None)`` → ``(DropIndex(...),)``
- ``compare(source, target)`` identical → ``()`` (no delta)
- ``compare(source, target)`` per structural field → ``(ReplaceIndex(...),)``
  parametrized over: method, key_columns, include_columns, unique, predicate
- ``compare(source, target)`` comment-only diff → ``()`` (deferred, no delta)
- ``compare(None, None)`` → ``()`` (defensive)
- Emitted deltas carry correct ``target``, ``old_index``, ``new_index``
- ``_structurally_equal`` helper is directly tested
"""

from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.index import (
    IndexComparator,
    _structurally_equal,
)
from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.index import CreateIndex, DropIndex, ReplaceIndex
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod, SortOrder

# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _qname(namespace: str, name: str) -> QualifiedName:
    return QualifiedName(namespace=namespace, name=name)


def _index_ref(namespace: str = "public", name: str = "users_email_idx") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.INDEX, qname=_qname(namespace, name))


def _table_ref(namespace: str = "public", name: str = "users") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=_qname(namespace, name))


def _key_col(column_name: str = "email") -> IndexKeyColumn:
    return IndexKeyColumn(column_name=column_name)


def _make_index(
    *,
    index_ref: ObjectRef | None = None,
    table_ref: ObjectRef | None = None,
    method: IndexMethod = IndexMethod.BTREE,
    key_columns: tuple[IndexKeyColumn, ...] | None = None,
    include_columns: tuple[str, ...] = (),
    unique: bool = False,
    predicate: str | None = None,
    comment: str | None = None,
) -> Index:
    return Index(
        ref=index_ref or _index_ref(),
        table_ref=table_ref or _table_ref(),
        method=method,
        key_columns=key_columns or (_key_col(),),
        include_columns=include_columns,
        unique=unique,
        predicate=predicate,
        comment=comment,
    )


# The canonical "base" index used across most tests
_BASE_INDEX = _make_index()


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_isinstance_comparator(self) -> None:
        """IndexComparator must be a structural match for the Comparator Protocol."""
        assert isinstance(IndexComparator(), Comparator)

    def test_kind_attribute(self) -> None:
        assert IndexComparator.kind == ObjectKind.INDEX

    def test_kind_instance_attribute(self) -> None:
        assert IndexComparator().kind == ObjectKind.INDEX


# ---------------------------------------------------------------------------
# CREATE: source=None, target set
# ---------------------------------------------------------------------------


class TestCreateIndex:
    def test_returns_create_index_delta(self) -> None:
        cmp = IndexComparator()
        result = cmp.compare(None, _BASE_INDEX)
        assert len(result) == 1
        assert isinstance(result[0], CreateIndex)

    def test_create_delta_target_matches_index_ref(self) -> None:
        idx = _make_index()
        cmp = IndexComparator()
        (delta,) = cmp.compare(None, idx)
        assert isinstance(delta, CreateIndex)
        assert delta.target == idx.ref

    def test_create_delta_carries_index_payload(self) -> None:
        idx = _make_index(unique=True, predicate="WHERE active")
        cmp = IndexComparator()
        (delta,) = cmp.compare(None, idx)
        assert isinstance(delta, CreateIndex)
        assert delta.index == idx

    def test_create_in_custom_namespace(self) -> None:
        ref = _index_ref(namespace="myschema", name="my_idx")
        idx = _make_index(index_ref=ref, table_ref=_table_ref(namespace="myschema"))
        cmp = IndexComparator()
        (delta,) = cmp.compare(None, idx)
        assert isinstance(delta, CreateIndex)
        assert delta.target.qname.namespace == "myschema"


# ---------------------------------------------------------------------------
# DROP: source set, target=None
# ---------------------------------------------------------------------------


class TestDropIndex:
    def test_returns_drop_index_delta(self) -> None:
        cmp = IndexComparator()
        result = cmp.compare(_BASE_INDEX, None)
        assert len(result) == 1
        assert isinstance(result[0], DropIndex)

    def test_drop_delta_target_matches_index_ref(self) -> None:
        idx = _make_index()
        cmp = IndexComparator()
        (delta,) = cmp.compare(idx, None)
        assert isinstance(delta, DropIndex)
        assert delta.target == idx.ref

    def test_drop_delta_carries_index_payload(self) -> None:
        idx = _make_index(unique=True)
        cmp = IndexComparator()
        (delta,) = cmp.compare(idx, None)
        assert isinstance(delta, DropIndex)
        assert delta.index == idx


# ---------------------------------------------------------------------------
# NO CHANGE: identical source and target
# ---------------------------------------------------------------------------


class TestNoChange:
    def test_identical_indexes_emit_nothing(self) -> None:
        cmp = IndexComparator()
        result = cmp.compare(_BASE_INDEX, _BASE_INDEX)
        assert result == ()

    def test_copies_are_identical(self) -> None:
        idx_a = _make_index(unique=False, predicate=None)
        idx_b = _make_index(unique=False, predicate=None)
        cmp = IndexComparator()
        assert cmp.compare(idx_a, idx_b) == ()

    def test_both_none_emits_nothing(self) -> None:
        """Defensive: engine should never pass (None, None) but must not raise."""
        cmp = IndexComparator()
        result = cmp.compare(None, None)
        assert result == ()


# ---------------------------------------------------------------------------
# REPLACE: structural field differences (parametrized)
# ---------------------------------------------------------------------------


class TestReplaceIndex:
    def _assert_replace(self, source: Index, target: Index) -> ReplaceIndex:
        """Helper: assert exactly one ReplaceIndex is emitted and return it."""
        cmp = IndexComparator()
        result = cmp.compare(source, target)
        assert len(result) == 1
        delta = result[0]
        assert isinstance(delta, ReplaceIndex)
        return delta

    def test_replace_delta_carries_old_and_new(self) -> None:
        source = _make_index(unique=False)
        target = _make_index(unique=True)
        delta = self._assert_replace(source, target)
        assert delta.old_index == source
        assert delta.new_index == target

    def test_replace_delta_target_matches_new_index_ref(self) -> None:
        source = _make_index(unique=False)
        target = _make_index(unique=True)
        delta = self._assert_replace(source, target)
        assert delta.target == target.ref

    # --- Parametrized: one structural field at a time -------------------------

    def test_method_difference_emits_replace(self) -> None:
        source = _make_index(method=IndexMethod.BTREE)
        target = _make_index(method=IndexMethod.HASH)
        self._assert_replace(source, target)

    @pytest.mark.parametrize(
        ("src_method", "tgt_method"),
        [
            (IndexMethod.BTREE, IndexMethod.HASH),
            (IndexMethod.BTREE, IndexMethod.GIN),
            (IndexMethod.BTREE, IndexMethod.GIST),
            (IndexMethod.BTREE, IndexMethod.BRIN),
            (IndexMethod.HASH, IndexMethod.BTREE),
            (IndexMethod.GIST, IndexMethod.SPGIST),
        ],
    )
    def test_method_pairs_emit_replace(
        self, src_method: IndexMethod, tgt_method: IndexMethod
    ) -> None:
        source = _make_index(method=src_method)
        target = _make_index(method=tgt_method)
        self._assert_replace(source, target)

    def test_key_columns_difference_emits_replace(self) -> None:
        source = _make_index(key_columns=(_key_col("email"),))
        target = _make_index(key_columns=(_key_col("username"),))
        self._assert_replace(source, target)

    def test_key_columns_extra_column_emits_replace(self) -> None:
        source = _make_index(key_columns=(_key_col("email"),))
        target = _make_index(key_columns=(_key_col("email"), _key_col("username")))
        self._assert_replace(source, target)

    def test_key_columns_sort_order_emits_replace(self) -> None:
        source = _make_index(
            key_columns=(IndexKeyColumn(column_name="email", sort_order=SortOrder.ASC),)
        )
        target = _make_index(
            key_columns=(IndexKeyColumn(column_name="email", sort_order=SortOrder.DESC),)
        )
        self._assert_replace(source, target)

    def test_key_columns_opclass_emits_replace(self) -> None:
        source = _make_index(key_columns=(IndexKeyColumn(column_name="email"),))
        target = _make_index(
            key_columns=(IndexKeyColumn(column_name="email", opclass="text_pattern_ops"),)
        )
        self._assert_replace(source, target)

    def test_include_columns_difference_emits_replace(self) -> None:
        source = _make_index(include_columns=())
        target = _make_index(include_columns=("created_at",))
        self._assert_replace(source, target)

    def test_include_columns_change_emits_replace(self) -> None:
        source = _make_index(include_columns=("created_at",))
        target = _make_index(include_columns=("updated_at",))
        self._assert_replace(source, target)

    def test_include_columns_remove_emits_replace(self) -> None:
        source = _make_index(include_columns=("col",))
        target = _make_index(include_columns=())
        self._assert_replace(source, target)

    def test_unique_true_to_false_emits_replace(self) -> None:
        source = _make_index(unique=True)
        target = _make_index(unique=False)
        self._assert_replace(source, target)

    def test_unique_false_to_true_emits_replace(self) -> None:
        source = _make_index(unique=False)
        target = _make_index(unique=True)
        self._assert_replace(source, target)

    def test_predicate_add_emits_replace(self) -> None:
        source = _make_index(predicate=None)
        target = _make_index(predicate="WHERE active = true")
        self._assert_replace(source, target)

    def test_predicate_remove_emits_replace(self) -> None:
        source = _make_index(predicate="WHERE active = true")
        target = _make_index(predicate=None)
        self._assert_replace(source, target)

    def test_predicate_change_emits_replace(self) -> None:
        source = _make_index(predicate="WHERE active = true")
        target = _make_index(predicate="WHERE deleted_at IS NULL")
        self._assert_replace(source, target)

    @pytest.mark.parametrize(
        ("field", "src_val", "tgt_val"),
        [
            ("method", IndexMethod.BTREE, IndexMethod.HASH),
            ("unique", False, True),
            ("unique", True, False),
            ("predicate", None, "WHERE active"),
            ("predicate", "WHERE active", None),
            ("include_columns", (), ("col",)),
            ("include_columns", ("col",), ()),
        ],
    )
    def test_parametrized_structural_field_emits_replace(
        self, field: str, src_val: object, tgt_val: object
    ) -> None:
        """Single-field parametrized check: each structural field independently
        triggers a ReplaceIndex when changed."""
        source = _make_index(**{field: src_val})  # type: ignore[arg-type]
        target = _make_index(**{field: tgt_val})  # type: ignore[arg-type]
        cmp = IndexComparator()
        result = cmp.compare(source, target)
        assert len(result) == 1
        assert isinstance(result[0], ReplaceIndex)


# ---------------------------------------------------------------------------
# COMMENT-ONLY difference → no delta (deferred, MVP-A)
# ---------------------------------------------------------------------------


class TestCommentOnlyDiff:
    def test_comment_only_diff_emits_nothing(self) -> None:
        """A comment-only change must NOT emit ReplaceIndex in MVP-A.

        Rationale: COMMENT ON INDEX does not require a rebuild; there is no
        AlterIndexComment delta type yet.  This is intentional deferral.
        """
        source = _make_index(comment=None)
        target = _make_index(comment="This index speeds up lookups")
        cmp = IndexComparator()
        result = cmp.compare(source, target)
        assert result == ()

    def test_comment_change_emits_nothing(self) -> None:
        source = _make_index(comment="old comment")
        target = _make_index(comment="new comment")
        cmp = IndexComparator()
        assert cmp.compare(source, target) == ()

    def test_comment_removal_emits_nothing(self) -> None:
        source = _make_index(comment="some comment")
        target = _make_index(comment=None)
        cmp = IndexComparator()
        assert cmp.compare(source, target) == ()

    def test_structural_change_plus_comment_change_emits_replace(self) -> None:
        """When a structural field changes alongside comment, ReplaceIndex is emitted."""
        source = _make_index(unique=False, comment="old")
        target = _make_index(unique=True, comment="new")
        cmp = IndexComparator()
        result = cmp.compare(source, target)
        assert len(result) == 1
        assert isinstance(result[0], ReplaceIndex)


# ---------------------------------------------------------------------------
# _structurally_equal helper
# ---------------------------------------------------------------------------


class TestStructurallyEqual:
    def test_same_index_is_equal(self) -> None:
        assert _structurally_equal(_BASE_INDEX, _BASE_INDEX) is True

    def test_equivalent_copies_are_equal(self) -> None:
        a = _make_index()
        b = _make_index()
        assert _structurally_equal(a, b) is True

    def test_comment_diff_is_equal(self) -> None:
        """_structurally_equal must return True even when comments differ."""
        a = _make_index(comment=None)
        b = _make_index(comment="different")
        assert _structurally_equal(a, b) is True

    def test_method_diff_not_equal(self) -> None:
        a = _make_index(method=IndexMethod.BTREE)
        b = _make_index(method=IndexMethod.GIN)
        assert _structurally_equal(a, b) is False

    def test_key_columns_diff_not_equal(self) -> None:
        a = _make_index(key_columns=(_key_col("id"),))
        b = _make_index(key_columns=(_key_col("email"),))
        assert _structurally_equal(a, b) is False

    def test_include_columns_diff_not_equal(self) -> None:
        a = _make_index(include_columns=())
        b = _make_index(include_columns=("col",))
        assert _structurally_equal(a, b) is False

    def test_unique_diff_not_equal(self) -> None:
        a = _make_index(unique=False)
        b = _make_index(unique=True)
        assert _structurally_equal(a, b) is False

    def test_predicate_diff_not_equal(self) -> None:
        a = _make_index(predicate=None)
        b = _make_index(predicate="WHERE active")
        assert _structurally_equal(a, b) is False
