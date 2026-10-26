from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.delta import (
    AlterPolicy,
    CreatePolicy,
    Delta,
    DeltaSet,
    DropPolicy,
    ReplacePolicy,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.policy import Policy


def _policy(*, name: str = "items_policy", **updates: object) -> Policy:
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


def test_create_and_drop_policy_validate_targets() -> None:
    policy = _policy()

    assert CreatePolicy(target=policy.ref, policy=policy).policy is policy
    assert DropPolicy(target=policy.ref, policy=policy).policy is policy

    wrong_ref = policy.ref.model_copy(
        update={"qname": QualifiedName(namespace="public", name="other")}
    )
    with pytest.raises(ValidationError, match=r"must equal policy\.ref"):
        CreatePolicy(target=wrong_ref, policy=policy)


def test_alter_policy_carries_only_changed_clauses() -> None:
    policy = _policy()
    delta = AlterPolicy(
        target=policy.ref,
        policy=policy,
        new_roles=("reader",),
        new_using_expr="id >= 0",
    )

    assert delta.new_roles == ("reader",)
    assert delta.new_using_expr == "id >= 0"
    assert delta.new_with_check_expr is None


def test_alter_policy_rejects_noop_and_unchanged_clause() -> None:
    policy = _policy()

    with pytest.raises(ValidationError, match="at least one changed clause"):
        AlterPolicy(target=policy.ref, policy=policy)
    with pytest.raises(ValidationError, match="must differ"):
        AlterPolicy(target=policy.ref, policy=policy, new_using_expr=policy.using_expr)


def test_replace_policy_round_trips_through_python_serialization() -> None:
    old = _policy()
    new = _policy(command="SELECT", permissive=False)
    delta = ReplacePolicy(target=old.ref, old_policy=old, new_policy=new)

    assert delta.old_policy is old
    assert delta.new_policy is new
    assert TypeAdapter(Delta).validate_python(delta.model_dump()) == delta


def test_replace_policy_round_trips_through_json_serialization() -> None:
    old = _policy()
    new = _policy(command="SELECT", permissive=False)
    delta = ReplacePolicy(target=old.ref, old_policy=old, new_policy=new)

    restored_delta: Delta = TypeAdapter(Delta).validate_json(delta.model_dump_json())
    assert restored_delta == delta


def test_replace_policy_delta_set_round_trips_through_json() -> None:
    old = _policy()
    new = _policy(command="SELECT", permissive=False)
    delta = ReplacePolicy(target=old.ref, old_policy=old, new_policy=new)

    restored_set: DeltaSet = TypeAdapter(DeltaSet).validate_json(
        DeltaSet(deltas=(delta,)).model_dump_json()
    )
    assert restored_set.deltas[0] == delta


def test_replace_policy_requires_same_changed_identity() -> None:
    old = _policy()
    with pytest.raises(ValidationError, match="identical policy identities"):
        ReplacePolicy(target=old.ref, old_policy=old, new_policy=_policy(name="renamed"))
    with pytest.raises(ValidationError, match="cannot represent an unchanged policy"):
        ReplacePolicy(target=old.ref, old_policy=old, new_policy=old)
