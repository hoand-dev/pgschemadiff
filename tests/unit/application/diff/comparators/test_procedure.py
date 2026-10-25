from __future__ import annotations

from typing import Literal

from pgschemadiff.application.diff.comparators.function import FunctionComparator
from pgschemadiff.application.diff.comparators.procedure import ProcedureComparator
from pgschemadiff.application.diff.engine import DiffEngine
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import (
    AlterProcedureOwner,
    CreateProcedure,
    ReplaceFunction,
    ReplaceProcedure,
)
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.procedure import Procedure, ProcedureArgument
from pgschemadiff.domain.schema import Schema


def _procedure(
    *types: str,
    body: str = "SELECT 1",
    owner: str | None = "app_owner",
    language: str = "sql",
    name: str = "sample",
    argument_name: str = "value",
    mode: Literal["IN", "OUT", "INOUT", "VARIADIC"] = "IN",
) -> Procedure:
    ref = ObjectRef(
        kind=ObjectKind.PROCEDURE,
        qname=QualifiedName(namespace="public", name=name),
        arg_signature=types,
    )
    return Procedure(
        ref=ref,
        arguments=tuple(
            ProcedureArgument(name=argument_name, mode=mode, data_type=data_type)
            for data_type in types
        ),
        language=language,
        security_definer=False,
        body=body,
        definition=(
            f"CREATE OR REPLACE PROCEDURE public.{name}({', '.join(types)}) "
            f"LANGUAGE {language} AS $$ {body} $$"
        ),
        owner=owner,
    )


def test_procedure_comparator_creates_and_drops_exact_overloads() -> None:
    integer = _procedure("integer")
    text = _procedure("text")
    comparator = ProcedureComparator()

    created = comparator.compare(None, integer)
    dropped = comparator.compare(text, None)

    assert isinstance(created[0], CreateProcedure)
    assert created[0].target.arg_signature == ("integer",)
    assert dropped[0].target.arg_signature == ("text",)


def test_procedure_comparator_replaces_body_and_emits_owner_change_separately() -> None:
    old = _procedure("integer")
    changed = _procedure("integer", body="SELECT 2", owner="new_owner")

    deltas = ProcedureComparator().compare(old, changed)

    assert len(deltas) == 2
    replacement = next(delta for delta in deltas if isinstance(delta, ReplaceProcedure))
    owner = next(delta for delta in deltas if isinstance(delta, AlterProcedureOwner))
    assert replacement.new_procedure.body == "SELECT 2"
    assert owner.new_owner == "new_owner"


def test_procedure_comparator_marks_parameter_name_and_mode_changes_incompatible() -> None:
    old = _procedure("integer", argument_name="old_name")
    renamed = _procedure("integer", argument_name="new_name")
    changed_mode = _procedure("integer", mode="INOUT")

    renamed_delta = ProcedureComparator().compare(old, renamed)[0]
    mode_delta = ProcedureComparator().compare(old, changed_mode)[0]

    assert isinstance(renamed_delta, ReplaceProcedure)
    assert renamed_delta.incompatible
    assert isinstance(mode_delta, ReplaceProcedure)
    assert mode_delta.incompatible


def test_diff_engine_dispatches_function_and_procedure_identity_separately() -> None:
    function_ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="public", name="shared"),
        arg_signature=("integer",),
    )
    function = Function(
        ref=function_ref,
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
        definition="CREATE OR REPLACE FUNCTION public.shared(integer) RETURNS integer ...",
    )
    procedure = _procedure("integer", name="shared")
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    source = Database(
        name="source",
        schemas=(Schema(ref=schema_ref, functions=(function,), procedures=(procedure,)),),
    )
    target = Database(
        name="target",
        schemas=(
            Schema(
                ref=schema_ref,
                functions=(function.model_copy(update={"body": "SELECT 2"}),),
                procedures=(procedure.model_copy(update={"body": "SELECT 3"}),),
            ),
        ),
    )

    deltas = DiffEngine((FunctionComparator(), ProcedureComparator())).diff(source, target)

    assert len(deltas) == 2
    assert {delta.target.kind for delta in deltas} == {ObjectKind.FUNCTION, ObjectKind.PROCEDURE}
    assert all(isinstance(delta, (ReplaceFunction, ReplaceProcedure)) for delta in deltas)
