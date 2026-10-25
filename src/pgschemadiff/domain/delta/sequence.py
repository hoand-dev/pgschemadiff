"""Sequence delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef
from pgschemadiff.domain.sequence import Sequence


def _check_sequence_target(target: ObjectRef, payload_ref: ObjectRef | None = None) -> None:
    if target.kind is not ObjectKind.SEQUENCE:
        raise ValueError(f"Sequence delta target must have kind SEQUENCE, got {target.kind!r}")
    if payload_ref is not None and target != payload_ref:
        raise ValueError(
            f"Sequence delta target {target!r} must equal sequence.ref {payload_ref!r}"
        )


class CreateSequence(DeltaBase):
    """Create a PostgreSQL sequence without applying runtime state."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_sequence"] = "create_sequence"

    sequence: Sequence

    @model_validator(mode="after")
    def _check_target_matches_sequence(self) -> Self:
        _check_sequence_target(self.target, self.sequence.ref)
        return self


class DropSequence(DeltaBase):
    """Drop a PostgreSQL sequence restrictively."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_sequence"] = "drop_sequence"

    sequence: Sequence

    @model_validator(mode="after")
    def _check_target_matches_sequence(self) -> Self:
        _check_sequence_target(self.target, self.sequence.ref)
        return self


class AlterSequenceOptions(DeltaBase):
    """Change supported sequence options; never restart the runtime counter."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_sequence_options"] = "alter_sequence_options"

    new_data_type: Literal["smallint", "integer", "bigint"] | None = None
    new_start: int | None = None
    new_increment: int | None = None
    new_min_value: int | None = None
    new_max_value: int | None = None
    new_cache: int | None = None
    new_cycle: bool | None = None

    @model_validator(mode="after")
    def _check_options(self) -> Self:
        _check_sequence_target(self.target)
        if all(
            value is None
            for value in (
                self.new_data_type,
                self.new_start,
                self.new_increment,
                self.new_min_value,
                self.new_max_value,
                self.new_cache,
                self.new_cycle,
            )
        ):
            raise ValueError("AlterSequenceOptions requires at least one option")
        if self.new_increment == 0:
            raise ValueError("new_increment must not be zero")
        if self.new_cache is not None and self.new_cache < 1:
            raise ValueError("new_cache must be at least 1")
        if (
            self.new_min_value is not None
            and self.new_max_value is not None
            and self.new_min_value > self.new_max_value
        ):
            raise ValueError("new_min_value must not exceed new_max_value")
        return self


class AlterSequenceOwner(DeltaBase):
    """Change the role owning a sequence."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_sequence_owner"] = "alter_sequence_owner"

    new_owner: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_target_kind(self) -> Self:
        _check_sequence_target(self.target)
        return self


class AlterSequenceOwnedBy(DeltaBase):
    """Set or clear the table-column ownership relationship."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_sequence_owned_by"] = "alter_sequence_owned_by"

    old_owned_by: ObjectRef | None = None
    new_owned_by: ObjectRef | None

    @model_validator(mode="after")
    def _check_owned_by(self) -> Self:
        _check_sequence_target(self.target)
        if self.new_owned_by is not None and self.new_owned_by.kind is not ObjectKind.COLUMN:
            raise ValueError("new_owned_by must have kind COLUMN")
        return self


SequenceDelta = Annotated[
    CreateSequence
    | DropSequence
    | AlterSequenceOptions
    | AlterSequenceOwner
    | AlterSequenceOwnedBy,
    Field(discriminator="kind"),
]
