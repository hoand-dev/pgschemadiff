from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.delta import (
    AlterFunctionOwner,
    CreateFunction,
    Delta,
    DeltaSet,
    DropFunction,
    ReplaceFunction,
)
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName


def _function(*signature: str, body: str = "SELECT 1") -> Function:
    ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="public", name="sample"),
        arg_signature=signature,
    )
    return Function(
        ref=ref,
        arguments=tuple(
            FunctionArgument(name=f"arg{index}", mode="IN", data_type=data_type)
            for index, data_type in enumerate(signature, start=1)
        ),
        return_type="integer",
        language="sql",
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        body=body,
        definition=f"CREATE OR REPLACE FUNCTION public.sample() RETURNS integer AS $$ {body} $$",
    )


def test_function_deltas_reject_mismatched_targets() -> None:
    fn = _function("integer")
    other_ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="public", name="other"),
        arg_signature=("integer",),
    )

    with pytest.raises(ValidationError):
        CreateFunction(target=other_ref, function=fn)


def test_function_delta_union_round_trips_all_function_delta_types() -> None:
    old = _function("integer")
    new = _function("integer", body="SELECT 2")
    deltas: tuple[Delta, ...] = (
        CreateFunction(target=old.ref, function=old),
        DropFunction(target=old.ref, function=old),
        ReplaceFunction(target=old.ref, old_function=old, new_function=new),
        AlterFunctionOwner(target=old.ref, function=old, new_owner="new_owner"),
    )

    restored = DeltaSet.model_validate_json(DeltaSet(deltas=deltas).model_dump_json())

    assert tuple(type(delta) for delta in restored) == tuple(type(delta) for delta in deltas)
    assert restored.by_target(old.ref)[2].new_function.body == "SELECT 2"  # type: ignore[attr-defined]


def test_incompatible_function_replacement_is_explicit_in_delta_payload() -> None:
    fn = _function("integer")
    delta = ReplaceFunction(
        target=fn.ref,
        old_function=fn,
        new_function=fn.model_copy(update={"return_type": "text"}),
        incompatible=True,
    )

    adapter = TypeAdapter[Delta](Delta)
    restored: Delta = adapter.validate_json(adapter.dump_json(delta))

    assert isinstance(restored, ReplaceFunction)
    assert restored.incompatible


def test_function_delta_sort_keys_include_overload_signature() -> None:
    zero = _function()
    integer = _function("integer")

    zero_delta = CreateFunction(target=zero.ref, function=zero)
    integer_delta = CreateFunction(target=integer.ref, function=integer)

    assert zero_delta.sort_key != integer_delta.sort_key
    assert zero_delta.sort_key < integer_delta.sort_key
