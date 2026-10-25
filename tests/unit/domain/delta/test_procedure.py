from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.delta import (
    AlterProcedureOwner,
    CreateProcedure,
    Delta,
    DeltaSet,
    DropProcedure,
    ReplaceProcedure,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.procedure import Procedure, ProcedureArgument


def _procedure(*signature: str, body: str = "SELECT 1") -> Procedure:
    ref = ObjectRef(
        kind=ObjectKind.PROCEDURE,
        qname=QualifiedName(namespace="public", name="sample"),
        arg_signature=signature,
    )
    return Procedure(
        ref=ref,
        arguments=tuple(
            ProcedureArgument(name=f"arg{index}", data_type=data_type)
            for index, data_type in enumerate(signature, start=1)
        ),
        language="sql",
        security_definer=False,
        body=body,
        definition=(
            f"CREATE OR REPLACE PROCEDURE public.sample({', '.join(signature)}) "
            f"LANGUAGE sql AS $$ {body} $$"
        ),
    )


def test_procedure_deltas_reject_mismatched_targets() -> None:
    procedure = _procedure("integer")
    function_ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=procedure.ref.qname,
        arg_signature=procedure.ref.arg_signature,
    )

    with pytest.raises(ValidationError):
        CreateProcedure(target=function_ref, procedure=procedure)


def test_procedure_delta_union_round_trips_every_procedure_delta() -> None:
    old = _procedure("integer")
    new = _procedure("integer", body="SELECT 2")
    deltas: tuple[Delta, ...] = (
        CreateProcedure(target=old.ref, procedure=old),
        DropProcedure(target=old.ref, procedure=old),
        ReplaceProcedure(target=old.ref, old_procedure=old, new_procedure=new),
        AlterProcedureOwner(target=old.ref, procedure=old, new_owner="new_owner"),
    )

    restored = DeltaSet.model_validate_json(DeltaSet(deltas=deltas).model_dump_json())

    assert tuple(type(delta) for delta in restored) == tuple(type(delta) for delta in deltas)
    assert restored.by_target(old.ref)[2].new_procedure.body == "SELECT 2"  # type: ignore[attr-defined]


def test_incompatible_procedure_replacement_is_explicit_in_delta() -> None:
    old = _procedure("integer")
    delta = ReplaceProcedure(
        target=old.ref,
        old_procedure=old,
        new_procedure=old.model_copy(
            update={"arguments": (ProcedureArgument(name="renamed", data_type="integer"),)}
        ),
        incompatible=True,
    )

    restored = TypeAdapter[Delta](Delta).validate_json(TypeAdapter[Delta](Delta).dump_json(delta))

    assert isinstance(restored, ReplaceProcedure)
    assert restored.incompatible


def test_procedure_delta_sort_keys_include_overload_signature() -> None:
    zero = _procedure()
    integer = _procedure("integer")

    zero_delta = CreateProcedure(target=zero.ref, procedure=zero)
    integer_delta = CreateProcedure(target=integer.ref, procedure=integer)

    assert zero_delta.sort_key != integer_delta.sort_key
    assert zero_delta.sort_key < integer_delta.sort_key
