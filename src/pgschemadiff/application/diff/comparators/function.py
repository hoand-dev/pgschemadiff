"""Comparator for PostgreSQL function overloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.function import (
    AlterFunctionOwner,
    CreateFunction,
    DropFunction,
    FunctionDelta,
    ReplaceFunction,
)
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pgschemadiff.domain.function import Function, FunctionArgument


def _input_arguments(function: Function) -> tuple[FunctionArgument, ...]:
    return tuple(
        argument for argument in function.arguments if argument.mode in {"IN", "INOUT", "VARIADIC"}
    )


def _has_default_conflict(function: Function, candidates: Iterable[Function]) -> bool:
    for other in candidates:
        if other.ref == function.ref or other.ref.qname != function.ref.qname:
            continue
        if _positional_calls_overlap(function, other) or _named_calls_overlap(function, other):
            return True
    return False


def _positional_calls_overlap(left: Function, right: Function) -> bool:
    left_args = _input_arguments(left)
    right_args = _input_arguments(right)
    minimum = max(
        len(left_args) - left.effective_default_count,
        len(right_args) - right.effective_default_count,
    )
    maximum = min(len(left_args), len(right_args))
    return any(
        tuple(argument.data_type for argument in left_args[:arity])
        == tuple(argument.data_type for argument in right_args[:arity])
        for arity in range(minimum, maximum + 1)
    )


def _named_calls_overlap(left: Function, right: Function) -> bool:
    left_args = _input_arguments(left)
    right_args = _input_arguments(right)
    left_required = len(left_args) - left.effective_default_count
    right_required = len(right_args) - right.effective_default_count

    required_names: set[str] = set()
    for args, required_count in ((left_args, left_required), (right_args, right_required)):
        for argument in args[:required_count]:
            if argument.name is None:
                return False
            required_names.add(argument.name)

    left_types = {argument.name: argument.data_type for argument in left_args if argument.name}
    right_types = {argument.name: argument.data_type for argument in right_args if argument.name}
    return all(
        name in left_types and name in right_types and left_types[name] == right_types[name]
        for name in required_names
    )


def _parameter_shape(function: Function) -> tuple[tuple[str | None, str, str], ...]:
    return tuple(
        (argument.name, argument.mode, argument.data_type) for argument in function.arguments
    )


def _defaults(function: Function) -> tuple[str | None, ...]:
    return (
        function.default_expressions,
        str(function.effective_default_count),
        *(argument.default_expr for argument in function.arguments),
    )


class FunctionComparator:
    """Compare function existence, semantics, and ownership by full overload identity."""

    kind: ObjectKind = ObjectKind.FUNCTION

    def __init__(self, *, target_functions: Iterable[Function] = ()) -> None:
        self._target_functions = tuple(target_functions)

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[FunctionDelta, ...]:
        src: Function | None = source  # type: ignore[assignment]
        tgt: Function | None = target  # type: ignore[assignment]

        if src is None and tgt is None:
            return ()
        if src is None:
            assert tgt is not None
            return (
                CreateFunction(
                    target=tgt.ref,
                    function=tgt,
                    default_conflict=(
                        tgt.effective_default_count > 0
                        and _has_default_conflict(tgt, self._target_functions)
                    ),
                ),
            )
        if tgt is None:
            return (DropFunction(target=src.ref, function=src),)
        if src.ref != tgt.ref:
            raise DiffError(
                f"Cannot compare distinct function identities: {src.ref!r} != {tgt.ref!r}"
            )

        result: list[FunctionDelta] = []
        source_semantics = src.model_dump(exclude={"owner"})
        target_semantics = tgt.model_dump(exclude={"owner"})
        if source_semantics != target_semantics:
            defaults_changed = _defaults(src) != _defaults(tgt)
            incompatible = (
                src.return_type != tgt.return_type
                or src.returns_set != tgt.returns_set
                or _parameter_shape(src) != _parameter_shape(tgt)
            )
            default_conflict = (
                defaults_changed
                and tgt.effective_default_count > 0
                and _has_default_conflict(tgt, self._target_functions)
            )
            result.append(
                ReplaceFunction(
                    target=src.ref,
                    old_function=src,
                    new_function=tgt,
                    incompatible=incompatible,
                    default_conflict=default_conflict,
                )
            )

        if src.owner != tgt.owner:
            if tgt.owner is None:
                raise DiffError("Function owner cannot be changed to an unresolved owner.")
            result.append(AlterFunctionOwner(target=src.ref, function=src, new_owner=tgt.owner))
        return tuple(result)


assert isinstance(FunctionComparator(), Comparator)
