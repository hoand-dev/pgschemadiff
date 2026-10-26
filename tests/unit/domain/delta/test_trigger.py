from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.delta import (
    AlterTriggerEnabled,
    CreateTrigger,
    Delta,
    DropTrigger,
    ReplaceTrigger,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.trigger import Trigger


def _trigger(
    *, name: str = "items_audit", definition: str = "CREATE TRIGGER items_audit"
) -> Trigger:
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )
    return Trigger(
        ref=ObjectRef(
            kind=ObjectKind.TRIGGER,
            qname=QualifiedName(namespace="public", name=name),
            parent=table_ref,
        ),
        table_ref=table_ref,
        function_ref=ObjectRef(
            kind=ObjectKind.FUNCTION,
            qname=QualifiedName(namespace="public", name="audit_row"),
            arg_signature=(),
        ),
        definition=definition,
        timing="AFTER",
        events=("INSERT",),
        row_level=True,
        is_constraint=False,
        deferrable=False,
        initially_deferred=False,
        enabled="O",
    )


def test_create_and_drop_trigger_validate_payload_identity() -> None:
    trigger = _trigger()
    other = _trigger(name="other_audit")

    assert CreateTrigger(target=trigger.ref, trigger=trigger).trigger is trigger
    assert DropTrigger(target=trigger.ref, trigger=trigger).trigger is trigger
    with pytest.raises(ValidationError, match=r"must equal trigger\.ref"):
        CreateTrigger(target=other.ref, trigger=trigger)


def test_replace_trigger_requires_same_identity_and_changed_definition() -> None:
    old = _trigger()
    new = _trigger(definition="CREATE TRIGGER items_audit AFTER INSERT")

    delta = ReplaceTrigger(target=old.ref, old_trigger=old, new_trigger=new)

    assert delta.old_trigger is old
    assert delta.new_trigger is new
    with pytest.raises(ValidationError, match="identical trigger identities"):
        ReplaceTrigger(target=old.ref, old_trigger=old, new_trigger=_trigger(name="other_audit"))
    with pytest.raises(ValidationError, match="unchanged trigger"):
        ReplaceTrigger(target=old.ref, old_trigger=old, new_trigger=old)


def test_enabled_delta_requires_a_real_state_change() -> None:
    trigger = _trigger()

    assert AlterTriggerEnabled(target=trigger.ref, trigger=trigger, new_enabled="D")
    with pytest.raises(ValidationError, match="must differ"):
        AlterTriggerEnabled(target=trigger.ref, trigger=trigger, new_enabled="O")
    with pytest.raises(ValidationError, match=r"must equal trigger\.ref"):
        AlterTriggerEnabled(
            target=_trigger(name="other_audit").ref, trigger=trigger, new_enabled="D"
        )


def test_trigger_delta_json_round_trip_preserves_concrete_types() -> None:
    trigger = _trigger()
    deltas: tuple[Delta, ...] = (
        CreateTrigger(target=trigger.ref, trigger=trigger),
        DropTrigger(target=trigger.ref, trigger=trigger),
        ReplaceTrigger(
            target=trigger.ref,
            old_trigger=trigger,
            new_trigger=_trigger(definition="CREATE TRIGGER items_audit AFTER INSERT"),
        ),
        AlterTriggerEnabled(target=trigger.ref, trigger=trigger, new_enabled="D"),
    )
    adapter = TypeAdapter[Delta](Delta)

    assert tuple(adapter.validate_json(adapter.dump_json(delta)) for delta in deltas) == deltas
