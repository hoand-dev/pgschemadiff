from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.database import Database
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema


def _ref(*signature: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="App Schema", name='select"value'),
        arg_signature=signature,
    )


def _function(*signature: str, name: str = 'select"value') -> Function:
    ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="App Schema", name=name),
        arg_signature=signature,
    )
    arguments = tuple(
        FunctionArgument(name=f"arg{index}", mode="IN", data_type=data_type)
        for index, data_type in enumerate(signature, start=1)
    )
    return Function(
        ref=ref,
        arguments=arguments,
        return_type="integer",
        language="sql",
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        body="SELECT 1",
        definition=(
            'CREATE OR REPLACE FUNCTION "App Schema"."select"value"() '
            "RETURNS integer LANGUAGE sql AS $$ SELECT 1 $$"
        ),
        owner="app_owner",
    )


def test_function_identity_keeps_overloads_and_zero_argument_signature_distinct() -> None:
    zero = _function()
    integer = _function("integer")
    text = _function("text")

    assert zero.ref.arg_signature == ()
    assert len({zero.ref, integer.ref, text.ref}) == 3


def test_function_preserves_argument_modes_defaults_and_output_shape() -> None:
    fn = Function(
        ref=_ref("integer"),
        arguments=(
            FunctionArgument(name="value", mode="IN", data_type="integer", default_expr="7"),
            FunctionArgument(name="label", mode="OUT", data_type="text"),
        ),
        return_type="TABLE(label text)",
        language="plpgsql",
        volatility="stable",
        strict=True,
        security_definer=False,
        leakproof=False,
        parallel="restricted",
        cost=2.5,
        rows=4,
        config=("search_path=pg_catalog",),
        body="BEGIN RETURN QUERY SELECT 'x'; END",
        definition="CREATE OR REPLACE FUNCTION public.fn(integer) ...",
    )

    assert fn.arguments[0].default_expr == "7"
    assert fn.arguments[1].mode == "OUT"
    assert fn.return_type == "TABLE(label text)"
    assert fn.is_supported


def test_function_rejects_signature_that_disagrees_with_input_arguments() -> None:
    with pytest.raises(ValidationError, match="arg_signature"):
        Function(
            ref=_ref("text"),
            arguments=(FunctionArgument(name="value", mode="IN", data_type="integer"),),
            return_type="integer",
            language="sql",
            volatility="volatile",
            strict=False,
            security_definer=False,
            leakproof=False,
            parallel="unsafe",
            cost=100,
            rows=0,
            body="SELECT 1",
            definition="CREATE OR REPLACE FUNCTION public.fn(text) ...",
        )


def test_function_marks_other_languages_unsupported_and_models_stay_frozen() -> None:
    fn = _function("integer").model_copy(update={"language": "c"})

    assert not fn.is_supported
    with pytest.raises((ValidationError, TypeError)):
        fn.body = "changed"  # type: ignore[misc]


def test_schema_and_database_aggregate_overloaded_functions() -> None:
    zero = _function()
    integer = _function("integer")
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="App Schema", name="App Schema"),
    )
    schema = Schema(ref=schema_ref, functions=(zero, integer))

    database = Database(name="test", schemas=(schema,))

    assert database.all_functions() == (zero, integer)


def test_schema_rejects_same_function_identity_twice() -> None:
    fn = _function("integer")
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="App Schema", name="App Schema"),
    )

    with pytest.raises(ValidationError, match="Duplicate function ref"):
        Schema(ref=schema_ref, functions=(fn, fn))
