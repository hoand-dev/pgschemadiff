from __future__ import annotations

import pytest

from pgschemadiff.application.diff.comparators.domain_type import DomainTypeComparator
from pgschemadiff.application.diff.engine import DiffEngine
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import (
    AddDomainCheck,
    AlterDomainAttrs,
    AlterDomainDefault,
    AlterDomainNullability,
    CreateDomain,
    DropDomain,
    DropDomainCheck,
    ReplaceDomainType,
    ValidateDomainCheck,
)
from pgschemadiff.domain.domain_type import DomainCheck, DomainType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.shared.errors import DiffError


def _domain(
    *,
    base_type: str = "integer",
    collation: str | None = None,
    default_expr: str | None = None,
    not_null: bool = False,
    checks: tuple[DomainCheck, ...] = (),
    owner: str | None = "app_owner",
    used_in_container: bool = False,
    name: str = "positive",
) -> DomainType:
    ref = ObjectRef(
        kind=ObjectKind.DOMAIN_TYPE,
        qname=QualifiedName(namespace="public", name=name),
    )
    return DomainType(
        ref=ref,
        base_type=base_type,
        collation=collation,
        default_expr=default_expr,
        not_null=not_null,
        checks=checks,
        owner=owner,
        used_in_container=used_in_container,
    )


def test_domain_create_drop_and_noop() -> None:
    domain = _domain()
    comparator = DomainTypeComparator()

    assert comparator.compare(None, domain) == (CreateDomain(target=domain.ref, domain=domain),)
    assert comparator.compare(domain, None) == (DropDomain(target=domain.ref, domain=domain),)
    assert comparator.compare(domain, domain) == ()


@pytest.mark.parametrize(
    ("source_default", "target_default", "expected"),
    [(None, "0", "0"), ("0", None, None)],
    ids=("set", "drop"),
)
def test_domain_default_change(
    source_default: str | None, target_default: str | None, expected: str | None
) -> None:
    source = _domain(default_expr=source_default)
    target = _domain(default_expr=target_default)

    assert DomainTypeComparator().compare(source, target) == (
        AlterDomainDefault(target=source.ref, new_default_expr=expected),
    )


@pytest.mark.parametrize(
    ("source_not_null", "target_not_null"),
    [(False, True), (True, False)],
    ids=("set", "drop"),
)
def test_domain_nullability_change(source_not_null: bool, target_not_null: bool) -> None:
    source = _domain(not_null=source_not_null)
    target = _domain(not_null=target_not_null)

    assert DomainTypeComparator().compare(source, target) == (
        AlterDomainNullability(target=source.ref, new_not_null=target_not_null),
    )


def test_domain_check_add_remove_and_expression_change() -> None:
    old_check = DomainCheck(name="positive_check", expression="VALUE > 0")
    new_check = DomainCheck(name="positive_check", expression="VALUE >= 0")
    added = DomainCheck(name="upper_check", expression="VALUE < 100")

    assert DomainTypeComparator().compare(_domain(), _domain(checks=(added,))) == (
        AddDomainCheck(target=_domain().ref, check=added),
    )
    assert DomainTypeComparator().compare(_domain(checks=(old_check,)), _domain()) == (
        DropDomainCheck(target=_domain().ref, check_name="positive_check"),
    )
    assert DomainTypeComparator().compare(
        _domain(checks=(old_check,)), _domain(checks=(new_check,))
    ) == (
        DropDomainCheck(target=_domain().ref, check_name="positive_check"),
        AddDomainCheck(target=_domain().ref, check=new_check),
    )


def test_domain_existing_check_validation_state_changes() -> None:
    check = DomainCheck(name="positive_check", expression="VALUE > 0", validated=False)
    source = _domain(checks=(check,))
    target = _domain(checks=(check.model_copy(update={"validated": True}),))

    assert DomainTypeComparator().compare(source, target) == (
        ValidateDomainCheck(target=source.ref, check_name="positive_check"),
    )
    with pytest.raises(DiffError, match="cannot be made NOT VALID"):
        DomainTypeComparator().compare(target, source)


def test_domain_check_and_not_null_deltas_carry_container_use_from_either_snapshot() -> None:
    check = DomainCheck(name="positive_check", expression="VALUE > 0")
    source = _domain(used_in_container=True)
    target = _domain(checks=(check,))
    deltas = DomainTypeComparator().compare(source, target)

    assert deltas == (AddDomainCheck(target=source.ref, check=check, used_in_container=True),)
    assert DomainTypeComparator().compare(
        source,
        _domain(not_null=True),
    ) == (AlterDomainNullability(target=source.ref, new_not_null=True, used_in_container=True),)


@pytest.mark.parametrize(
    ("target_base_type", "target_collation"),
    [("text", None), ("text", '"C"')],
    ids=("base-type", "collation"),
)
def test_domain_base_type_or_collation_change_is_blocked_replacement(
    target_base_type: str, target_collation: str | None
) -> None:
    source = _domain()
    target = _domain(base_type=target_base_type, collation=target_collation)

    assert DomainTypeComparator().compare(source, target) == (
        ReplaceDomainType(
            target=source.ref,
            old_base_type=source.base_type,
            new_base_type=target.base_type,
            old_collation=source.collation,
            new_collation=target.collation,
        ),
    )


def test_domain_owner_change_requires_resolved_owner() -> None:
    source = _domain()
    assert DomainTypeComparator().compare(source, _domain(owner="other_owner")) == (
        AlterDomainAttrs(target=source.ref, new_owner="other_owner"),
    )
    with pytest.raises(DiffError, match="owner"):
        DomainTypeComparator().compare(source, _domain(owner=None))


def test_domain_type_comparator_is_registered_with_engine() -> None:
    source_domain = _domain()
    target_domain = _domain(default_expr="0")
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    source = Database(
        name="source", schemas=(Schema(ref=schema_ref, domain_types=(source_domain,)),)
    )
    target = Database(
        name="target", schemas=(Schema(ref=schema_ref, domain_types=(target_domain,)),)
    )

    result = DiffEngine((DomainTypeComparator(),)).diff(source, target)

    assert result.deltas == (AlterDomainDefault(target=source_domain.ref, new_default_expr="0"),)
