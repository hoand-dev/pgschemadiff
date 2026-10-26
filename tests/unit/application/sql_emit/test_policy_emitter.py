from __future__ import annotations

import pytest

from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlStatement
from pgschemadiff.application.sql_emit.registry import default_handlers
from pgschemadiff.domain.delta import AlterPolicy, CreatePolicy, DeltaSet, DropPolicy, ReplacePolicy
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.policy import Policy, PolicyCommand
from pgschemadiff.shared.errors import MigrationError

_TABLE_REF = ObjectRef(
    kind=ObjectKind.TABLE,
    qname=QualifiedName(namespace='App "Schema', name="Order"),
)


def _policy(**updates: object) -> Policy:
    values: dict[str, object] = {
        "ref": ObjectRef(
            kind=ObjectKind.POLICY,
            qname=QualifiedName(namespace='App "Schema', name='read"policy'),
            parent=_TABLE_REF,
        ),
        "table_ref": _TABLE_REF,
        "command": PolicyCommand.UPDATE,
        "permissive": True,
        "roles": ("PGSD Reader", 'pgsd "writer', "public"),
        "using_expr": "id > 0",
        "with_check_expr": "value > 0",
    }
    values.update(updates)
    return Policy(**values)  # type: ignore[arg-type]


def _emit(
    delta: CreatePolicy | DropPolicy | AlterPolicy | ReplacePolicy,
) -> tuple[SqlStatement, ...]:
    return SqlEmitter(default_handlers()).emit(DeltaSet.from_iterable((delta,)))


def test_create_policy_quotes_names_roles_and_emits_optional_expressions() -> None:
    policy = _policy()
    delta = CreatePolicy(target=policy.ref, policy=policy)

    (statement,) = _emit(delta)

    assert statement.sql == (
        'CREATE POLICY "read""policy" ON "App ""Schema"."Order" AS PERMISSIVE '
        'FOR UPDATE TO "PGSD Reader", "pgsd ""writer", PUBLIC USING (id > 0) '
        "WITH CHECK (value > 0)"
    )
    assert statement.transactional is True
    assert statement.delta is delta


def test_create_policy_omits_absent_expressions_and_emits_restrictive_all() -> None:
    policy = _policy(
        command=PolicyCommand.ALL, permissive=False, roles=("public",), using_expr=None
    )
    delta = CreatePolicy(target=policy.ref, policy=policy)

    (statement,) = _emit(delta)

    assert statement.sql == (
        'CREATE POLICY "read""policy" ON "App ""Schema"."Order" AS RESTRICTIVE '
        "FOR ALL TO PUBLIC WITH CHECK (value > 0)"
    )


def test_alter_policy_emits_only_changed_clauses() -> None:
    policy = _policy()
    delta = AlterPolicy(
        target=policy.ref,
        policy=policy,
        new_roles=("public",),
        new_using_expr="id >= 0",
    )

    (statement,) = _emit(delta)

    assert statement.sql == (
        'ALTER POLICY "read""policy" ON "App ""Schema"."Order" TO PUBLIC USING (id >= 0)'
    )
    assert statement.delta is delta


def test_drop_policy_uses_owning_table() -> None:
    policy = _policy()
    delta = DropPolicy(target=policy.ref, policy=policy)

    (statement,) = _emit(delta)

    assert statement.sql == 'DROP POLICY "read""policy" ON "App ""Schema"."Order"'
    assert statement.delta is delta


def test_replace_policy_drops_then_creates_in_one_transactional_delta() -> None:
    old = _policy()
    new = old.model_copy(update={"command": PolicyCommand.SELECT, "permissive": False})
    delta = ReplacePolicy(target=old.ref, old_policy=old, new_policy=new)

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'DROP POLICY "read""policy" ON "App ""Schema"."Order"',
        'CREATE POLICY "read""policy" ON "App ""Schema"."Order" AS RESTRICTIVE '
        'FOR SELECT TO "PGSD Reader", "pgsd ""writer", PUBLIC USING (id > 0) '
        "WITH CHECK (value > 0)",
    )
    assert all(statement.transactional and statement.delta is delta for statement in statements)


def test_policy_emitter_rejects_deparser_sentinel() -> None:
    policy = _policy().model_copy(update={"using_expr": "?"})
    delta = CreatePolicy.model_construct(target=policy.ref, policy=policy)

    with pytest.raises(MigrationError, match="USING expression"):
        _emit(delta)
