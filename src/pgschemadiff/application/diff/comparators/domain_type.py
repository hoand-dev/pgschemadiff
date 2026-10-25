"""Comparator for PostgreSQL domain types."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.domain_type import (
    AddDomainCheck,
    AlterDomainAttrs,
    AlterDomainDefault,
    AlterDomainNullability,
    CreateDomain,
    DomainTypeDelta,
    DropDomain,
    DropDomainCheck,
    ReplaceDomainType,
    ValidateDomainCheck,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.domain_type import DomainType


def _compare_checks(
    source: DomainType,
    target: DomainType,
    *,
    used_in_container: bool,
) -> tuple[DomainTypeDelta, ...]:
    source_checks = {check.name: check for check in source.checks}
    target_checks = {check.name: check for check in target.checks}
    result: list[DomainTypeDelta] = []
    for old_check in source.checks:
        new_check = target_checks.get(old_check.name)
        if new_check is None:
            result.append(DropDomainCheck(target=source.ref, check_name=old_check.name))
        elif old_check.expression != new_check.expression:
            result.append(DropDomainCheck(target=source.ref, check_name=old_check.name))
            result.append(
                AddDomainCheck(
                    target=source.ref,
                    check=new_check,
                    used_in_container=used_in_container,
                )
            )
        elif old_check.validated != new_check.validated:
            if not new_check.validated:
                raise DiffError("An existing domain check cannot be made NOT VALID.")
            result.append(
                ValidateDomainCheck(
                    target=source.ref,
                    check_name=old_check.name,
                    used_in_container=used_in_container,
                )
            )

    result.extend(
        AddDomainCheck(
            target=source.ref,
            check=check,
            used_in_container=used_in_container,
        )
        for check in target.checks
        if check.name not in source_checks
    )
    return tuple(result)


class DomainTypeComparator:
    """Compare domain existence, base semantics, defaults, checks, and owner."""

    kind: ObjectKind = ObjectKind.DOMAIN_TYPE

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[DomainTypeDelta, ...]:
        """Emit lifecycle, supported alterations, or blocked base replacement."""
        src = cast("DomainType | None", source)
        tgt = cast("DomainType | None", target)

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreateDomain(target=tgt.ref, domain=tgt),)
        if tgt is None:
            return (DropDomain(target=src.ref, domain=src),)

        if src.base_type != tgt.base_type or src.collation != tgt.collation:
            return (
                ReplaceDomainType(
                    target=src.ref,
                    old_base_type=src.base_type,
                    new_base_type=tgt.base_type,
                    old_collation=src.collation,
                    new_collation=tgt.collation,
                ),
            )

        used_in_container = src.used_in_container or tgt.used_in_container
        result: list[DomainTypeDelta] = []
        if src.default_expr != tgt.default_expr:
            result.append(AlterDomainDefault(target=src.ref, new_default_expr=tgt.default_expr))
        if src.not_null != tgt.not_null:
            result.append(
                AlterDomainNullability(
                    target=src.ref,
                    new_not_null=tgt.not_null,
                    used_in_container=used_in_container,
                )
            )

        result.extend(
            _compare_checks(
                src,
                tgt,
                used_in_container=used_in_container,
            )
        )

        if src.owner != tgt.owner:
            if tgt.owner is None:
                raise DiffError("Domain owner cannot be changed to an unresolved owner.")
            result.append(AlterDomainAttrs(target=src.ref, new_owner=tgt.owner))
        return tuple(result)


assert isinstance(DomainTypeComparator(), Comparator)
