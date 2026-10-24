# P3-TX-01 — Transaction unit splitter design

**Status:** Approved; implementation complete.
**Date:** 2026-10-24

## Goal

Split emitted SQL into ordered transaction units without parsing SQL or changing
statement order. Units preserve the transaction and explicit boundary metadata
needed by the migration manifest and applier.

## Decisions

- Keep the splitter in `application/sql_emit/transaction.py`; it is pure
  application code and does not inspect SQL or perform IO (ADR-0005).
- Add frozen `TransactionUnit(statements, transactional)`. Reject empty units,
  mixed transaction modes, and multi-statement non-transactional units with
  `MigrationError`.
- `split_units()` groups maximal consecutive transactional statements. Each
  non-transactional statement forms its own unit. `new_unit=True` starts a unit
  before that statement, including at position zero; it never creates an empty
  unit. Input order and statement identity are preserved.
- Add `TransactionUnit.max_risk_level(assessments)`: ADR-0008 requires each
  manifest unit to report `max_risk`. It reads risk assessments by their delta,
  returns the highest ADR-0009 level, and raises `MigrationError` if an
  assessment is absent or belongs to a different delta. No separate delta list
  is needed because statements retain delta provenance.
- The `VALIDATE CONSTRAINT` statement starts a new unit through the existing
  `SqlStatement.new_unit` marker; the splitter does not parse SQL (P3-SQL review
  decision, 2026-10-23).
- Lock-timeout and statement-timeout settings are applier concerns and remain
  out of scope for P3-APPLY-01.

## API contract

```python
@dataclass(frozen=True)
class TransactionUnit:
    statements: tuple[SqlStatement, ...]
    transactional: bool

    def max_risk_level(
        self,
        assessments: Mapping[DeltaBase, RiskAssessment],
    ) -> RiskLevel: ...


def split_units(
    statements: Sequence[SqlStatement],
) -> tuple[TransactionUnit, ...]: ...
```

Empty input returns an empty tuple. Non-transactional units contain exactly one
statement, consistent with PostgreSQL's restrictions on commands such as
`CREATE/DROP INDEX CONCURRENTLY`.

## Tests and acceptance

Cover transactional grouping, non-transactional isolation, `new_unit` at the
start and at consecutive boundaries, empty input, validation errors, risk
aggregation, and order/invariants for Hypothesis-generated sequences. Extend
the existing registry corpus test to assert its transaction-unit layout.

P3-TX-01 is complete when the splitter contract and registry corpus assertions
pass with the repository verification gates. P3-OUT-01 remains responsible for
manifest line ranges and risk rationale serialization.
