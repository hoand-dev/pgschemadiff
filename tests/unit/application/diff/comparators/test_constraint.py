"""Unit tests for ConstraintComparator (task P2-DIFF-05).

Coverage
--------
* add-only (constraint in target only) → AddConstraint
* drop-only (constraint in source only) → DropConstraint
* identical constraint on both sides → no delta
* definition-changed (same name, fields differ) → DropConstraint + AddConstraint pair
  in that order (drop before add)
* multiple constraints aggregated and sorted by name
* deterministic name-sorted ordering
* correct target ObjectRef:
  - kind == CONSTRAINT
  - parent == table_ref
  - qname.name == constraint.name
  - qname.namespace == table_ref.qname.namespace
* empty-vs-empty → empty tuple
* all five constraint kinds: PrimaryKey, Unique, Check, ForeignKey, Exclusion

Layer: pure application (domain + stdlib imports only, no IO, no async).
"""

from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.constraint import ConstraintComparator
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ConstraintDeferrability,
    ExclusionConstraint,
    ExclusionElement,
    FKAction,
    FKMatch,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def table_ref() -> ObjectRef:
    """A TABLE ObjectRef for 'public.orders' used across most tests."""
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="orders"),
    )


@pytest.fixture
def cmp() -> ConstraintComparator:
    """A fresh ConstraintComparator instance."""
    return ConstraintComparator()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pk(name: str, columns: tuple[str, ...] = ("id",)) -> PrimaryKeyConstraint:
    return PrimaryKeyConstraint(name=name, columns=columns)


def _uq(name: str, columns: tuple[str, ...] = ("email",)) -> UniqueConstraint:
    return UniqueConstraint(name=name, columns=columns)


def _chk(name: str, expression: str = "price > 0") -> CheckConstraint:
    return CheckConstraint(name=name, expression=expression)


def _fk(
    name: str,
    *,
    columns: tuple[str, ...] = ("customer_id",),
    ref_namespace: str = "public",
    ref_table: str = "customers",
    ref_columns: tuple[str, ...] = ("id",),
) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        name=name,
        columns=columns,
        ref_namespace=ref_namespace,
        ref_table=ref_table,
        ref_columns=ref_columns,
    )


def _excl(name: str) -> ExclusionConstraint:
    return ExclusionConstraint(
        name=name,
        index_method="gist",
        elements=(ExclusionElement(column_or_expr="tsrange", operator="&&"),),
    )


# ---------------------------------------------------------------------------
# kind attribute
# ---------------------------------------------------------------------------


class TestKindAttribute:
    """ConstraintComparator.kind must be ObjectKind.CONSTRAINT."""

    def test_kind_is_constraint(self, cmp: ConstraintComparator) -> None:
        assert cmp.kind is ObjectKind.CONSTRAINT


# ---------------------------------------------------------------------------
# Empty vs empty
# ---------------------------------------------------------------------------


class TestEmptyVsEmpty:
    def test_empty_source_empty_target_produces_no_deltas(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        result = cmp.compare_sets(table_ref, source=(), target=())
        assert result == ()


# ---------------------------------------------------------------------------
# Add-only (target only)
# ---------------------------------------------------------------------------


class TestAddOnly:
    def test_primary_key_in_target_only_emits_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        result = cmp.compare_sets(table_ref, source=(), target=(pk,))

        assert len(result) == 1
        delta = result[0]
        assert isinstance(delta, AddConstraint)
        assert delta.constraint == pk

    def test_unique_in_target_only_emits_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        uq = _uq("orders_uq_num")
        result = cmp.compare_sets(table_ref, source=(), target=(uq,))

        assert len(result) == 1
        assert isinstance(result[0], AddConstraint)
        assert result[0].constraint == uq

    def test_check_in_target_only_emits_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        chk = _chk("orders_chk_total")
        result = cmp.compare_sets(table_ref, source=(), target=(chk,))

        assert len(result) == 1
        assert isinstance(result[0], AddConstraint)
        assert result[0].constraint == chk

    def test_foreign_key_in_target_only_emits_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        fk = _fk("orders_fk_customer")
        result = cmp.compare_sets(table_ref, source=(), target=(fk,))

        assert len(result) == 1
        assert isinstance(result[0], AddConstraint)
        assert result[0].constraint == fk

    def test_exclusion_in_target_only_emits_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        excl = _excl("orders_excl_period")
        result = cmp.compare_sets(table_ref, source=(), target=(excl,))

        assert len(result) == 1
        assert isinstance(result[0], AddConstraint)
        assert result[0].constraint == excl


# ---------------------------------------------------------------------------
# Drop-only (source only)
# ---------------------------------------------------------------------------


class TestDropOnly:
    def test_primary_key_in_source_only_emits_drop(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        result = cmp.compare_sets(table_ref, source=(pk,), target=())

        assert len(result) == 1
        delta = result[0]
        assert isinstance(delta, DropConstraint)
        assert delta.constraint == pk

    def test_unique_in_source_only_emits_drop(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        uq = _uq("orders_uq_num")
        result = cmp.compare_sets(table_ref, source=(uq,), target=())

        assert len(result) == 1
        assert isinstance(result[0], DropConstraint)
        assert result[0].constraint == uq

    def test_check_in_source_only_emits_drop(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        chk = _chk("orders_chk_total")
        result = cmp.compare_sets(table_ref, source=(chk,), target=())

        assert len(result) == 1
        assert isinstance(result[0], DropConstraint)
        assert result[0].constraint == chk

    def test_foreign_key_in_source_only_emits_drop(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        fk = _fk("orders_fk_customer")
        result = cmp.compare_sets(table_ref, source=(fk,), target=())

        assert len(result) == 1
        assert isinstance(result[0], DropConstraint)
        assert result[0].constraint == fk

    def test_exclusion_in_source_only_emits_drop(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        excl = _excl("orders_excl_period")
        result = cmp.compare_sets(table_ref, source=(excl,), target=())

        assert len(result) == 1
        assert isinstance(result[0], DropConstraint)
        assert result[0].constraint == excl


# ---------------------------------------------------------------------------
# Identical definition → no delta
# ---------------------------------------------------------------------------


class TestIdenticalNoDelta:
    def test_identical_pk_produces_no_delta(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        result = cmp.compare_sets(table_ref, source=(pk,), target=(pk,))
        assert result == ()

    def test_identical_unique_produces_no_delta(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        uq = _uq("orders_uq_num")
        result = cmp.compare_sets(table_ref, source=(uq,), target=(uq,))
        assert result == ()

    def test_identical_check_produces_no_delta(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        chk = _chk("orders_chk_total")
        result = cmp.compare_sets(table_ref, source=(chk,), target=(chk,))
        assert result == ()

    def test_identical_fk_produces_no_delta(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        fk = _fk("orders_fk_customer")
        result = cmp.compare_sets(table_ref, source=(fk,), target=(fk,))
        assert result == ()

    def test_identical_exclusion_produces_no_delta(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        excl = _excl("orders_excl_period")
        result = cmp.compare_sets(table_ref, source=(excl,), target=(excl,))
        assert result == ()

    def test_multiple_identical_constraints_produce_no_deltas(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        uq = _uq("orders_uq_num")
        chk = _chk("orders_chk_total")
        result = cmp.compare_sets(table_ref, source=(pk, uq, chk), target=(pk, uq, chk))
        assert result == ()


# ---------------------------------------------------------------------------
# Definition-changed → Drop + Add pair
# ---------------------------------------------------------------------------


class TestDefinitionChanged:
    def test_pk_columns_changed_emits_drop_then_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_pk = _pk("orders_pkey", columns=("id",))
        new_pk = _pk("orders_pkey", columns=("id", "tenant_id"))

        result = cmp.compare_sets(table_ref, source=(old_pk,), target=(new_pk,))

        assert len(result) == 2
        drop, add = result
        assert isinstance(drop, DropConstraint)
        assert isinstance(add, AddConstraint)
        assert drop.constraint == old_pk
        assert add.constraint == new_pk

    def test_check_expression_changed_emits_drop_then_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_chk = _chk("orders_chk_total", expression="total > 0")
        new_chk = _chk("orders_chk_total", expression="total >= 0")

        result = cmp.compare_sets(table_ref, source=(old_chk,), target=(new_chk,))

        assert len(result) == 2
        assert isinstance(result[0], DropConstraint)
        assert isinstance(result[1], AddConstraint)
        assert result[0].constraint == old_chk
        assert result[1].constraint == new_chk

    def test_fk_on_delete_changed_emits_drop_then_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_fk = ForeignKeyConstraint(
            name="orders_fk_customer",
            columns=("customer_id",),
            ref_namespace="public",
            ref_table="customers",
            ref_columns=("id",),
            on_delete=FKAction.NO_ACTION,
        )
        new_fk = ForeignKeyConstraint(
            name="orders_fk_customer",
            columns=("customer_id",),
            ref_namespace="public",
            ref_table="customers",
            ref_columns=("id",),
            on_delete=FKAction.CASCADE,
        )

        result = cmp.compare_sets(table_ref, source=(old_fk,), target=(new_fk,))

        assert len(result) == 2
        assert isinstance(result[0], DropConstraint)
        assert isinstance(result[1], AddConstraint)

    def test_unique_nulls_not_distinct_changed_emits_drop_then_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_uq = UniqueConstraint(
            name="orders_uq_code", columns=("code",), nulls_not_distinct=False
        )
        new_uq = UniqueConstraint(name="orders_uq_code", columns=("code",), nulls_not_distinct=True)

        result = cmp.compare_sets(table_ref, source=(old_uq,), target=(new_uq,))

        assert len(result) == 2
        drop, add = result
        assert isinstance(drop, DropConstraint)
        assert isinstance(add, AddConstraint)

    def test_exclusion_predicate_changed_emits_drop_then_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_excl = ExclusionConstraint(
            name="orders_excl_period",
            index_method="gist",
            elements=(ExclusionElement(column_or_expr="tsrange", operator="&&"),),
            predicate=None,
        )
        new_excl = ExclusionConstraint(
            name="orders_excl_period",
            index_method="gist",
            elements=(ExclusionElement(column_or_expr="tsrange", operator="&&"),),
            predicate="is_active = true",
        )

        result = cmp.compare_sets(table_ref, source=(old_excl,), target=(new_excl,))

        assert len(result) == 2
        assert isinstance(result[0], DropConstraint)
        assert isinstance(result[1], AddConstraint)

    def test_deferrability_changed_emits_drop_then_add(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_pk = PrimaryKeyConstraint(
            name="orders_pkey",
            columns=("id",),
            deferrability=ConstraintDeferrability.NOT_DEFERRABLE,
        )
        new_pk = PrimaryKeyConstraint(
            name="orders_pkey",
            columns=("id",),
            deferrability=ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED,
        )

        result = cmp.compare_sets(table_ref, source=(old_pk,), target=(new_pk,))

        assert len(result) == 2
        assert isinstance(result[0], DropConstraint)
        assert isinstance(result[1], AddConstraint)


# ---------------------------------------------------------------------------
# Multiple constraints aggregated
# ---------------------------------------------------------------------------


class TestMultipleConstraints:
    def test_mixed_add_drop_no_change(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        old_uq = _uq("orders_uq_num")
        new_fk = _fk("orders_fk_customer")
        chk = _chk("orders_chk_total")  # identical on both sides

        result = cmp.compare_sets(
            table_ref,
            source=(pk, old_uq, chk),
            target=(pk, new_fk, chk),
        )

        # orders_fk_customer → add; orders_uq_num → drop; chk → no delta; pk → no delta
        assert len(result) == 2
        kinds = {type(d) for d in result}
        assert AddConstraint in kinds
        assert DropConstraint in kinds

    def test_all_dropped_on_empty_target(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        uq = _uq("orders_uq_num")
        chk = _chk("orders_chk_total")

        result = cmp.compare_sets(table_ref, source=(pk, uq, chk), target=())

        assert len(result) == 3
        assert all(isinstance(d, DropConstraint) for d in result)

    def test_all_added_on_empty_source(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        uq = _uq("orders_uq_num")
        chk = _chk("orders_chk_total")

        result = cmp.compare_sets(table_ref, source=(), target=(pk, uq, chk))

        assert len(result) == 3
        assert all(isinstance(d, AddConstraint) for d in result)


# ---------------------------------------------------------------------------
# Deterministic name-sorted ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_results_sorted_by_constraint_name_ascending(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        # Provide constraints in reverse alphabetical order; expect sorted output.
        c_z = _chk("zzz_check", expression="x > 0")
        c_a = _pk("aaa_pkey", columns=("id",))
        c_m = _uq("mmm_unique", columns=("code",))

        result = cmp.compare_sets(
            table_ref,
            source=(),
            target=(c_z, c_a, c_m),  # deliberately unsorted input
        )

        names = [d.target.qname.name for d in result]
        assert names == ["aaa_pkey", "mmm_unique", "zzz_check"]

    def test_drop_before_add_for_replaced_constraint(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old = _chk("the_check", expression="a > 0")
        new = _chk("the_check", expression="a >= 0")

        result = cmp.compare_sets(table_ref, source=(old,), target=(new,))

        assert len(result) == 2
        assert isinstance(result[0], DropConstraint), "Drop must come before Add"
        assert isinstance(result[1], AddConstraint), "Add must follow Drop"

    def test_mixed_ordering_across_multiple_names(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        # 'alpha' → replace (drop+add); 'beta' → add-only; 'gamma' → drop-only
        old_alpha = _chk("alpha", expression="x > 0")
        new_alpha = _chk("alpha", expression="x >= 0")
        new_beta = _uq("beta", columns=("code",))
        old_gamma = _pk("gamma", columns=("id",))

        result = cmp.compare_sets(
            table_ref,
            source=(old_alpha, old_gamma),
            target=(new_alpha, new_beta),
        )

        # Expected order: alpha-drop, alpha-add, beta-add, gamma-drop
        assert len(result) == 4
        assert result[0].target.qname.name == "alpha"
        assert isinstance(result[0], DropConstraint)
        assert result[1].target.qname.name == "alpha"
        assert isinstance(result[1], AddConstraint)
        assert result[2].target.qname.name == "beta"
        assert isinstance(result[2], AddConstraint)
        assert result[3].target.qname.name == "gamma"
        assert isinstance(result[3], DropConstraint)


# ---------------------------------------------------------------------------
# Correct ObjectRef construction
# ---------------------------------------------------------------------------


class TestObjectRefConstruction:
    def test_target_kind_is_constraint(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        result = cmp.compare_sets(table_ref, source=(), target=(pk,))

        assert result[0].target.kind is ObjectKind.CONSTRAINT

    def test_target_parent_is_table_ref(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        result = cmp.compare_sets(table_ref, source=(), target=(pk,))

        assert result[0].target.parent == table_ref

    def test_target_qname_name_equals_constraint_name(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        result = cmp.compare_sets(table_ref, source=(), target=(pk,))

        assert result[0].target.qname.name == "orders_pkey"

    def test_target_namespace_mirrors_table_namespace(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("orders_pkey")
        result = cmp.compare_sets(table_ref, source=(), target=(pk,))

        assert result[0].target.qname.namespace == "public"

    def test_non_public_namespace_propagated_correctly(self, cmp: ConstraintComparator) -> None:
        myapp_table_ref = ObjectRef(
            kind=ObjectKind.TABLE,
            qname=QualifiedName(namespace="myapp", name="payments"),
        )
        fk = _fk("payments_fk_order")
        result = cmp.compare_sets(myapp_table_ref, source=(), target=(fk,))

        assert result[0].target.qname.namespace == "myapp"
        assert result[0].target.parent == myapp_table_ref

    def test_drop_constraint_ref_is_also_correct(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        uq = _uq("orders_uq_code", columns=("code",))
        result = cmp.compare_sets(table_ref, source=(uq,), target=())

        drop = result[0]
        assert isinstance(drop, DropConstraint)
        assert drop.target.kind is ObjectKind.CONSTRAINT
        assert drop.target.parent == table_ref
        assert drop.target.qname.name == "orders_uq_code"
        assert drop.target.qname.namespace == "public"

    def test_replace_pair_both_refs_correct(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_chk = _chk("orders_chk_x", expression="x > 0")
        new_chk = _chk("orders_chk_x", expression="x >= 0")

        result = cmp.compare_sets(table_ref, source=(old_chk,), target=(new_chk,))

        drop, add = result
        for delta in (drop, add):
            assert delta.target.kind is ObjectKind.CONSTRAINT
            assert delta.target.parent == table_ref
            assert delta.target.qname.name == "orders_chk_x"
            assert delta.target.qname.namespace == "public"


# ---------------------------------------------------------------------------
# All five constraint kinds coverage in one aggregated scenario
# ---------------------------------------------------------------------------


class TestAllFiveKinds:
    def test_all_five_kinds_as_add_only(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("z_pkey")
        uq = _uq("z_unique")
        chk = _chk("z_check")
        fk = _fk("z_fk")
        excl = _excl("z_excl")

        result = cmp.compare_sets(
            table_ref,
            source=(),
            target=(pk, uq, chk, fk, excl),
        )

        assert len(result) == 5
        assert all(isinstance(d, AddConstraint) for d in result)

        add_deltas = [d for d in result if isinstance(d, AddConstraint)]
        constraint_kinds = {d.constraint.kind for d in add_deltas}
        assert constraint_kinds == {
            "primary_key",
            "unique",
            "check",
            "foreign_key",
            "exclusion",
        }

    def test_all_five_kinds_as_drop_only(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("z_pkey")
        uq = _uq("z_unique")
        chk = _chk("z_check")
        fk = _fk("z_fk")
        excl = _excl("z_excl")

        result = cmp.compare_sets(
            table_ref,
            source=(pk, uq, chk, fk, excl),
            target=(),
        )

        assert len(result) == 5
        assert all(isinstance(d, DropConstraint) for d in result)

    def test_all_five_kinds_identical_no_deltas(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        pk = _pk("z_pkey")
        uq = _uq("z_unique")
        chk = _chk("z_check")
        fk = _fk("z_fk")
        excl = _excl("z_excl")
        constraints = (pk, uq, chk, fk, excl)

        result = cmp.compare_sets(table_ref, source=constraints, target=constraints)
        assert result == ()

    def test_fk_match_type_change_emits_replace(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_fk = ForeignKeyConstraint(
            name="fk_cust",
            columns=("customer_id",),
            ref_namespace="public",
            ref_table="customers",
            ref_columns=("id",),
            match_type=FKMatch.SIMPLE,
        )
        new_fk = ForeignKeyConstraint(
            name="fk_cust",
            columns=("customer_id",),
            ref_namespace="public",
            ref_table="customers",
            ref_columns=("id",),
            match_type=FKMatch.FULL,
        )

        result = cmp.compare_sets(table_ref, source=(old_fk,), target=(new_fk,))

        assert len(result) == 2
        assert isinstance(result[0], DropConstraint)
        assert isinstance(result[1], AddConstraint)
        assert result[0].constraint == old_fk
        assert result[1].constraint == new_fk

    def test_fk_ref_table_change_emits_replace(
        self, cmp: ConstraintComparator, table_ref: ObjectRef
    ) -> None:
        old_fk = _fk("fk_cust", ref_table="customers")
        new_fk = _fk("fk_cust", ref_table="clients")

        result = cmp.compare_sets(table_ref, source=(old_fk,), target=(new_fk,))

        assert len(result) == 2
        assert isinstance(result[0], DropConstraint)
        assert isinstance(result[1], AddConstraint)
