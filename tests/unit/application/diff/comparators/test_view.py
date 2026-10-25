from __future__ import annotations

from typing import Literal

import pytest

from pgschemadiff.application.diff.comparators.view import ViewComparator
from pgschemadiff.domain.delta import AlterViewOwner, CreateView, DropView, ReplaceView
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.view import View
from pgschemadiff.shared.errors import DiffError


def _ref(name: str = "items_view") -> ObjectRef:
    return ObjectRef(kind=ObjectKind.VIEW, qname=QualifiedName(namespace="public", name=name))


def _view(
    *,
    name: str = "items_view",
    columns: tuple[tuple[str, str], ...] = (("id", "integer"), ("label", "text")),
    definition: str = "SELECT items.id, items.label FROM public.items",
    check_option: Literal["none", "local", "cascaded"] = "none",
    security_barrier: bool = False,
    security_invoker: bool = False,
    owner: str | None = "app_owner",
) -> View:
    return View(
        ref=_ref(name),
        columns=columns,
        definition=definition,
        check_option=check_option,
        security_barrier=security_barrier,
        security_invoker=security_invoker,
        owner=owner,
    )


def test_view_comparator_creates_and_drops_views() -> None:
    view = _view()

    assert ViewComparator().compare(None, view) == (CreateView(target=view.ref, view=view),)
    assert ViewComparator().compare(view, None) == (DropView(target=view.ref, view=view),)


def test_view_comparator_replaces_when_target_only_appends_columns() -> None:
    old = _view(columns=(("id", "integer"),))
    new = _view(
        columns=(("id", "integer"), ("label", "text")),
        definition="SELECT id, label FROM public.items",
    )

    (delta,) = ViewComparator().compare(old, new)

    assert isinstance(delta, ReplaceView)
    assert not delta.incompatible


@pytest.mark.parametrize(
    ("old_columns", "new_columns"),
    [
        ((("id", "integer"), ("label", "text")), (("identifier", "integer"), ("label", "text"))),
        ((("id", "integer"), ("label", "text")), (("label", "text"), ("id", "integer"))),
        ((("id", "integer"),), (("id", "text"),)),
        ((("id", "integer"), ("label", "text")), (("id", "integer"),)),
    ],
)
def test_view_comparator_marks_rename_reorder_type_change_or_removal_incompatible(
    old_columns: tuple[tuple[str, str], ...],
    new_columns: tuple[tuple[str, str], ...],
) -> None:
    old = _view(columns=old_columns)
    new = _view(columns=new_columns, definition="SELECT changed FROM public.items")

    (delta,) = ViewComparator().compare(old, new)

    assert isinstance(delta, ReplaceView)
    assert delta.incompatible


@pytest.mark.parametrize(
    ("check_option", "security_barrier", "security_invoker"),
    [
        ("local", False, False),
        ("none", True, False),
        ("none", False, True),
    ],
)
def test_view_comparator_replaces_definition_or_options(
    check_option: Literal["none", "local", "cascaded"],
    security_barrier: bool,
    security_invoker: bool,
) -> None:
    old = _view()
    new = _view(
        check_option=check_option,
        security_barrier=security_barrier,
        security_invoker=security_invoker,
    )

    (delta,) = ViewComparator().compare(old, new)

    assert isinstance(delta, ReplaceView)
    assert not delta.incompatible


def test_view_comparator_emits_owner_change_separately() -> None:
    old = _view()
    new = _view(owner="new_owner")

    (delta,) = ViewComparator().compare(old, new)

    assert isinstance(delta, AlterViewOwner)
    assert delta.new_owner == "new_owner"


def test_view_comparator_rejects_unresolved_owner_and_distinct_identity() -> None:
    with pytest.raises(DiffError, match="unresolved owner"):
        ViewComparator().compare(_view(), _view(owner=None))
    with pytest.raises(DiffError, match="distinct view identities"):
        ViewComparator().compare(_view(), _view(name="other_view"))
