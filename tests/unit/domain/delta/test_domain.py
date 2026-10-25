from __future__ import annotations

from pgschemadiff.domain.delta import (
    AddDomainCheck,
    AlterDomainAttrs,
    AlterDomainDefault,
    AlterDomainNullability,
    CreateDomain,
    DeltaSet,
    DropDomain,
    DropDomainCheck,
    ReplaceDomainType,
    ValidateDomainCheck,
)
from pgschemadiff.domain.domain_type import DomainCheck, DomainType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName


def _domain() -> DomainType:
    ref = ObjectRef(
        kind=ObjectKind.DOMAIN_TYPE,
        qname=QualifiedName(namespace="public", name="positive"),
    )
    return DomainType(
        ref=ref,
        base_type="integer",
        checks=(DomainCheck(name="positive_check", expression="VALUE > 0"),),
        owner="app_owner",
    )


def test_domain_deltas_round_trip_through_delta_set_json() -> None:
    domain = _domain()
    deltas = (
        CreateDomain(target=domain.ref, domain=domain),
        DropDomain(target=domain.ref, domain=domain),
        AlterDomainDefault(target=domain.ref, new_default_expr="0"),
        AlterDomainDefault(target=domain.ref, new_default_expr=None),
        AlterDomainNullability(target=domain.ref, new_not_null=True),
        AlterDomainNullability(target=domain.ref, new_not_null=False),
        AddDomainCheck(
            target=domain.ref,
            check=DomainCheck(name="upper_check", expression="VALUE < 100"),
        ),
        ValidateDomainCheck(target=domain.ref, check_name="upper_check"),
        DropDomainCheck(target=domain.ref, check_name="positive_check"),
        AlterDomainAttrs(target=domain.ref, new_owner="other_owner"),
        ReplaceDomainType(
            target=domain.ref,
            old_base_type="integer",
            new_base_type="text",
            old_collation=None,
            new_collation=None,
        ),
    )

    restored = DeltaSet.model_validate_json(DeltaSet(deltas=deltas).model_dump_json())

    assert restored.deltas == deltas
    assert tuple(type(delta) for delta in restored) == tuple(type(delta) for delta in deltas)
