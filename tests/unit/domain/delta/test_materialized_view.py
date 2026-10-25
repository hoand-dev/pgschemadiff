from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgschemadiff.domain.delta import (
    AlterMaterializedViewOwner,
    CreateMaterializedView,
    Delta,
    DropMaterializedView,
    ReplaceMaterializedView,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.materialized_view import MaterializedView


def _materialized_view(
    *, name: str = "items_mv", definition: str = "SELECT id FROM items"
) -> MaterializedView:
    return MaterializedView(
        ref=ObjectRef(
            kind=ObjectKind.MATERIALIZED_VIEW,
            qname=QualifiedName(namespace="public", name=name),
        ),
        columns=(("id", "integer"),),
        definition=definition,
    )


def test_materialized_view_create_drop_and_owner_deltas_validate_identity() -> None:
    view = _materialized_view()
    other = _materialized_view(name="other_mv")

    assert CreateMaterializedView(target=view.ref, materialized_view=view).materialized_view is view
    assert DropMaterializedView(target=view.ref, materialized_view=view).materialized_view is view
    assert (
        AlterMaterializedViewOwner(
            target=view.ref,
            materialized_view=view,
            new_owner="new_owner",
        ).new_owner
        == "new_owner"
    )
    with pytest.raises(ValidationError, match=r"must equal materialized_view\.ref"):
        CreateMaterializedView(target=other.ref, materialized_view=view)
    with pytest.raises(ValidationError, match="must not be empty"):
        AlterMaterializedViewOwner(target=view.ref, materialized_view=view, new_owner="")


def test_replace_materialized_view_requires_same_identity_and_changed_payload() -> None:
    original = _materialized_view()
    changed = _materialized_view(definition="SELECT id + 1 FROM items")

    delta = ReplaceMaterializedView(
        target=original.ref,
        old_materialized_view=original,
        new_materialized_view=changed,
    )

    assert delta.old_materialized_view is original
    assert delta.new_materialized_view is changed
    with pytest.raises(ValidationError, match="identical materialized-view identities"):
        ReplaceMaterializedView(
            target=original.ref,
            old_materialized_view=original,
            new_materialized_view=_materialized_view(name="other_mv"),
        )
    with pytest.raises(ValidationError, match="unchanged materialized view"):
        ReplaceMaterializedView(
            target=original.ref,
            old_materialized_view=original,
            new_materialized_view=original,
        )


def test_materialized_view_delta_json_round_trip_keeps_concrete_type() -> None:
    view = _materialized_view()
    delta: Delta = CreateMaterializedView(target=view.ref, materialized_view=view)

    restored = TypeAdapter[Delta](Delta).validate_json(TypeAdapter[Delta](Delta).dump_json(delta))

    assert restored == delta
    assert isinstance(restored, CreateMaterializedView)
