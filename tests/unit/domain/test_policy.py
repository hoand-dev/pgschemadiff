from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.policy import Policy, PolicyCommand
from pgschemadiff.domain.table import Table


def _table_ref(name: str = "items") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name=name))


def _policy(**updates: object) -> Policy:
    table_ref = _table_ref()
    values: dict[str, object] = {
        "ref": ObjectRef(
            kind=ObjectKind.POLICY,
            qname=QualifiedName(namespace="public", name="items_policy"),
            parent=table_ref,
        ),
        "table_ref": table_ref,
        "command": PolicyCommand.UPDATE,
        "permissive": True,
        "roles": ("public",),
        "using_expr": "id > 0",
        "with_check_expr": "value > 0",
    }
    values.update(updates)
    return Policy(**values)  # type: ignore[arg-type]


def test_policy_has_table_parent_and_validates_commands() -> None:
    policy = _policy()

    assert policy.ref.kind is ObjectKind.POLICY
    assert policy.ref.parent == policy.table_ref
    assert policy.command is PolicyCommand.UPDATE
    assert set(PolicyCommand) == {
        PolicyCommand.ALL,
        PolicyCommand.SELECT,
        PolicyCommand.INSERT,
        PolicyCommand.UPDATE,
        PolicyCommand.DELETE,
    }


def test_policy_rejects_wrong_parent_or_namespace() -> None:
    with pytest.raises(ValidationError, match="parent must match table_ref"):
        _policy(
            ref=ObjectRef(
                kind=ObjectKind.POLICY,
                qname=QualifiedName(namespace="public", name="items_policy"),
                parent=_table_ref("other"),
            )
        )

    with pytest.raises(ValidationError, match="namespace"):
        _policy(
            ref=ObjectRef(
                kind=ObjectKind.POLICY,
                qname=QualifiedName(namespace="other", name="items_policy"),
                parent=_table_ref(),
            )
        )


@pytest.mark.parametrize("roles", [(), ("reader", "public"), ("reader", "reader")])
def test_policy_requires_nonempty_sorted_unique_roles(roles: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        _policy(roles=roles)


@pytest.mark.parametrize("expression", ["", "  ", "?"])
def test_policy_rejects_unusable_catalog_expressions(expression: str) -> None:
    with pytest.raises(ValidationError):
        _policy(using_expr=expression)


def test_policy_is_frozen() -> None:
    policy = _policy()

    with pytest.raises(ValidationError):
        policy.permissive = False  # type: ignore[misc]


def test_table_owns_policies_and_rls_state_defaults_off() -> None:
    policy = _policy()
    table = Table(ref=policy.table_ref, policies=(policy,))

    assert table.row_security is False
    assert table.force_row_security is False
    assert table.policies == (policy,)
    assert (
        Table(
            ref=policy.table_ref,
            policies=(policy,),
            row_security=True,
            force_row_security=True,
        ).force_row_security
        is True
    )


def test_policy_rejects_unsorted_roles() -> None:
    with pytest.raises(ValidationError):
        _policy(roles=("reader", "public"))
