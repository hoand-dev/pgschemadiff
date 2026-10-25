from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.database import Database
from pgschemadiff.domain.domain_type import DomainCheck, DomainType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema


def _domain_ref(name: str = "positive", namespace: str = "public") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.DOMAIN_TYPE,
        qname=QualifiedName(namespace=namespace, name=name),
    )


@pytest.mark.unit
def test_domain_type_preserves_base_metadata_checks_prerequisites_and_container_flag() -> None:
    enum_ref = ObjectRef(
        kind=ObjectKind.ENUM,
        qname=QualifiedName(namespace="types", name="state"),
    )
    checks = (
        DomainCheck(name="a_check", expression="VALUE <> ''", validated=True),
        DomainCheck(name="z_check", expression="VALUE <> 'bad'", validated=False),
    )
    domain = DomainType(
        ref=_domain_ref(),
        base_type="text",
        collation='"C"',
        default_expr="'ok'::text",
        not_null=True,
        checks=checks,
        type_prerequisites=(enum_ref,),
        used_in_container=True,
        owner="app_owner",
    )

    assert domain.base_type == "text"
    assert domain.collation == '"C"'
    assert domain.default_expr == "'ok'::text"
    assert domain.not_null is True
    assert domain.checks == checks
    assert domain.type_prerequisites == (enum_ref,)
    assert domain.used_in_container is True
    assert domain.owner == "app_owner"


@pytest.mark.unit
def test_domain_type_rejects_wrong_ref_kind_duplicate_checks_and_unsorted_checks() -> None:
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )
    with pytest.raises(ValidationError, match="must have kind DOMAIN_TYPE"):
        DomainType(ref=table_ref, base_type="integer")

    duplicate = DomainCheck(name="same", expression="VALUE > 0")
    with pytest.raises(ValidationError, match="Check names must be unique"):
        DomainType(ref=_domain_ref(), base_type="integer", checks=(duplicate, duplicate))

    with pytest.raises(ValidationError, match="checks must be ordered by name"):
        DomainType(
            ref=_domain_ref(),
            base_type="integer",
            checks=(
                DomainCheck(name="z_check", expression="VALUE > 0"),
                DomainCheck(name="a_check", expression="VALUE < 10"),
            ),
        )


@pytest.mark.unit
def test_domain_type_is_frozen_and_json_round_trips() -> None:
    domain = DomainType(
        ref=_domain_ref(),
        base_type="integer",
        checks=(DomainCheck(name="positive_check", expression="VALUE > 0"),),
    )

    with pytest.raises(ValidationError):
        domain.owner = "other"  # type: ignore[misc]
    assert DomainType.model_validate_json(domain.model_dump_json()) == domain


@pytest.mark.unit
def test_schema_and_database_expose_domain_types() -> None:
    domain = DomainType(ref=_domain_ref(), base_type="integer")
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    database = Database(
        name="source",
        schemas=(Schema(ref=schema_ref, domain_types=(domain,)),),
    )

    assert database.schemas[0].domain_types == (domain,)
    assert database.all_domain_types() == (domain,)
