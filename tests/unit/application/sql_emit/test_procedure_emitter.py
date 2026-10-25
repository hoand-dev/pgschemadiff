import pytest

from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlStatement
from pgschemadiff.application.sql_emit.procedure_emitter import _procedure_signature
from pgschemadiff.application.sql_emit.registry import default_handlers
from pgschemadiff.domain.delta import (
    AlterProcedureOwner,
    CreateProcedure,
    DeltaSet,
    DropProcedure,
    ReplaceProcedure,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.procedure import Procedure, ProcedureArgument
from pgschemadiff.shared.errors import MigrationError

_PROCEDURE_REF = ObjectRef(
    kind=ObjectKind.PROCEDURE,
    qname=QualifiedName(namespace="App Schema", name='Run"Task'),
    arg_signature=("integer", '"types"."Currency"'),
)
_DEFINITION = (
    'CREATE OR REPLACE PROCEDURE "App Schema"."Run""Task"('
    'IN amount integer, INOUT currency "types"."Currency") '
    "LANGUAGE sql AS $procedure$ SELECT amount $procedure$"
)


def _procedure(
    *,
    definition: str | None = _DEFINITION,
    language: str = "sql",
    owner: str | None = 'Role "Owner',
) -> Procedure:
    return Procedure(
        ref=_PROCEDURE_REF,
        arguments=(
            ProcedureArgument(name="amount", data_type="integer"),
            ProcedureArgument(name="currency", mode="INOUT", data_type='"types"."Currency"'),
        ),
        language=language,
        security_definer=False,
        body="SELECT amount",
        definition=definition,
        owner=owner,
    )


def _emit(
    delta: CreateProcedure | DropProcedure | ReplaceProcedure | AlterProcedureOwner,
) -> tuple[SqlStatement, ...]:
    return SqlEmitter(default_handlers()).emit(DeltaSet.from_iterable((delta,)))


def test_create_procedure_rewrites_prefix_then_emits_quoted_owner() -> None:
    delta = CreateProcedure(target=_PROCEDURE_REF, procedure=_procedure())

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        _DEFINITION.replace("CREATE OR REPLACE PROCEDURE", "CREATE PROCEDURE", 1),
        'ALTER PROCEDURE "App Schema"."Run""Task"(IN integer, IN "types"."Currency") '
        'OWNER TO "Role ""Owner"',
    )
    assert all(statement.transactional for statement in statements)
    assert all(statement.delta is delta for statement in statements)


def test_create_procedure_requires_catalog_definition_and_exact_prefix() -> None:
    missing = CreateProcedure(
        target=_PROCEDURE_REF,
        procedure=_procedure(definition=None, owner=None),
    )
    unrecognized = CreateProcedure(
        target=_PROCEDURE_REF,
        procedure=_procedure(definition="SELECT 1", owner=None),
    )

    with pytest.raises(MigrationError, match="Procedure definition"):
        _emit(missing)
    with pytest.raises(MigrationError, match="unsupported pg_get_functiondef prefix"):
        _emit(unrecognized)


def test_create_procedure_blocks_unsupported_language() -> None:
    with pytest.raises(MigrationError, match="language"):
        _emit(CreateProcedure(target=_PROCEDURE_REF, procedure=_procedure(language="c")))


def test_replace_procedure_emits_catalog_definition_without_owner_change() -> None:
    old = _procedure()
    new = old.model_copy(
        update={"body": "SELECT amount + 1", "definition": _DEFINITION + " /* changed */"}
    )
    delta = ReplaceProcedure(target=_PROCEDURE_REF, old_procedure=old, new_procedure=new)

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (new.definition,)
    assert statements[0].delta is delta
    assert statements[0].transactional


def test_replace_procedure_blocks_incompatible_shape() -> None:
    old = _procedure()
    delta = ReplaceProcedure(
        target=_PROCEDURE_REF,
        old_procedure=old,
        new_procedure=old.model_copy(update={"definition": _DEFINITION + " /* changed */"}),
        incompatible=True,
    )

    with pytest.raises(MigrationError, match="parameter shape"):
        _emit(delta)


def test_drop_procedure_quotes_exact_input_signature_and_uses_restrict() -> None:
    delta = DropProcedure(target=_PROCEDURE_REF, procedure=_procedure(owner=None))

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'DROP PROCEDURE "App Schema"."Run""Task"(IN integer, IN "types"."Currency") RESTRICT',
    )
    assert statements[0].delta is delta
    assert statements[0].transactional


def test_procedure_signature_rejects_missing_overload_identity() -> None:
    malformed_ref = ObjectRef.model_construct(
        kind=ObjectKind.PROCEDURE,
        qname=_PROCEDURE_REF.qname,
        arg_signature=None,
    )

    with pytest.raises(MigrationError, match="argument signature"):
        _procedure_signature(malformed_ref)


def test_alter_procedure_owner_quotes_signature_and_role() -> None:
    delta = AlterProcedureOwner(
        target=_PROCEDURE_REF,
        procedure=_procedure(owner=None),
        new_owner='New "Owner',
    )

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'ALTER PROCEDURE "App Schema"."Run""Task"(IN integer, IN "types"."Currency") '
        'OWNER TO "New ""Owner"',
    )
    assert statements[0].delta is delta
