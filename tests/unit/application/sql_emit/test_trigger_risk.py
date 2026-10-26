from __future__ import annotations

from typing import Literal

import pytest

from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.sql_emit.risk import RiskLevel, classify_risk
from pgschemadiff.domain.delta import (
    AlterTriggerEnabled,
    CreateTrigger,
    DeltaSet,
    DropTrigger,
    ReplaceTrigger,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.trigger import Trigger
from pgschemadiff.shared.errors import RiskGateError


def _trigger(
    *,
    definition: str = "CREATE TRIGGER audit AFTER INSERT",
    enabled: Literal["O", "D", "R", "A"] = "O",
) -> Trigger:
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )
    return Trigger(
        ref=ObjectRef(
            kind=ObjectKind.TRIGGER,
            qname=QualifiedName(namespace="public", name="audit"),
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
        enabled=enabled,
    )


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        pytest.param(
            CreateTrigger(target=_trigger().ref, trigger=_trigger()),
            RiskLevel.WARNING,
            id="create-changes-write-behavior",
        ),
        pytest.param(
            ReplaceTrigger(
                target=_trigger().ref,
                old_trigger=_trigger(),
                new_trigger=_trigger(definition="CREATE TRIGGER audit BEFORE INSERT"),
            ),
            RiskLevel.WARNING,
            id="replace-changes-write-behavior",
        ),
        pytest.param(
            DropTrigger(target=_trigger().ref, trigger=_trigger()),
            RiskLevel.DESTRUCTIVE,
            id="drop-removes-write-behavior",
        ),
        pytest.param(
            AlterTriggerEnabled(
                target=_trigger().ref,
                trigger=_trigger(),
                new_enabled="D",
            ),
            RiskLevel.DANGEROUS,
            id="disable-can-bypass-write-time-behavior",
        ),
    ],
)
def test_trigger_risk_is_explicit_and_conservative(delta: object, expected: RiskLevel) -> None:
    assessment = classify_risk(delta)  # type: ignore[arg-type]

    assert assessment.delta is delta
    assert assessment.level is expected
    assert assessment.reason.strip()


def test_enabled_state_change_risk_is_enforced_by_generate_migration() -> None:
    trigger = _trigger()
    delta = AlterTriggerEnabled(target=trigger.ref, trigger=trigger, new_enabled="D")

    with pytest.raises(RiskGateError, match="dangerous"):
        generate_migration(DeltaSet.from_iterable((delta,)), max_risk=RiskLevel.WARNING)
