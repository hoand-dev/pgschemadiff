from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.sql_emit.risk import RiskLevel, classify_risk
from pgschemadiff.domain.delta import DeltaSet
from pgschemadiff.domain.delta.materialized_view import (
    AlterMaterializedViewOwner,
    CreateMaterializedView,
    DropMaterializedView,
    ReplaceMaterializedView,
)
from pgschemadiff.domain.delta.view import DropView
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.materialized_view import MaterializedView
from pgschemadiff.domain.view import View
from pgschemadiff.shared.errors import RiskGateError

if TYPE_CHECKING:
    from pgschemadiff.domain.delta import DeltaBase


def _view(
    *,
    definition: str = "SELECT id FROM public.items",
    has_indexes: bool = False,
    dependents: tuple[ObjectRef, ...] = (),
) -> MaterializedView:
    materialized_view = MaterializedView(
        ref=ObjectRef(
            kind=ObjectKind.MATERIALIZED_VIEW,
            qname=QualifiedName(namespace="public", name="items_mv"),
        ),
        columns=(("id", "integer"),),
        definition=definition,
        owner="app_owner",
        has_indexes=has_indexes,
    )
    return (
        materialized_view.model_copy(update={"dependents": dependents})
        if dependents
        else materialized_view
    )


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        pytest.param(
            CreateMaterializedView(
                target=_view().ref,
                materialized_view=_view(),
            ),
            RiskLevel.DANGEROUS,
            id="create-evaluates-query",
        ),
        pytest.param(
            CreateMaterializedView(
                target=_view(has_indexes=True).ref,
                materialized_view=_view(has_indexes=True),
            ),
            RiskLevel.BLOCKED,
            id="create-with-index",
        ),
        pytest.param(
            DropMaterializedView(target=_view().ref, materialized_view=_view()),
            RiskLevel.DESTRUCTIVE,
            id="drop",
        ),
        pytest.param(
            DropMaterializedView(
                target=_view(has_indexes=True).ref,
                materialized_view=_view(has_indexes=True),
            ),
            RiskLevel.BLOCKED,
            id="drop-with-index",
        ),
        pytest.param(
            ReplaceMaterializedView(
                target=_view().ref,
                old_materialized_view=_view(),
                new_materialized_view=_view(definition="SELECT id + 1 AS id FROM public.items"),
            ),
            RiskLevel.DANGEROUS,
            id="replace",
        ),
        pytest.param(
            ReplaceMaterializedView(
                target=_view(has_indexes=True).ref,
                old_materialized_view=_view(has_indexes=True),
                new_materialized_view=_view(definition="SELECT id + 1 AS id FROM public.items"),
            ),
            RiskLevel.BLOCKED,
            id="replace-source-indexed",
        ),
        pytest.param(
            ReplaceMaterializedView(
                target=_view().ref,
                old_materialized_view=_view(),
                new_materialized_view=_view(
                    definition="SELECT id + 1 AS id FROM public.items",
                    has_indexes=True,
                ),
            ),
            RiskLevel.BLOCKED,
            id="replace-target-indexed",
        ),
        pytest.param(
            AlterMaterializedViewOwner(
                target=_view(has_indexes=True).ref,
                materialized_view=_view(has_indexes=True),
                new_owner="new_owner",
            ),
            RiskLevel.DANGEROUS,
            id="owner-change-with-index",
        ),
    ],
)
def test_materialized_view_risk_accounts_for_query_cost_and_attached_indexes(
    delta: DeltaBase,
    expected: RiskLevel,
) -> None:
    assessment = classify_risk(delta)

    assert assessment.delta is delta
    assert assessment.level is expected
    assert assessment.reason.strip()
    if expected is RiskLevel.BLOCKED:
        assert "index" in assessment.reason.lower()


def test_materialized_view_drop_and_replace_block_unremoved_dependents() -> None:
    dependent_ref = ObjectRef(
        kind=ObjectKind.VIEW,
        qname=QualifiedName(namespace="public", name="items_view"),
    )
    old = _view(dependents=(dependent_ref,))
    drop = DropMaterializedView(target=old.ref, materialized_view=old)
    replace = ReplaceMaterializedView(
        target=old.ref,
        old_materialized_view=old,
        new_materialized_view=_view(
            definition="SELECT id + 1 AS id FROM public.items",
            dependents=(dependent_ref,),
        ),
    )

    assert classify_risk(drop).level is RiskLevel.BLOCKED
    assert classify_risk(replace).level is RiskLevel.BLOCKED


def test_materialized_view_drop_requires_dependent_view_delta_and_orders_it_first() -> None:
    materialized_view = _view()
    dependent = View(
        ref=ObjectRef(
            kind=ObjectKind.VIEW,
            qname=QualifiedName(namespace="public", name="items_view"),
        ),
        columns=(("id", "integer"),),
        definition="SELECT id FROM public.items_mv",
        prerequisites=(materialized_view.ref,),
    )
    materialized_view = materialized_view.model_copy(update={"dependents": (dependent.ref,)})
    drop_materialized_view = DropMaterializedView(
        target=materialized_view.ref,
        materialized_view=materialized_view,
    )

    with pytest.raises(RiskGateError, match="dependent"):
        generate_migration(
            DeltaSet.from_iterable((drop_materialized_view,)),
            max_risk=RiskLevel.DESTRUCTIVE,
        )

    plan = generate_migration(
        DeltaSet.from_iterable(
            (
                drop_materialized_view,
                DropView(target=dependent.ref, view=dependent),
            )
        ),
        max_risk=RiskLevel.DESTRUCTIVE,
    )

    assert tuple(delta.target for delta in plan.delta_set) == (dependent.ref, materialized_view.ref)
