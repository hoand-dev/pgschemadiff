"""Composite-type delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef


def _check_composite_target(target: ObjectRef, payload_ref: ObjectRef | None = None) -> None:
    if target.kind is not ObjectKind.COMPOSITE_TYPE:
        raise ValueError(
            f"Composite delta target must have kind COMPOSITE_TYPE, got {target.kind!r}"
        )
    if payload_ref is not None and target != payload_ref:
        raise ValueError(
            f"Composite delta target {target!r} must equal composite.ref {payload_ref!r}"
        )


class CreateCompositeType(DeltaBase):
    """Create a PostgreSQL composite type."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_composite_type"] = "create_composite_type"

    composite: CompositeType

    @model_validator(mode="after")
    def _check_target_matches_composite(self) -> Self:
        _check_composite_target(self.target, self.composite.ref)
        return self


class DropCompositeType(DeltaBase):
    """Drop a PostgreSQL composite type."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_composite_type"] = "drop_composite_type"

    composite: CompositeType

    @model_validator(mode="after")
    def _check_target_matches_composite(self) -> Self:
        _check_composite_target(self.target, self.composite.ref)
        return self


class AlterCompositeAddAttribute(DeltaBase):
    """Append one attribute to a PostgreSQL composite type."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_composite_add_attribute"] = "alter_composite_add_attribute"

    attribute: CompositeAttribute
    type_prerequisites: tuple[ObjectRef, ...] = ()

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_composite_target(self.target)
        return self


class AlterCompositeDropAttribute(DeltaBase):
    """Drop one named attribute from a PostgreSQL composite type."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_composite_drop_attribute"] = "alter_composite_drop_attribute"

    attribute_name: str = Field(min_length=1)
    type_prerequisites: tuple[ObjectRef, ...] = ()

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_composite_target(self.target)
        return self


class AlterCompositeAttributeType(DeltaBase):
    """Change one composite attribute's type and/or collation."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_composite_attribute_type"] = "alter_composite_attribute_type"

    attribute_name: str = Field(min_length=1)
    new_data_type: str = Field(min_length=1)
    new_collation: str | None = None
    old_type_prerequisites: tuple[ObjectRef, ...] = ()
    new_type_prerequisites: tuple[ObjectRef, ...] = ()

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_composite_target(self.target)
        return self


class AlterCompositeTypeAttrs(DeltaBase):
    """Change composite type owner."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_composite_type_attrs"] = "alter_composite_type_attrs"

    new_owner: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_composite_target(self.target)
        return self


class ReplaceCompositeType(DeltaBase):
    """Describe unsupported composite attribute reorder or middle insertion."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_composite_type"] = "replace_composite_type"

    old_attributes: tuple[CompositeAttribute, ...]
    new_attributes: tuple[CompositeAttribute, ...]

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_composite_target(self.target)
        return self


CompositeTypeDelta = Annotated[
    CreateCompositeType
    | DropCompositeType
    | AlterCompositeAddAttribute
    | AlterCompositeDropAttribute
    | AlterCompositeAttributeType
    | AlterCompositeTypeAttrs
    | ReplaceCompositeType,
    Field(discriminator="kind"),
]
