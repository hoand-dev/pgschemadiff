from typing import Literal

import pytest

from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlStatement
from pgschemadiff.application.sql_emit.registry import default_handlers
from pgschemadiff.domain.delta import (
    AlterViewOwner,
    CreateView,
    DeltaSet,
    DropView,
    ReplaceView,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.view import View
from pgschemadiff.shared.errors import MigrationError

_VIEW_REF = ObjectRef(
    kind=ObjectKind.VIEW,
    qname=QualifiedName(namespace="App Schema", name='Mixed"View'),
)
_DEFINITION = "SELECT 1 AS id, 'x'::text AS \"select\""


def _view(
    *,
    definition: str = _DEFINITION,
    columns: tuple[tuple[str, str], ...] = (("id", "integer"), ("select", "text")),
    check_option: Literal["none", "local", "cascaded"] = "local",
    security_barrier: bool = True,
    security_invoker: bool = True,
    owner: str | None = 'Role "Owner',
) -> View:
    return View(
        ref=_VIEW_REF,
        columns=columns,
        definition=definition,
        check_option=check_option,
        security_barrier=security_barrier,
        security_invoker=security_invoker,
        owner=owner,
    )


def _emit(
    delta: CreateView | DropView | ReplaceView | AlterViewOwner,
) -> tuple[SqlStatement, ...]:
    return SqlEmitter(default_handlers()).emit(DeltaSet.from_iterable((delta,)))


def test_create_view_emits_quoted_columns_options_check_option_and_owner() -> None:
    delta = CreateView(target=_VIEW_REF, view=_view())

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'CREATE VIEW "App Schema"."Mixed""View" ("id", "select") '
        "WITH (security_barrier = true, security_invoker = true) AS "
        f"{_DEFINITION} WITH LOCAL CHECK OPTION",
        'ALTER VIEW "App Schema"."Mixed""View" OWNER TO "Role ""Owner"',
    )
    assert all(statement.transactional and statement.delta is delta for statement in statements)


def test_create_view_strips_catalog_semicolon_before_check_option() -> None:
    # pg_get_viewdef(oid, true) returns " SELECT ...;" with a trailing semicolon.
    view = _view(definition=" SELECT 1 AS id;\n", columns=(("id", "integer"),), owner=None)

    statements = _emit(CreateView(target=_VIEW_REF, view=view))

    assert statements[0].sql.endswith("AS  SELECT 1 AS id WITH LOCAL CHECK OPTION")


def test_create_view_omits_default_options_and_owner() -> None:
    view = _view(
        definition="SELECT 1 AS id",
        columns=(("id", "integer"),),
        check_option="none",
        security_barrier=False,
        security_invoker=False,
        owner=None,
    )

    statements = _emit(CreateView(target=_VIEW_REF, view=view))

    assert tuple(statement.sql for statement in statements) == (
        'CREATE VIEW "App Schema"."Mixed""View" ("id") AS SELECT 1 AS id',
    )


def test_replace_view_emits_create_or_replace_for_compatible_shape() -> None:
    old = _view()
    new = _view(definition="SELECT 2 AS id, 'y'::text AS \"select\"")
    delta = ReplaceView(target=_VIEW_REF, old_view=old, new_view=new)

    statements = _emit(delta)

    assert statements[0].sql.startswith('CREATE OR REPLACE VIEW "App Schema"."Mixed""View"')
    assert statements[0].sql.endswith(f"AS {new.definition} WITH LOCAL CHECK OPTION")
    assert statements[0].delta is delta


def test_incompatible_view_replacement_is_rejected() -> None:
    view = _view()
    delta = ReplaceView(
        target=_VIEW_REF,
        old_view=view,
        new_view=_view(columns=(("renamed", "text"),)),
        incompatible=True,
    )

    with pytest.raises(MigrationError, match="output column"):
        _emit(delta)


def test_view_shape_change_is_rejected_even_if_delta_flag_is_inaccurate() -> None:
    old = _view()
    delta = ReplaceView(
        target=_VIEW_REF,
        old_view=old,
        new_view=_view(columns=(("renamed", "text"),)),
    )

    with pytest.raises(MigrationError, match="output column"):
        _emit(delta)


def test_drop_view_uses_restrict() -> None:
    delta = DropView(target=_VIEW_REF, view=_view(owner=None))

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'DROP VIEW "App Schema"."Mixed""View" RESTRICT',
    )


def test_alter_view_owner_quotes_role() -> None:
    delta = AlterViewOwner(target=_VIEW_REF, view=_view(owner=None), new_owner='New "Owner')

    statements = _emit(delta)

    assert tuple(statement.sql for statement in statements) == (
        'ALTER VIEW "App Schema"."Mixed""View" OWNER TO "New ""Owner"',
    )
