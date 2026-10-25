from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.database import Database
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.procedure import Procedure, ProcedureArgument
from pgschemadiff.domain.schema import Schema


def _ref(*signature: str, kind: ObjectKind = ObjectKind.PROCEDURE) -> ObjectRef:
    return ObjectRef(
        kind=kind,
        qname=QualifiedName(namespace="App Schema", name='do"work'),
        arg_signature=signature,
    )


def _procedure(*signature: str, name: str = 'do"work') -> Procedure:
    ref = ObjectRef(
        kind=ObjectKind.PROCEDURE,
        qname=QualifiedName(namespace="App Schema", name=name),
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
        body="SELECT 1",
        definition=(
            'CREATE OR REPLACE PROCEDURE "App Schema"."do""work"() LANGUAGE sql AS $$ SELECT 1 $$'
        ),
        owner="app_owner",
    )


def test_procedure_identity_uses_input_signature_and_out_is_not_identity() -> None:
    proc = Procedure(
        ref=_ref("integer"),
        arguments=(
            ProcedureArgument(name="value", mode="IN", data_type="integer"),
            ProcedureArgument(name="result", mode="OUT", data_type="text"),
        ),
        language="plpgsql",
        security_definer=False,
        body="BEGIN result := value::text; END",
        definition="CREATE OR REPLACE PROCEDURE public.work(IN integer, OUT text) ...",
    )

    assert proc.ref.arg_signature == ("integer",)
    assert tuple(argument.mode for argument in proc.arguments) == ("IN", "OUT")


def test_procedure_rejects_signature_that_disagrees_with_input_arguments() -> None:
    with pytest.raises(ValidationError, match="arg_signature"):
        Procedure(
            ref=_ref("text"),
            arguments=(ProcedureArgument(name="value", data_type="integer"),),
            language="sql",
            security_definer=False,
            body="SELECT 1",
            definition="CREATE OR REPLACE PROCEDURE public.work(integer) ...",
        )


def test_procedure_models_security_config_defaults_and_is_frozen() -> None:
    proc = Procedure(
        ref=_ref("integer"),
        arguments=(ProcedureArgument(name="value", data_type="integer", default_expr="7"),),
        language="plpgsql",
        security_definer=False,
        transforms=("jsonb",),
        config=("search_path=pg_catalog",),
        default_expressions="7",
        default_count=1,
        body="BEGIN RAISE NOTICE '%', value; END",
        definition="CREATE OR REPLACE PROCEDURE public.work(integer) ...",
        owner="app_owner",
    )

    assert proc.arguments[0].default_expr == "7"
    assert proc.config == ("search_path=pg_catalog",)
    assert proc.is_supported
    with pytest.raises((ValidationError, TypeError)):
        proc.body = "changed"  # type: ignore[misc]


def test_procedure_marks_unsupported_language() -> None:
    assert not _procedure("integer").model_copy(update={"language": "c"}).is_supported


def test_function_and_procedure_identity_do_not_collide() -> None:
    function_ref = _ref("integer", kind=ObjectKind.FUNCTION)
    procedure_ref = _ref("integer")

    assert function_ref.qname == procedure_ref.qname
    assert function_ref.arg_signature == procedure_ref.arg_signature
    assert function_ref != procedure_ref


def test_schema_and_database_aggregate_overloaded_procedures() -> None:
    zero = _procedure()
    integer = _procedure("integer")
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="App Schema", name="App Schema"),
    )

    database = Database(name="test", schemas=(Schema(ref=schema_ref, procedures=(zero, integer)),))

    assert database.all_procedures() == (zero, integer)


def test_schema_keeps_function_and_procedure_with_matching_signature_separate() -> None:
    procedure = _procedure("integer")
    function = Function(
        ref=_ref("integer", kind=ObjectKind.FUNCTION),
        arguments=(FunctionArgument(name="value", data_type="integer"),),
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
        definition="CREATE OR REPLACE FUNCTION public.do_work(integer) RETURNS integer ...",
    )
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="App Schema", name="App Schema"),
    )

    schema = Schema(ref=schema_ref, functions=(function,), procedures=(procedure,))

    assert schema.functions[0].ref != schema.procedures[0].ref


def test_schema_rejects_duplicate_procedure_identity() -> None:
    procedure = _procedure("integer")
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="App Schema", name="App Schema"),
    )

    with pytest.raises(ValidationError, match="Duplicate procedure ref"):
        Schema(ref=schema_ref, procedures=(procedure, procedure))
