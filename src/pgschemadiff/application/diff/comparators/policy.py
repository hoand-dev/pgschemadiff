"""Comparator for table-owned row-level security policies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.policy import (
    AlterPolicy,
    CreatePolicy,
    DropPolicy,
    PolicyDelta,
    ReplacePolicy,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.policy import Policy


class PolicyComparator:
    """Compare structured policy clauses and opaque deparsed expressions."""

    kind: ObjectKind = ObjectKind.POLICY

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[PolicyDelta, ...]:
        src: Policy | None = source  # type: ignore[assignment]
        tgt: Policy | None = target  # type: ignore[assignment]

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (CreatePolicy(target=tgt.ref, policy=tgt),)
        if tgt is None:
            return (DropPolicy(target=src.ref, policy=src),)
        if src.ref != tgt.ref:
            raise DiffError(
                f"Cannot compare distinct policy identities: {src.ref!r} != {tgt.ref!r}"
            )

        if (
            src.command != tgt.command
            or src.permissive != tgt.permissive
            or (src.using_expr is not None and tgt.using_expr is None)
            or (src.with_check_expr is not None and tgt.with_check_expr is None)
        ):
            return (ReplacePolicy(target=src.ref, old_policy=src, new_policy=tgt),)

        new_roles = tgt.roles if src.roles != tgt.roles else None
        new_using_expr = tgt.using_expr if src.using_expr != tgt.using_expr else None
        new_with_check_expr = (
            tgt.with_check_expr if src.with_check_expr != tgt.with_check_expr else None
        )
        if new_roles is not None or new_using_expr is not None or new_with_check_expr is not None:
            return (
                AlterPolicy(
                    target=src.ref,
                    policy=src,
                    new_roles=new_roles,
                    new_using_expr=new_using_expr,
                    new_with_check_expr=new_with_check_expr,
                ),
            )
        return ()


assert isinstance(PolicyComparator(), Comparator)
