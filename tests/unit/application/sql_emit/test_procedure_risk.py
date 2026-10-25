from __future__ import annotations

import pytest

from pgschemadiff.application.sql_emit.risk import RiskLevel, classify_risk
from pgschemadiff.domain.delta import (
    AlterProcedureOwner,
    CreateProcedure,
    DeltaBase,
    DropProcedure,
    ReplaceProcedure,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.procedure import Procedure, ProcedureArgument


def _procedure(
    *,
    language: str = "sql",
    security_definer: bool = False,
    body: str = "SELECT 1",
) -> Procedure:
    ref = ObjectRef(
        kind=ObjectKind.PROCEDURE,
        qname=QualifiedName(namespace="public", name="run_task"),
        arg_signature=("integer",),
    )
    return Procedure(
        ref=ref,
        arguments=(ProcedureArgument(name="value", data_type="integer"),),
        language=language,
        security_definer=security_definer,
        body=body,
        definition="CREATE OR REPLACE PROCEDURE public.run_task(integer) ...",
        owner="app_owner",
    )


def test_procedure_create_drop_replace_and_owner_risks() -> None:
    procedure = _procedure()
    deltas = (
        CreateProcedure(target=procedure.ref, procedure=procedure),
        DropProcedure(target=procedure.ref, procedure=procedure),
        ReplaceProcedure(
            target=procedure.ref,
            old_procedure=procedure,
            new_procedure=procedure.model_copy(update={"body": "SELECT 2"}),
        ),
        AlterProcedureOwner(target=procedure.ref, procedure=procedure, new_owner="new_owner"),
    )

    assert tuple(classify_risk(delta).level for delta in deltas) == (
        RiskLevel.WARNING,
        RiskLevel.DESTRUCTIVE,
        RiskLevel.DANGEROUS,
        RiskLevel.DANGEROUS,
    )


def test_new_security_definer_procedure_is_blocked() -> None:
    procedure = _procedure(security_definer=True)
    delta = CreateProcedure(target=procedure.ref, procedure=procedure)

    assessment = classify_risk(delta)

    assert assessment.level is RiskLevel.BLOCKED
    assert "SECURITY DEFINER" in assessment.reason


def test_incompatible_procedure_replacement_is_blocked() -> None:
    procedure = _procedure()
    delta = ReplaceProcedure(
        target=procedure.ref,
        old_procedure=procedure,
        new_procedure=procedure.model_copy(update={"body": "SELECT 2"}),
        incompatible=True,
    )

    assert classify_risk(delta).level is RiskLevel.BLOCKED


@pytest.mark.parametrize(
    "delta_type", [CreateProcedure, DropProcedure, ReplaceProcedure, AlterProcedureOwner]
)
def test_unsupported_procedure_language_is_blocked_for_every_delta(delta_type: type) -> None:
    unsupported = _procedure(language="c")
    supported = _procedure()
    delta: DeltaBase
    if delta_type is CreateProcedure:
        delta = CreateProcedure(target=unsupported.ref, procedure=unsupported)
    elif delta_type is DropProcedure:
        delta = DropProcedure(target=unsupported.ref, procedure=unsupported)
    elif delta_type is ReplaceProcedure:
        delta = ReplaceProcedure(
            target=supported.ref,
            old_procedure=supported,
            new_procedure=unsupported,
        )
    else:
        delta = AlterProcedureOwner(
            target=unsupported.ref,
            procedure=unsupported,
            new_owner="new_owner",
        )

    assert classify_risk(delta).level is RiskLevel.BLOCKED
