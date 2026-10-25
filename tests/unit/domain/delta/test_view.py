from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.delta import (
    AlterViewOwner,
    CreateView,
    Delta,
    DropView,
    ReplaceView,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.view import View


def _view(
    *, name: str = "items_view", columns: tuple[tuple[str, str], ...] = (("id", "integer"),)
) -> View:
    return View(
        ref=ObjectRef(kind=ObjectKind.VIEW, qname=QualifiedName(namespace="public", name=name)),
        columns=columns,
        definition="SELECT items.id FROM public.items",
        check_option="none",
        security_barrier=False,
        security_invoker=False,
        owner="app_owner",
    )


def test_view_deltas_validate_payload_identity() -> None:
    view = _view()
    other = _view(name="other_view")

    assert CreateView(target=view.ref, view=view).view is view
    assert DropView(target=view.ref, view=view).view is view
    assert (
        AlterViewOwner(target=view.ref, view=view, new_owner="new_owner").new_owner == "new_owner"
    )
    with pytest.raises(ValidationError, match=r"must equal view\.ref"):
        CreateView(target=other.ref, view=view)
    with pytest.raises(ValidationError, match="must not be empty"):
        AlterViewOwner(target=view.ref, view=view, new_owner="")


def test_replace_view_requires_same_identity_and_changed_payload() -> None:
    original = _view()
    appended = _view(columns=(("id", "integer"), ("label", "text")))
    delta = ReplaceView(target=original.ref, old_view=original, new_view=appended)

    assert delta.target == original.ref
    assert not delta.incompatible
    with pytest.raises(ValidationError, match="identical view identities"):
        ReplaceView(target=original.ref, old_view=original, new_view=_view(name="other_view"))
    with pytest.raises(ValidationError, match="unchanged view"):
        ReplaceView(target=original.ref, old_view=original, new_view=original)


def test_view_delta_json_round_trip_preserves_concrete_type_and_prerequisites() -> None:
    view = _view()
    delta: Delta = CreateView(target=view.ref, view=view)

    adapter = TypeAdapter[Delta](Delta)
    restored: Delta = adapter.validate_json(adapter.dump_json(delta))

    assert restored == delta
    assert isinstance(restored, CreateView)
