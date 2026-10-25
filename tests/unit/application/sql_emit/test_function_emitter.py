import pytest

from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlStatement
from pgschemadiff.application.sql_emit.function_emitter import _function_signature
from pgschemadiff.application.sql_emit.registry import default_handlers
from pgschemadiff.domain.delta import (
    AlterFunctionOwner,
    CreateFunction,
    DeltaSet,
    DropFunction,
    ReplaceFunction,
)
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.shared.errors import MigrationError

_FUNCTION_REF = ObjectRef(
    kind=ObjectKind.FUNCTION,
    qname=QualifiedName(namespace="App Schema", name='Calc"Total'),
    arg_signature=("integer", '"types"."Currency"'),
)
_DEFINITION = (
    'CREATE OR REPLACE FUNCTION "App Schema"."Calc""Total"('
    'amount integer, currency "types"."Currency") RETURNS integer '
    "LANGUAGE sql IMMUTABLE AS $function$ SELECT amount $function$"
)


def _function(
    *,
    definition: str | None = _DEFINITION,
    language: str = "sql",
    owner: str | None = 'Role "Owner',
) -> Function:
    return Function(
        ref=_FUNCTION_REF,
        arguments=(
            FunctionArgument(name="amount", data_type="integer"),
            FunctionArgument(name="currency", data_type='"types"."Currency"'),
        ),
        return_type="integer",
        language=language,
        volatility="immutable",
        strict=False,
        security_definer=False,
        leakproof=False,
        parallel="unsafe",
        cost=100,
        rows=0,
        body="SELECT amount",
        definition=definition,
        owner=owner,
    )


def _emit(
    delta: CreateFunction | DropFunction | ReplaceFunction | AlterFunctionOwner,
) -> tuple[SqlStatement, ...]:
    return SqlEmitter(default_handlers()).emit(DeltaSet.from_iterable((delta,)))


def test_create_function_emits_definition_then_quoted_owner() -> None:
    delta = CreateFunction(target=_FUNCTION_REF, function=_function())

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        _DEFINITION.replace("CREATE OR REPLACE FUNCTION", "CREATE FUNCTION", 1),
        'ALTER FUNCTION "App Schema"."Calc""Total"(integer, "types"."Currency") '
        'OWNER TO "Role ""Owner"',
    )
    assert all(statement.transactional for statement in statements)
    assert all(statement.delta is delta for statement in statements)


def test_create_function_requires_a_catalog_definition() -> None:
    delta = CreateFunction(
        target=_FUNCTION_REF,
        function=_function(definition=None, owner=None),
    )

    with pytest.raises(MigrationError, match="Function definition"):
        _emit(delta)


def test_create_function_rejects_unrecognized_definition_prefix() -> None:
    delta = CreateFunction(
        target=_FUNCTION_REF,
        function=_function(definition="SELECT 1", owner=None),
    )

    with pytest.raises(MigrationError, match="unsupported pg_get_functiondef prefix"):
        _emit(delta)


def test_create_function_blocks_unsupported_language_and_default_conflict() -> None:
    unsupported = CreateFunction(
        target=_FUNCTION_REF,
        function=_function(language="c"),
    )
    conflicting = CreateFunction(
        target=_FUNCTION_REF,
        function=_function(),
        default_conflict=True,
    )

    with pytest.raises(MigrationError, match="language"):
        _emit(unsupported)
    with pytest.raises(MigrationError, match="default conflict"):
        _emit(conflicting)


def test_replace_function_emits_new_definition_without_changing_owner() -> None:
    old = _function()
    new = old.model_copy(
        update={"body": "SELECT amount + 1", "definition": _DEFINITION + " /* new */"}
    )
    delta = ReplaceFunction(target=_FUNCTION_REF, old_function=old, new_function=new)

    statements = _emit(delta)

    assert new.definition is not None
    assert tuple(statement.sql for statement in statements) == (new.definition,)
    assert statements[0].delta is delta
    assert statements[0].transactional


@pytest.mark.parametrize(
    "delta",
    [
        ReplaceFunction(
            target=_FUNCTION_REF,
            old_function=_function(),
            new_function=_function(definition=_DEFINITION + " /* new */"),
            incompatible=True,
        ),
        ReplaceFunction(
            target=_FUNCTION_REF,
            old_function=_function(),
            new_function=_function(definition=_DEFINITION + " /* new */"),
            default_conflict=True,
        ),
    ],
    ids=("incompatible", "default-conflict"),
)
def test_replace_function_blocks_unsafe_shapes(delta: ReplaceFunction) -> None:
    with pytest.raises(MigrationError):
        _emit(delta)


def test_drop_function_quotes_exact_overload_signature() -> None:
    delta = DropFunction(target=_FUNCTION_REF, function=_function(owner=None))

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'DROP FUNCTION "App Schema"."Calc""Total"(integer, "types"."Currency") RESTRICT',
    )
    assert statements[0].delta is delta
    assert statements[0].transactional


def test_function_signature_rejects_missing_overload_identity() -> None:
    malformed_ref = ObjectRef.model_construct(
        kind=ObjectKind.FUNCTION,
        qname=_FUNCTION_REF.qname,
        arg_signature=None,
    )

    with pytest.raises(MigrationError, match="argument signature"):
        _function_signature(malformed_ref)


def test_alter_function_owner_quotes_exact_overload_signature_and_role() -> None:
    delta = AlterFunctionOwner(
        target=_FUNCTION_REF,
        function=_function(owner=None),
        new_owner='New "Owner',
    )

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'ALTER FUNCTION "App Schema"."Calc""Total"(integer, "types"."Currency") '
        'OWNER TO "New ""Owner"',
    )
    assert statements[0].delta is delta
    assert statements[0].transactional
