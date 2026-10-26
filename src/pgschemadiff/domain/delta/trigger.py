"""Trigger delta types."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef
from pgschemadiff.domain.trigger import Trigger


def _check_target(target: ObjectRef, trigger_ref: ObjectRef) -> None:
    if target.kind is not ObjectKind.TRIGGER:
        raise ValueError(f"Trigger delta target must have kind TRIGGER, got {target.kind!r}")
    if target != trigger_ref:
        raise ValueError(f"Trigger delta target {target!r} must equal trigger.ref {trigger_ref!r}")


class CreateTrigger(DeltaBase):
    """Create one PostgreSQL trigger."""

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_trigger"] = "create_trigger"

    trigger: Trigger

    @model_validator(mode="after")
    def _check_target_matches_trigger(self) -> Self:
        _check_target(self.target, self.trigger.ref)
        return self


class DropTrigger(DeltaBase):
    """Drop one PostgreSQL trigger restrictively."""

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_trigger"] = "drop_trigger"

    trigger: Trigger

    @model_validator(mode="after")
    def _check_target_matches_trigger(self) -> Self:
        _check_target(self.target, self.trigger.ref)
        return self


class ReplaceTrigger(DeltaBase):
    """Replace a trigger definition, dropping constraint triggers when required."""

    op: Literal[DeltaOp.REPLACE] = DeltaOp.REPLACE
    kind: Literal["replace_trigger"] = "replace_trigger"

    old_trigger: Trigger
    new_trigger: Trigger

    @model_validator(mode="after")
    def _check_replace_consistency(self) -> Self:
        _check_target(self.target, self.old_trigger.ref)
        if self.old_trigger.ref != self.new_trigger.ref:
            raise ValueError("ReplaceTrigger requires identical trigger identities")
        if self.old_trigger == self.new_trigger:
            raise ValueError("ReplaceTrigger cannot represent an unchanged trigger")
        return self


class AlterTriggerEnabled(DeltaBase):
    """Change a trigger's origin/replica/always enabled state."""

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_trigger_enabled"] = "alter_trigger_enabled"

    trigger: Trigger
    new_enabled: Literal["O", "D", "R", "A"]

    @model_validator(mode="after")
    def _check_enabled_change(self) -> Self:
        _check_target(self.target, self.trigger.ref)
        if self.new_enabled == self.trigger.enabled:
            raise ValueError("New trigger enabled state must differ from current state")
        return self


TriggerDelta = Annotated[
    CreateTrigger | DropTrigger | ReplaceTrigger | AlterTriggerEnabled,
    Field(discriminator="kind"),
]
