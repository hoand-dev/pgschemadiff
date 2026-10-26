from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.policy import PolicyComparator
from pgschemadiff.application.diff.comparators.table import TableComparator
from pgschemadiff.application.diff.engine import Comparator, DiffEngine
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import (
    AlterPolicy,
    AlterTableAttrs,
    CreatePolicy,
    DropPolicy,
    ReplacePolicy,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.policy import Policy
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.shared.errors import DiffError


def _policy(name: str = "items_policy", **updates: object) -> Policy:
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )
    values: dict[str, object] = {
        "ref": ObjectRef(
            kind=ObjectKind.POLICY,
            qname=QualifiedName(namespace="public", name=name),
            parent=table_ref,
        ),
        "table_ref": table_ref,
        "command": "UPDATE",
        "permissive": True,
        "roles": ("public",),
        "using_expr": "id > 0",
        "with_check_expr": "value > 0",
    }
    values.update(updates)
    return Policy(**values)  # type: ignore[arg-type]


def test_policy_comparator_creates_and_drops() -> None:
    policy = _policy()
    comparator = PolicyComparator()

    assert isinstance(comparator, Comparator)
    assert comparator.compare(None, policy) == (CreatePolicy(target=policy.ref, policy=policy),)
    assert comparator.compare(policy, None) == (DropPolicy(target=policy.ref, policy=policy),)
    assert comparator.compare(None, None) == ()


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"roles": ("reader",)}, "roles"),
        ({"using_expr": "id >= 0"}, "using"),
        ({"with_check_expr": "value >= 0"}, "with_check"),
    ],
)
def test_policy_comparator_alters_roles_and_expressions(
    updates: dict[str, object], expected: str
) -> None:
    old = _policy()
    new = old.model_copy(update=updates)

    (delta,) = PolicyComparator().compare(old, new)

    assert isinstance(delta, AlterPolicy)
    assert delta.policy is old
    if expected == "roles":
        assert delta.new_roles == ("reader",)
    elif expected == "using":
        assert delta.new_using_expr == "id >= 0"
    else:
        assert delta.new_with_check_expr == "value >= 0"


@pytest.mark.parametrize(
    "updates",
    [{"command": "SELECT"}, {"permissive": False}],
    ids=("command", "permissiveness"),
)
def test_policy_comparator_replaces_when_command_or_permissiveness_changes(
    updates: dict[str, object],
) -> None:
    old = _policy()
    new = old.model_copy(update=updates)

    (delta,) = PolicyComparator().compare(old, new)

    assert isinstance(delta, ReplacePolicy)
    assert delta.old_policy is old
    assert delta.new_policy is new


@pytest.mark.parametrize("field", ["using_expr", "with_check_expr"])
def test_policy_comparator_replaces_when_alter_cannot_clear_clause(field: str) -> None:
    old = _policy()
    new = old.model_copy(update={field: None})

    (delta,) = PolicyComparator().compare(old, new)

    assert isinstance(delta, ReplacePolicy)


def test_policy_comparator_rejects_distinct_identities() -> None:
    with pytest.raises(DiffError, match="distinct policy identities"):
        PolicyComparator().compare(_policy(), _policy(name="other"))


def test_policy_comparator_is_registered_in_object_ref_engine_fetcher() -> None:
    policy = _policy()
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    source = Database(
        name="source",
        schemas=(
            Schema(
                ref=schema_ref,
                tables=(Table(ref=policy.table_ref, policies=(policy,)),),
            ),
        ),
    )
    target = Database(
        name="target",
        schemas=(Schema(ref=schema_ref, tables=(Table(ref=policy.table_ref),)),),
    )

    assert DiffEngine((PolicyComparator(),)).diff(source, target).by_target(policy.ref) == (
        DropPolicy(target=policy.ref, policy=policy),
    )


def test_table_comparator_diffs_row_security_flags() -> None:
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )
    source = Table(ref=table_ref)
    target = Table(ref=table_ref, row_security=True, force_row_security=True)

    (delta,) = TableComparator().compare(source, target)

    assert isinstance(delta, AlterTableAttrs)
    assert delta.new_row_security is True
    assert delta.new_force_row_security is True
