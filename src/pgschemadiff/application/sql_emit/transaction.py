"""Split ordered SQL statements into transaction units."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pgschemadiff.application.sql_emit.emitter import SqlStatement
    from pgschemadiff.application.sql_emit.risk import RiskAssessment
    from pgschemadiff.domain.delta import DeltaBase

_RISK_LEVELS = tuple(RiskLevel)


@dataclass(frozen=True)
class TransactionUnit:
    """An ordered group of statements executed with one transaction mode."""

    statements: tuple[SqlStatement, ...]
    transactional: bool

    def __post_init__(self) -> None:
        if not isinstance(self.statements, tuple):
            raise MigrationError("Transaction unit statements must be a tuple.")
        if not self.statements:
            raise MigrationError("A transaction unit must contain at least one statement.")
        if any(statement.transactional != self.transactional for statement in self.statements):
            raise MigrationError("Every statement must match the unit's transactional value.")
        if not self.transactional and len(self.statements) != 1:
            raise MigrationError("A non-transactional unit must contain exactly one statement.")

    def max_risk_level(self, assessments: Mapping[DeltaBase, RiskAssessment]) -> RiskLevel:
        """Return the highest risk level among this unit's statement deltas."""
        levels: list[RiskLevel] = []
        for statement in self.statements:
            assessment = assessments.get(statement.delta)
            if assessment is None:
                raise MigrationError("Risk assessment is missing for a transaction unit delta.")
            if assessment.delta != statement.delta:
                raise MigrationError("Risk assessment delta does not match the statement delta.")
            levels.append(assessment.level)
        return max(levels, key=_RISK_LEVELS.index)


def split_units(statements: Sequence[SqlStatement]) -> tuple[TransactionUnit, ...]:
    """Group transactional runs; isolate marked or non-transactional statements."""
    units: list[TransactionUnit] = []
    current: list[SqlStatement] = []

    for statement in statements:
        if not statement.transactional:
            if current:
                units.append(TransactionUnit(tuple(current), transactional=True))
                current.clear()
            units.append(TransactionUnit((statement,), transactional=False))
            continue

        if statement.isolated:
            if current:
                units.append(TransactionUnit(tuple(current), transactional=True))
                current.clear()
            units.append(TransactionUnit((statement,), transactional=True))
            continue

        if current and statement.new_unit:
            units.append(TransactionUnit(tuple(current), transactional=True))
            current.clear()
        current.append(statement)

    if current:
        units.append(TransactionUnit(tuple(current), transactional=True))

    return tuple(units)
