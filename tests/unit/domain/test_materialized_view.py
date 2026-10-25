from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.materialized_view import MaterializedView


def _ref(kind: ObjectKind, name: str) -> ObjectRef:
    return ObjectRef(kind=kind, qname=QualifiedName(namespace="public", name=name))


def _materialized_view(**updates: object) -> MaterializedView:
    values: dict[str, object] = {
        "ref": _ref(ObjectKind.MATERIALIZED_VIEW, "items_mv"),
        "columns": (("id", "integer"), ("label", "text")),
        "definition": "SELECT id, label FROM public.items",
        "access_method": "heap",
        "tablespace": "fast_space",
        "storage_parameters": ("fillfactor=70",),
        "owner": "app_owner",
        "prerequisites": (_ref(ObjectKind.TABLE, "items"),),
        "has_indexes": False,
    }
    values.update(updates)
    return MaterializedView(**values)  # type: ignore[arg-type]


def test_materialized_view_is_frozen_and_retains_physical_state_and_prerequisites() -> None:
    view = _materialized_view()

    assert view.columns == (("id", "integer"), ("label", "text"))
    assert view.access_method == "heap"
    assert view.tablespace == "fast_space"
    assert view.storage_parameters == ("fillfactor=70",)
    assert view.prerequisites == (_ref(ObjectKind.TABLE, "items"),)
    assert view.has_indexes is False
    with pytest.raises(ValidationError):
        view.owner = "other"  # type: ignore[misc]


def test_materialized_view_requires_materialized_view_identity() -> None:
    with pytest.raises(ValidationError, match="must have kind MATERIALIZED_VIEW"):
        _materialized_view(ref=_ref(ObjectKind.VIEW, "items_mv"))


@pytest.mark.parametrize(
    "columns",
    [(("id", "integer"), ("id", "text")), (("id", " "),)],
)
def test_materialized_view_rejects_duplicate_or_unusable_output_columns(
    columns: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ValidationError):
        _materialized_view(columns=columns)


def test_materialized_view_rejects_blank_definition_invalid_owner_and_bad_prerequisites() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        _materialized_view(definition="  ")
    with pytest.raises(ValidationError, match="owner must not be empty"):
        _materialized_view(owner="")
    with pytest.raises(ValidationError, match="Duplicate prerequisite"):
        _materialized_view(prerequisites=(_ref(ObjectKind.TABLE, "items"),) * 2)
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        _materialized_view(prerequisites=(_ref(ObjectKind.MATERIALIZED_VIEW, "items_mv"),))


def test_materialized_view_does_not_model_population_state() -> None:
    with pytest.raises(ValidationError, match="is_populated"):
        _materialized_view(is_populated=False)
