"""Domain-type delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.domain_type import DomainCheck, DomainType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef


def _check_domain_target(target: ObjectRef, payload_ref: ObjectRef | None = None) -> None:
    if target.kind is not ObjectKind.DOMAIN_TYPE:
        raise ValueError(f"Domain delta target must have kind DOMAIN_TYPE, got {target.kind!r}")
    if payload_ref is not None and target != payload_ref:
        raise ValueError(f"Domain delta target {target!r} must equal domain.ref {payload_ref!r}")


class CreateDomain(DeltaBase):
    """Create a PostgreSQL domain."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_domain"] = "create_domain"

    domain: DomainType

    @model_validator(mode="after")
    def _check_target_matches_domain(self) -> Self:
        _check_domain_target(self.target, self.domain.ref)
        return self


class DropDomain(DeltaBase):
    """Drop a PostgreSQL domain."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_domain"] = "drop_domain"

    domain: DomainType

    @model_validator(mode="after")
    def _check_target_matches_domain(self) -> Self:
        _check_domain_target(self.target, self.domain.ref)
        return self


class AlterDomainDefault(DeltaBase):
    """Set or remove a domain default."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_domain_default"] = "alter_domain_default"

    new_default_expr: str | None

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_domain_target(self.target)
        return self


class AlterDomainNullability(DeltaBase):
    """Set or remove a domain's NOT NULL constraint."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_domain_nullability"] = "alter_domain_nullability"

    new_not_null: bool
    used_in_container: bool = False

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_domain_target(self.target)
        return self


class AddDomainCheck(DeltaBase):
    """Add a named domain check, validating it when PostgreSQL permits."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["add_domain_check"] = "add_domain_check"

    check: DomainCheck
    used_in_container: bool = False

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_domain_target(self.target)
        return self


class ValidateDomainCheck(DeltaBase):
    """Validate an existing NOT VALID domain check."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["validate_domain_check"] = "validate_domain_check"

    check_name: str = Field(min_length=1)
    used_in_container: bool = False

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_domain_target(self.target)
        return self


class DropDomainCheck(DeltaBase):
    """Drop a named domain check."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["drop_domain_check"] = "drop_domain_check"

    check_name: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_domain_target(self.target)
        return self


class AlterDomainAttrs(DeltaBase):
    """Change domain owner."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_domain_attrs"] = "alter_domain_attrs"

    new_owner: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_domain_target(self.target)
        return self


class ReplaceDomainType(DeltaBase):
    """Describe a blocked domain base-type or collation change."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_domain_type"] = "replace_domain_type"

    old_base_type: str = Field(min_length=1)
    new_base_type: str = Field(min_length=1)
    old_collation: str | None = None
    new_collation: str | None = None

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_domain_target(self.target)
        return self


DomainTypeDelta = Annotated[
    CreateDomain
    | DropDomain
    | AlterDomainDefault
    | AlterDomainNullability
    | AddDomainCheck
    | ValidateDomainCheck
    | DropDomainCheck
    | AlterDomainAttrs
    | ReplaceDomainType,
    Field(discriminator="kind"),
]
