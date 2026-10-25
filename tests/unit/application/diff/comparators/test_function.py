from __future__ import annotations

from pgschemadiff.application.diff.comparators.function import FunctionComparator
from pgschemadiff.application.diff.engine import DiffEngine
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import AlterFunctionOwner, CreateFunction, ReplaceFunction
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema


def _function(
    *types: str,
    body: str = "SELECT 1",
    owner: str | None = "app_owner",
    language: str = "sql",
    return_type: str = "integer",
    defaults: str | None = None,
    default_count: int = 0,
    name: str = "sample",
) -> Function:
    ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="public", name=name),
        arg_signature=types,
    )
    return Function(
        ref=ref,
        arguments=tuple(
            FunctionArgument(name=f"arg{index}", data_type=data_type)
            for index, data_type in enumerate(types, start=1)
        ),
        return_type=return_type,
        language=language,
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        default_expressions=defaults,
        default_count=default_count,
        body=body,
        definition=(
            f"CREATE OR REPLACE FUNCTION public.{name}({', '.join(types)}) "
            f"RETURNS {return_type} LANGUAGE {language} AS $$ {body} $$"
        ),
        owner=owner,
    )


def test_function_comparator_creates_and_drops_exact_overloads() -> None:
    integer = _function("integer")
    text = _function("text")
    comparator = FunctionComparator()

    created = comparator.compare(None, integer)
    dropped = comparator.compare(text, None)

    assert isinstance(created[0], CreateFunction)
    assert created[0].target.arg_signature == ("integer",)
    assert dropped[0].target.arg_signature == ("text",)


def test_function_comparator_replaces_semantics_but_emits_owner_separately() -> None:
    old = _function("integer")
    changed = _function("integer", body="SELECT 2", owner="new_owner")

    deltas = FunctionComparator().compare(old, changed)

    assert len(deltas) == 2
    replacement = next(delta for delta in deltas if isinstance(delta, ReplaceFunction))
    owner = next(delta for delta in deltas if isinstance(delta, AlterFunctionOwner))
    assert replacement.new_function.body == "SELECT 2"
    assert owner.new_owner == "new_owner"


def test_function_comparator_marks_return_type_changes_incompatible() -> None:
    old = _function("integer")
    changed = _function("integer", return_type="text")

    delta = FunctionComparator().compare(old, changed)[0]

    assert isinstance(delta, ReplaceFunction)
    assert delta.incompatible


def test_function_comparator_blocks_defaults_that_conflict_with_an_overload() -> None:
    old = _function("integer", "text")
    changed = _function("integer", "text", defaults="'fallback'", default_count=1)
    short_overload = _function("integer")

    delta = FunctionComparator(target_functions=(changed, short_overload)).compare(old, changed)[0]

    assert isinstance(delta, ReplaceFunction)
    assert delta.default_conflict


def test_diff_engine_pairs_overloads_by_full_function_ref() -> None:
    integer = _function("integer")
    text = _function("text")
    changed_integer = _function("integer", body="SELECT 2")
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    source = Database(
        name="source",
        schemas=(Schema(ref=schema_ref, functions=(integer, text)),),
    )
    target = Database(
        name="target",
        schemas=(Schema(ref=schema_ref, functions=(text, changed_integer)),),
    )

    deltas = DiffEngine((FunctionComparator(),)).diff(source, target)

    assert len(deltas) == 1
    assert isinstance(deltas.deltas[0], ReplaceFunction)
    assert deltas.deltas[0].target.arg_signature == ("integer",)
