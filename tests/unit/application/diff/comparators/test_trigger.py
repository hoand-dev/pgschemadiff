from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.trigger import TriggerComparator
from pgschemadiff.application.diff.engine import DiffEngine
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import (
    AlterTriggerEnabled,
    CreateTrigger,
    DropTrigger,
    ReplaceTrigger,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.domain.trigger import Trigger
from pgschemadiff.shared.errors import DiffError


def _trigger(*, name: str = "items_audit", **updates: object) -> Trigger:
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )
    values: dict[str, object] = {
        "ref": ObjectRef(
            kind=ObjectKind.TRIGGER,
            qname=QualifiedName(namespace="public", name=name),
            parent=table_ref,
        ),
        "table_ref": table_ref,
        "function_ref": ObjectRef(
            kind=ObjectKind.FUNCTION,
            qname=QualifiedName(namespace="public", name="audit_row"),
            arg_signature=(),
        ),
        "definition": 'CREATE TRIGGER "items_audit" AFTER INSERT ON "public"."items"',
        "timing": "AFTER",
        "events": ("INSERT",),
        "row_level": True,
        "is_constraint": False,
        "deferrable": False,
        "initially_deferred": False,
        "enabled": "O",
    }
    values.update(updates)
    return Trigger(**values)  # type: ignore[arg-type]


def test_trigger_comparator_creates_and_drops() -> None:
    trigger = _trigger()

    assert TriggerComparator().compare(None, trigger) == (
        CreateTrigger(target=trigger.ref, trigger=trigger),
    )
    assert TriggerComparator().compare(trigger, None) == (
        DropTrigger(target=trigger.ref, trigger=trigger),
    )
    assert TriggerComparator().compare(None, None) == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("definition", "CREATE TRIGGER items_audit BEFORE INSERT ON public.items"),
        ("timing", "BEFORE"),
        ("events", ("UPDATE",)),
        ("row_level", False),
        ("columns", ("value",)),
        ("when_expr", "NEW.value > 0"),
        (
            "function_ref",
            ObjectRef(
                kind=ObjectKind.FUNCTION,
                qname=QualifiedName(namespace="public", name="other_function"),
                arg_signature=(),
            ),
        ),
        ("is_constraint", True),
        ("deferrable", True),
        ("initially_deferred", True),
    ],
)
def test_trigger_comparator_replaces_definition_or_structured_semantics(
    field: str,
    value: object,
) -> None:
    old = _trigger(
        is_constraint=field in {"deferrable", "initially_deferred"},
        deferrable=field == "initially_deferred",
    )
    new = old.model_copy(update={field: value})

    (delta,) = TriggerComparator().compare(old, new)

    assert isinstance(delta, ReplaceTrigger)
    assert delta.old_trigger is old
    assert delta.new_trigger is new


def test_trigger_comparator_emits_enabled_state_only_delta() -> None:
    old = _trigger()
    new = _trigger(enabled="R")

    (delta,) = TriggerComparator().compare(old, new)

    assert isinstance(delta, AlterTriggerEnabled)
    assert delta.trigger is old
    assert delta.new_enabled == "R"


def test_trigger_comparator_replacement_carries_enabled_state_transition_once() -> None:
    old = _trigger(enabled="D")
    new = _trigger(definition="CREATE TRIGGER items_audit BEFORE INSERT", enabled="A")

    (delta,) = TriggerComparator().compare(old, new)

    assert isinstance(delta, ReplaceTrigger)
    assert delta.new_trigger.enabled == "A"


def test_trigger_comparator_rejects_distinct_trigger_identities() -> None:
    with pytest.raises(DiffError, match="distinct trigger identities"):
        TriggerComparator().compare(_trigger(), _trigger(name="other_audit"))


def test_diff_engine_fetches_table_owned_triggers_by_object_ref() -> None:
    trigger = _trigger()
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    source = Database(
        name="source",
        schemas=(
            Schema(ref=schema_ref, tables=(Table(ref=trigger.table_ref, triggers=(trigger,)),)),
        ),
    )
    target = Database(
        name="target",
        schemas=(Schema(ref=schema_ref, tables=(Table(ref=trigger.table_ref),)),),
    )

    assert DiffEngine((TriggerComparator(),)).diff(source, target).by_target(trigger.ref) == (
        DropTrigger(target=trigger.ref, trigger=trigger),
    )
