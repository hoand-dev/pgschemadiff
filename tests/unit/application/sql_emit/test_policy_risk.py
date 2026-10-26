from __future__ import annotations

import pytest

from pgschemadiff.application.sql_emit.risk import RiskLevel, classify_risk
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.delta import (
    AlterPolicy,
    AlterTableAttrs,
    CreatePolicy,
    CreateTable,
    DropPolicy,
    ReplacePolicy,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.policy import Policy
from pgschemadiff.domain.table import Table


def _policy(**updates: object) -> Policy:
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )
    values: dict[str, object] = {
        "ref": ObjectRef(
            kind=ObjectKind.POLICY,
            qname=QualifiedName(namespace="public", name="items_policy"),
            parent=table_ref,
        ),
        "table_ref": table_ref,
        "command": "SELECT",
        "permissive": True,
        "roles": ("public",),
        "using_expr": "id > 0",
    }
    values.update(updates)
    return Policy(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("delta", "level"),
    [
        pytest.param(CreatePolicy(target=_policy().ref, policy=_policy()), RiskLevel.DANGEROUS),
        pytest.param(
            AlterPolicy(target=_policy().ref, policy=_policy(), new_roles=("reader",)),
            RiskLevel.DANGEROUS,
        ),
        pytest.param(
            ReplacePolicy(
                target=_policy().ref,
                old_policy=_policy(),
                new_policy=_policy(permissive=False),
            ),
            RiskLevel.DANGEROUS,
        ),
        pytest.param(DropPolicy(target=_policy().ref, policy=_policy()), RiskLevel.DESTRUCTIVE),
        pytest.param(
            AlterTableAttrs(target=_policy().table_ref, new_row_security=True),
            RiskLevel.DANGEROUS,
        ),
        pytest.param(
            AlterTableAttrs(target=_policy().table_ref, new_force_row_security=False),
            RiskLevel.DANGEROUS,
        ),
        pytest.param(
            CreateTable(
                target=_policy().table_ref,
                table=Table(
                    ref=_policy().table_ref,
                    columns=(Column(name="id", position=1, data_type="integer"),),
                    row_security=True,
                    force_row_security=True,
                ),
            ),
            RiskLevel.DANGEROUS,
        ),
    ],
)
def test_policy_and_row_security_changes_have_required_risk(
    delta: object, level: RiskLevel
) -> None:
    assert classify_risk(delta).level is level  # type: ignore[arg-type]
