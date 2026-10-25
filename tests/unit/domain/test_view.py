from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.view import View


def _ref(kind: ObjectKind, name: str, namespace: str = "public") -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace=namespace, name=name))


def _view(**updates: object) -> View:
    values: dict[str, object] = {
        "ref": _ref(ObjectKind.VIEW, "items_view"),
        "columns": (("id", "integer"), ("label", "text")),
        "definition": "SELECT items.id, items.label FROM public.items",
        "check_option": "none",
        "security_barrier": False,
        "security_invoker": False,
        "owner": "app_owner",
        "prerequisites": (_ref(ObjectKind.TABLE, "items"),),
    }
    values.update(updates)
    return View(**values)  # type: ignore[arg-type]


def test_view_is_frozen_and_preserves_ordered_output_and_prerequisites() -> None:
    view = _view()

    assert view.columns == (("id", "integer"), ("label", "text"))
    assert view.prerequisites == (_ref(ObjectKind.TABLE, "items"),)
    with pytest.raises(ValidationError):
        view.owner = "other"  # type: ignore[misc]


def test_view_requires_view_identity() -> None:
    with pytest.raises(ValidationError, match="must have kind VIEW"):
        _view(ref=_ref(ObjectKind.TABLE, "items_view"))


@pytest.mark.parametrize(
    "columns",
    [(("id", "integer"), ("id", "text")), (("id", " "),)],
)
def test_view_rejects_duplicate_or_unusable_output_columns(
    columns: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ValidationError):
        _view(columns=columns)


def test_view_rejects_duplicate_and_self_prerequisites() -> None:
    view_ref = _ref(ObjectKind.VIEW, "items_view")
    with pytest.raises(ValidationError, match="Duplicate prerequisite"):
        _view(prerequisites=(_ref(ObjectKind.TABLE, "items"),) * 2)
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        _view(prerequisites=(view_ref,))


def test_view_rejects_unknown_check_option() -> None:
    with pytest.raises(ValidationError):
        _view(check_option="other")
