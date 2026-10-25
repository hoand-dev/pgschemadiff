from dataclasses import FrozenInstanceError
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pgschemadiff.application.sql_emit.emitter import SqlStatement
from pgschemadiff.application.sql_emit.risk import RiskAssessment, RiskLevel
from pgschemadiff.application.sql_emit.transaction import TransactionUnit, split_units
from pgschemadiff.domain.delta import CreateSchema, DeltaBase, DropSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.shared.errors import MigrationError


def _schema_delta(name: str) -> DeltaBase:
    ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )
    if name == "created":
        return CreateSchema(target=ref, pg_schema=Schema(ref=ref))
    return DropSchema(target=ref, pg_schema=Schema(ref=ref))


_CREATE = _schema_delta("created")
_DROP = _schema_delta("removed")


def _statement(
    sql: str,
    transactional: bool,
    *,
    new_unit: bool = False,
    isolated: bool = False,
    delta: DeltaBase = _CREATE,
) -> SqlStatement:
    return SqlStatement(
        sql=sql,
        transactional=transactional,
        delta=delta,
        new_unit=new_unit,
        isolated=isolated,
    )


def test_split_groups_maximal_transactional_runs() -> None:
    statements = (
        _statement("CREATE SCHEMA", True),
        _statement("ALTER SCHEMA", True),
        _statement("CREATE INDEX CONCURRENTLY", False),
        _statement("DROP SCHEMA", True),
    )

    units = split_units(statements)

    assert tuple(unit.statements for unit in units) == (
        statements[:2],
        statements[2:3],
        statements[3:],
    )
    assert tuple(unit.transactional for unit in units) == (True, False, True)


def test_each_non_transactional_statement_is_isolated() -> None:
    statements = (
        _statement("CREATE SCHEMA", True),
        _statement("CREATE INDEX CONCURRENTLY", False),
        _statement("DROP INDEX CONCURRENTLY", False),
        _statement("ALTER SCHEMA", True),
    )

    units = split_units(statements)

    assert tuple(unit.statements for unit in units) == (
        statements[:1],
        statements[1:2],
        statements[2:3],
        statements[3:],
    )
    assert all(len(unit.statements) == 1 for unit in units[1:3])


def test_new_unit_at_start_and_consecutive_boundaries() -> None:
    statements = (
        _statement("first", True, new_unit=True),
        _statement("second", True, new_unit=True),
        _statement("third", True),
        _statement("fourth", True),
    )

    units = split_units(statements)

    assert tuple(unit.statements for unit in units) == (
        statements[:1],
        statements[1:],
    )


def test_isolated_transactional_statement_owns_its_unit_on_both_sides() -> None:
    statements = (
        _statement("before", True),
        _statement("isolated", True, isolated=True),
        _statement("after", True),
    )

    units = split_units(statements)

    assert tuple(unit.statements for unit in units) == tuple(
        (statement,) for statement in statements
    )
    assert tuple(unit.transactional for unit in units) == (True, True, True)


def test_empty_input_returns_no_units() -> None:
    assert split_units(()) == ()


def test_transaction_unit_rejects_empty_statements() -> None:
    with pytest.raises(MigrationError, match="at least one statement"):
        TransactionUnit(statements=(), transactional=True)


def test_transaction_unit_rejects_mutable_statement_container() -> None:
    with pytest.raises(MigrationError, match="must be a tuple"):
        TransactionUnit(
            statements=[_statement("CREATE SCHEMA", True)],  # type: ignore[arg-type]
            transactional=True,
        )


def test_transaction_unit_rejects_mixed_transaction_modes() -> None:
    statement = _statement("CREATE INDEX CONCURRENTLY", False)

    with pytest.raises(MigrationError, match="transactional value"):
        TransactionUnit(statements=(statement,), transactional=True)


def test_transaction_unit_rejects_multiple_non_transactional_statements() -> None:
    statements = (
        _statement("CREATE INDEX CONCURRENTLY", False),
        _statement("DROP INDEX CONCURRENTLY", False),
    )

    with pytest.raises(MigrationError, match="exactly one statement"):
        TransactionUnit(statements=statements, transactional=False)


def test_transaction_unit_is_frozen() -> None:
    unit = TransactionUnit(statements=(_statement("CREATE SCHEMA", True),), transactional=True)

    with pytest.raises(FrozenInstanceError):
        unit.transactional = False  # type: ignore[misc]


def test_max_risk_level_uses_highest_assessment_for_unit_deltas() -> None:
    unit = TransactionUnit(
        statements=(
            _statement("CREATE SCHEMA", True),
            _statement("DROP SCHEMA", True, delta=_DROP),
        ),
        transactional=True,
    )
    assessments = {
        _CREATE: RiskAssessment(_CREATE, RiskLevel.WARNING, "creates schema"),
        _DROP: RiskAssessment(_DROP, RiskLevel.DESTRUCTIVE, "drops schema"),
    }

    assert unit.max_risk_level(assessments) is RiskLevel.DESTRUCTIVE


def test_max_risk_level_rejects_missing_assessment() -> None:
    unit = TransactionUnit(statements=(_statement("CREATE SCHEMA", True),), transactional=True)

    with pytest.raises(MigrationError, match="Risk assessment is missing"):
        unit.max_risk_level({})


def test_max_risk_level_rejects_assessment_for_different_delta() -> None:
    unit = TransactionUnit(statements=(_statement("CREATE SCHEMA", True),), transactional=True)
    assessments = {
        _CREATE: RiskAssessment(_DROP, RiskLevel.SAFE, "wrong delta"),
    }

    with pytest.raises(MigrationError, match="does not match"):
        unit.max_risk_level(assessments)


@given(st.lists(st.tuples(st.booleans(), st.booleans()), max_size=40))
def test_split_preserves_order_and_unit_invariants(
    modes_and_boundaries: list[tuple[bool, bool]],
) -> None:
    statements = tuple(
        _statement(f"statement-{index}", transactional, new_unit=new_unit)
        for index, (transactional, new_unit) in enumerate(modes_and_boundaries)
    )

    units = split_units(statements)

    flattened = tuple(statement for unit in units for statement in unit.statements)
    assert flattened == statements
    assert all(actual is expected for actual, expected in zip(flattened, statements, strict=True))
    assert all(unit.statements for unit in units)
    assert all(
        statement.transactional is unit.transactional
        for unit in units
        for statement in unit.statements
    )
    assert all(unit.transactional or len(unit.statements) == 1 for unit in units)
    assert all(
        current.statements[0].new_unit
        for previous, current in pairwise(units)
        if previous.transactional and current.transactional
    )
