from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.materialized_view import MaterializedViewComparator
from pgschemadiff.domain.delta import (
    AlterMaterializedViewOwner,
    CreateMaterializedView,
    DropMaterializedView,
    ReplaceMaterializedView,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.materialized_view import MaterializedView
from pgschemadiff.shared.errors import DiffError


def _view(
    *,
    name: str = "items_mv",
    definition: str = "SELECT id FROM public.items",
    columns: tuple[tuple[str, str], ...] = (("id", "integer"),),
    access_method: str | None = None,
    tablespace: str | None = None,
    storage_parameters: tuple[str, ...] = (),
    owner: str | None = "app_owner",
    has_indexes: bool = False,
) -> MaterializedView:
    return MaterializedView(
        ref=ObjectRef(
            kind=ObjectKind.MATERIALIZED_VIEW,
            qname=QualifiedName(namespace="public", name=name),
        ),
        columns=columns,
        definition=definition,
        access_method=access_method,
        tablespace=tablespace,
        storage_parameters=storage_parameters,
        owner=owner,
        has_indexes=has_indexes,
    )


def test_materialized_view_comparator_creates_and_drops() -> None:
    view = _view()

    assert MaterializedViewComparator().compare(None, view) == (
        CreateMaterializedView(target=view.ref, materialized_view=view),
    )
    assert MaterializedViewComparator().compare(view, None) == (
        DropMaterializedView(target=view.ref, materialized_view=view),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("definition", "SELECT id + 1 AS id FROM public.items"),
        ("columns", (("identifier", "integer"),)),
        ("access_method", "heap"),
        ("tablespace", "fast_space"),
        ("storage_parameters", ("fillfactor=70",)),
    ],
)
def test_materialized_view_comparator_replaces_definition_columns_and_physical_options(
    field: str,
    value: object,
) -> None:
    old = _view()
    new = old.model_copy(update={field: value})

    (delta,) = MaterializedViewComparator().compare(old, new)

    assert isinstance(delta, ReplaceMaterializedView)
    assert delta.old_materialized_view is old
    assert delta.new_materialized_view is new


def test_materialized_view_comparator_ignores_population_and_index_observation() -> None:
    old = _view(has_indexes=False)
    new = _view(has_indexes=True)

    assert MaterializedViewComparator().compare(old, new) == ()


def test_materialized_view_comparator_ignores_incoming_dependency_observation() -> None:
    old = _view()
    dependent = ObjectRef(
        kind=ObjectKind.VIEW,
        qname=QualifiedName(namespace="public", name="items_view"),
    )
    new = old.model_copy(update={"dependents": (dependent,)})

    assert MaterializedViewComparator().compare(old, new) == ()


def test_materialized_view_comparator_emits_owner_change_separately() -> None:
    old = _view()
    new = _view(owner="new_owner")

    (delta,) = MaterializedViewComparator().compare(old, new)

    assert isinstance(delta, AlterMaterializedViewOwner)
    assert delta.new_owner == "new_owner"


def test_materialized_view_comparator_emits_replace_and_owner_changes_together() -> None:
    old = _view()
    new = _view(definition="SELECT id + 1 AS id FROM public.items", owner="new_owner")

    deltas = MaterializedViewComparator().compare(old, new)

    assert tuple(type(delta) for delta in deltas) == (
        ReplaceMaterializedView,
        AlterMaterializedViewOwner,
    )


def test_materialized_view_comparator_rejects_unresolved_owner_and_distinct_identity() -> None:
    with pytest.raises(DiffError, match="unresolved owner"):
        MaterializedViewComparator().compare(_view(), _view(owner=None))
    with pytest.raises(DiffError, match="distinct materialized-view identities"):
        MaterializedViewComparator().compare(_view(), _view(name="other_mv"))
