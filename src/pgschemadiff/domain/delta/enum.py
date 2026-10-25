"""Enum-level delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef


def _check_enum_target(target: ObjectRef, payload_ref: ObjectRef | None = None) -> None:
    if target.kind is not ObjectKind.ENUM:
        raise ValueError(f"Enum delta target must have kind ENUM, got {target.kind!r}")
    if payload_ref is not None and target != payload_ref:
        raise ValueError(f"Enum delta target {target!r} must equal enum.ref {payload_ref!r}")


class CreateEnum(DeltaBase):
    """Create a PostgreSQL enum type."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_enum"] = "create_enum"

    enum: EnumType

    @model_validator(mode="after")
    def _check_target_matches_enum(self) -> Self:
        _check_enum_target(self.target, self.enum.ref)
        return self


class DropEnum(DeltaBase):
    """Drop a PostgreSQL enum type."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_enum"] = "drop_enum"

    enum: EnumType

    @model_validator(mode="after")
    def _check_target_matches_enum(self) -> Self:
        _check_enum_target(self.target, self.enum.ref)
        return self


class AddEnumValue(DeltaBase):
    """Add one enum label before/after an anchor, or append when unanchored."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["add_enum_value"] = "add_enum_value"

    label: str = Field(min_length=1)
    before: str | None = Field(default=None, min_length=1)
    after: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_anchor(self) -> Self:
        _check_enum_target(self.target)
        if self.before is not None and self.after is not None:
            raise ValueError("AddEnumValue may specify before or after, not both")
        if self.label in {self.before, self.after}:
            raise ValueError("AddEnumValue anchor must differ from label")
        return self


class AlterEnumAttrs(DeltaBase):
    """Change enum owner."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_enum_attrs"] = "alter_enum_attrs"

    new_owner: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_enum_target(self.target)
        return self


class ReplaceEnumLabels(DeltaBase):
    """Describe unsupported enum label removal, rename, or reordering."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_enum_labels"] = "replace_enum_labels"

    old_labels: tuple[str, ...]
    new_labels: tuple[str, ...]

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_enum_target(self.target)
        return self


EnumDelta = Annotated[
    CreateEnum | DropEnum | AddEnumValue | AlterEnumAttrs | ReplaceEnumLabels,
    Field(discriminator="kind"),
]
