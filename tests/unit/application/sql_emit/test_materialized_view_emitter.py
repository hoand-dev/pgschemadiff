from __future__ import annotations

import pytest

from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlStatement
from pgschemadiff.application.sql_emit.registry import default_handlers
from pgschemadiff.domain.delta import DeltaSet
from pgschemadiff.domain.delta.materialized_view import (
    AlterMaterializedViewOwner,
    CreateMaterializedView,
    DropMaterializedView,
    ReplaceMaterializedView,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.materialized_view import MaterializedView
from pgschemadiff.shared.errors import MigrationError

_REF = ObjectRef(
    kind=ObjectKind.MATERIALIZED_VIEW,
    qname=QualifiedName(namespace="App Schema", name='Mixed"View'),
)


def _view(
    *,
    definition: str = 'SELECT "id", "select" FROM "App Schema"."Items"',
    columns: tuple[tuple[str, str], ...] = (("id", "integer"), ("select", "text")),
    access_method: str | None = "heap",
    tablespace: str | None = "fast space",
    storage_parameters: tuple[str, ...] = ("fillfactor=70", "autovacuum_enabled=false"),
    owner: str | None = 'Role "Owner',
    has_indexes: bool = False,
) -> MaterializedView:
    return MaterializedView(
        ref=_REF,
        columns=columns,
        definition=definition,
        access_method=access_method,
        tablespace=tablespace,
        storage_parameters=storage_parameters,
        owner=owner,
        has_indexes=has_indexes,
    )


def _emit(
    delta: CreateMaterializedView
    | DropMaterializedView
    | ReplaceMaterializedView
    | AlterMaterializedViewOwner,
) -> tuple[SqlStatement, ...]:
    return SqlEmitter(default_handlers()).emit(DeltaSet.from_iterable((delta,)))


def test_create_materialized_view_emits_physical_options_data_and_owner() -> None:
    delta = CreateMaterializedView(target=_REF, materialized_view=_view())

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'CREATE MATERIALIZED VIEW "App Schema"."Mixed""View" ("id", "select") '
        'USING "heap" WITH (fillfactor=70, autovacuum_enabled=false) '
        'TABLESPACE "fast space" AS SELECT "id", "select" FROM "App Schema"."Items" WITH DATA',
        'ALTER MATERIALIZED VIEW "App Schema"."Mixed""View" OWNER TO "Role ""Owner"',
    )
    assert all(statement.transactional and statement.delta is delta for statement in statements)
    assert all("REFRESH" not in statement.sql for statement in statements)


def test_create_materialized_view_omits_default_options_and_strips_catalog_semicolon() -> None:
    view = _view(
        definition=" SELECT id FROM public.items;\n",
        columns=(("id", "integer"),),
        access_method=None,
        tablespace=None,
        storage_parameters=(),
        owner=None,
    )

    statements = _emit(CreateMaterializedView(target=_REF, materialized_view=view))

    assert tuple(statement.sql for statement in statements) == (
        'CREATE MATERIALIZED VIEW "App Schema"."Mixed""View" ("id") '
        "AS  SELECT id FROM public.items WITH DATA",
    )


def test_drop_materialized_view_uses_restrict() -> None:
    delta = DropMaterializedView(target=_REF, materialized_view=_view(owner=None))

    assert tuple(statement.sql for statement in _emit(delta)) == (
        'DROP MATERIALIZED VIEW "App Schema"."Mixed""View" RESTRICT',
    )


def test_replace_materialized_view_drops_then_creates_transactionally() -> None:
    old = _view(owner=None)
    new = _view(definition='SELECT "id" + 1 AS "id", "select" FROM "App Schema"."Items"')
    delta = ReplaceMaterializedView(
        target=_REF,
        old_materialized_view=old,
        new_materialized_view=new,
    )

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'DROP MATERIALIZED VIEW "App Schema"."Mixed""View" RESTRICT',
        'CREATE MATERIALIZED VIEW "App Schema"."Mixed""View" ("id", "select") '
        'USING "heap" WITH (fillfactor=70, autovacuum_enabled=false) '
        'TABLESPACE "fast space" AS SELECT "id" + 1 AS "id", "select" '
        'FROM "App Schema"."Items" WITH DATA',
        'ALTER MATERIALIZED VIEW "App Schema"."Mixed""View" OWNER TO "Role ""Owner"',
    )
    assert all(statement.transactional and statement.delta is delta for statement in statements)


def test_alter_materialized_view_owner_quotes_role() -> None:
    delta = AlterMaterializedViewOwner(
        target=_REF,
        materialized_view=_view(owner=None),
        new_owner='New "Owner',
    )

    assert tuple(statement.sql for statement in _emit(delta)) == (
        'ALTER MATERIALIZED VIEW "App Schema"."Mixed""View" OWNER TO "New ""Owner"',
    )


def test_invalid_catalog_definition_is_rejected() -> None:
    view = _view(definition="?", owner=None)
    delta = CreateMaterializedView(target=_REF, materialized_view=view)

    with pytest.raises(MigrationError, match="usable SQL fragment"):
        _emit(delta)
