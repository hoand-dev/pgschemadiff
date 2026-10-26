"""Row-level security policy deltas."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef
from pgschemadiff.domain.policy import Policy


def _check_target(target: ObjectRef, policy_ref: ObjectRef) -> None:
    if target.kind is not ObjectKind.POLICY:
        raise ValueError(f"Policy delta target must have kind POLICY, got {target.kind!r}")
    if target != policy_ref:
        raise ValueError(f"Policy delta target {target!r} must equal policy.ref {policy_ref!r}")


def _check_expression(expression: str | None) -> str | None:
    if expression is not None and (not expression.strip() or expression.strip() == "?"):
        raise ValueError("Policy expression must be a usable catalog expression")
    return expression


class CreatePolicy(DeltaBase):
    """Create one PostgreSQL row-security policy."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_policy"] = "create_policy"

    policy: Policy

    @model_validator(mode="after")
    def _check_target_matches_policy(self) -> Self:
        _check_target(self.target, self.policy.ref)
        return self


class DropPolicy(DeltaBase):
    """Drop one PostgreSQL row-security policy."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_policy"] = "drop_policy"

    policy: Policy

    @model_validator(mode="after")
    def _check_target_matches_policy(self) -> Self:
        _check_target(self.target, self.policy.ref)
        return self


class AlterPolicy(DeltaBase):
    """Alter roles or catalog-deparsed expressions without changing policy kind."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_policy"] = "alter_policy"

    policy: Policy
    new_roles: tuple[str, ...] | None = None
    new_using_expr: str | None = None
    new_with_check_expr: str | None = None

    @field_validator("new_roles")
    @classmethod
    def _check_roles(cls, roles: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if roles is not None:
            if not roles or any(not role.strip() for role in roles):
                raise ValueError("Policy roles must be non-empty names")
            if roles != tuple(sorted(roles)):
                raise ValueError("Policy roles must be sorted")
            if len(roles) != len(set(roles)):
                raise ValueError("Policy roles must be unique")
        return roles

    @field_validator("new_using_expr", "new_with_check_expr")
    @classmethod
    def _check_new_expression(cls, expression: str | None) -> str | None:
        return _check_expression(expression)

    @model_validator(mode="after")
    def _check_changes(self) -> Self:
        _check_target(self.target, self.policy.ref)
        changes = (
            (self.new_roles, self.policy.roles),
            (self.new_using_expr, self.policy.using_expr),
            (self.new_with_check_expr, self.policy.with_check_expr),
        )
        if all(new is None for new, _ in changes):
            raise ValueError("AlterPolicy requires at least one changed clause")
        if any(new is not None and new == old for new, old in changes):
            raise ValueError("AlterPolicy values must differ from current clauses")
        return self


class ReplacePolicy(DeltaBase):
    """Replace a policy when ALTER POLICY cannot represent the desired state."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_policy"] = "replace_policy"

    old_policy: Policy
    new_policy: Policy

    @model_validator(mode="after")
    def _check_replace_consistency(self) -> Self:
        _check_target(self.target, self.old_policy.ref)
        if self.old_policy.ref != self.new_policy.ref:
            raise ValueError("ReplacePolicy requires identical policy identities")
        if self.old_policy == self.new_policy:
            raise ValueError("ReplacePolicy cannot represent an unchanged policy")
        return self


PolicyDelta = Annotated[
    CreatePolicy | DropPolicy | AlterPolicy | ReplacePolicy,
    Field(discriminator="kind"),
]
