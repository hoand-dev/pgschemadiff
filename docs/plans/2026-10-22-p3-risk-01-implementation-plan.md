# P3-RISK-01 Risk Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify each supported schema delta into a stable risk level and gate assessment collections using a configurable severity limit.

**Architecture:** Keep domain delta models unchanged. Add pure risk types and classification in `application/sql_emit/risk.py`; tests exercise the public constructors and risk policy. Update ADR-0009 to document external assessments and the fail-closed default gate.

**Tech Stack:** Python 3.13, `enum.StrEnum`, frozen `dataclass`, pytest, Ruff, mypy.

**Spec:** `docs/specs/2026-10-22-p3-risk-01-risk-classifier-design.md`

## Global Constraints

- Keep all existing domain delta models unchanged.
- Classify deltas only; defer table row-count/size estimates and other live catalog context.
- Unknown `DeltaBase` subclasses fail closed as `BLOCKED`.
- Default generation limit is `DANGEROUS`; `BLOCKED` never passes, even when explicitly selected as the limit.
- `RiskAssessment.reason` is deterministic, non-empty, and explains the classification.
- Classifier performs no database access, mutation, logging, SQL parsing, or external dependency calls.
- Do not implement SQL emission, transaction splitting, migration writing, CLI options, or statistics collection in this task.

---

## File structure

- `src/pgschemadiff/application/sql_emit/risk.py` — `RiskLevel`, immutable `RiskAssessment`, `classify_risk`, and `passes_risk_limit`. The package `__init__.py` already exists and stays unchanged.
- `tests/unit/application/sql_emit/test_risk.py` — tests for value ordering, assessment invariants, every classifier mapping/branch, unknown deltas, and gate limits.
- `docs/adr/0009-five-level-risk-model.md` — replace the per-Delta risk decision with the external-assessment contract and align meanings/default behavior with the spec.

## Task 1: Risk types and generation gate

**Files:**
- Create: `tests/unit/application/sql_emit/test_risk.py`
- Create: `src/pgschemadiff/application/sql_emit/risk.py`

**Interfaces:**
- Consumes: `DeltaBase` from `pgschemadiff.domain.delta`.
- Produces: `RiskLevel`, frozen `RiskAssessment(delta, level, reason)`, and `passes_risk_limit(assessments, *, max_risk=RiskLevel.DANGEROUS) -> bool`.

- [ ] **Step 1: Write failing API tests.** Build one valid `CreateSchema` delta from a `Schema` and matching schema `ObjectRef`. Assert enum declaration order is `SAFE`, `WARNING`, `DANGEROUS`, `DESTRUCTIVE`, `BLOCKED`; assessment retains original delta; blank/whitespace reason raises `ValueError`; assigning to `reason` raises `FrozenInstanceError`.

Use these imports and local fixtures in `test_risk.py`:

```python
from dataclasses import FrozenInstanceError

import pytest

from pgschemadiff.application.sql_emit.risk import (
    RiskAssessment,
    RiskLevel,
    passes_risk_limit,
)
from pgschemadiff.domain.delta import CreateSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema


_SCHEMA_REF = ObjectRef(
    kind=ObjectKind.SCHEMA,
    qname=QualifiedName(namespace="public", name="public"),
)
_DELTA = CreateSchema(target=_SCHEMA_REF, pg_schema=Schema(ref=_SCHEMA_REF))


def _assessment(level: RiskLevel) -> RiskAssessment:
    return RiskAssessment(delta=_DELTA, level=level, reason=level.value)


def test_risk_levels_have_explicit_severity_order() -> None:
    assert tuple(level.name for level in RiskLevel) == (
        "SAFE",
        "WARNING",
        "DANGEROUS",
        "DESTRUCTIVE",
        "BLOCKED",
    )


def test_assessment_keeps_delta_is_frozen_and_rejects_blank_reason() -> None:
    assessment = _assessment(RiskLevel.SAFE)
    assert assessment.delta is _DELTA
    with pytest.raises(FrozenInstanceError):
        setattr(assessment, "reason", "changed")
    with pytest.raises(ValueError):
        RiskAssessment(delta=_DELTA, level=RiskLevel.SAFE, reason="  ")


def test_default_risk_limit_allows_through_dangerous() -> None:
    allowed = tuple(_assessment(level) for level in (
        RiskLevel.SAFE,
        RiskLevel.WARNING,
        RiskLevel.DANGEROUS,
    ))
    assert passes_risk_limit(allowed)
    assert not passes_risk_limit((_assessment(RiskLevel.DESTRUCTIVE),))


def test_blocked_never_passes_even_when_selected_as_limit() -> None:
    assert not passes_risk_limit(
        (_assessment(RiskLevel.DANGEROUS),),
        max_risk=RiskLevel.WARNING,
    )
    assert passes_risk_limit(
        (_assessment(RiskLevel.DESTRUCTIVE),),
        max_risk=RiskLevel.DESTRUCTIVE,
    )
    assert not passes_risk_limit(
        (_assessment(RiskLevel.BLOCKED),),
        max_risk=RiskLevel.BLOCKED,
    )


def test_empty_assessment_collection_passes() -> None:
    assert passes_risk_limit(())
```

- [ ] **Step 2: Verify RED.** Run `uv run pytest tests/unit/application/sql_emit/test_risk.py -q`. Expected: collection fails because `application.sql_emit.risk` does not exist.
- [ ] **Step 3: Implement the minimum API.** Define lowercase string values on `RiskLevel(StrEnum)`, a frozen dataclass with `delta: DeltaBase`, `level: RiskLevel`, and `reason: str`; reject blank reasons in `__post_init__`. Use an explicit rank map and `all(...)` for the gate so empty input passes and `BLOCKED` is always rejected:

```python
return all(
    assessment.level is not RiskLevel.BLOCKED
    and _RISK_RANK[assessment.level] <= _RISK_RANK[max_risk]
    for assessment in assessments
)
```

- [ ] **Step 4: Verify GREEN.** Run `uv run pytest tests/unit/application/sql_emit/test_risk.py -q`; all API and gate tests pass.
- [ ] **Step 5: Commit.** `git add src/pgschemadiff/application/sql_emit/risk.py tests/unit/application/sql_emit/test_risk.py`; commit as `feat(risk): add assessment and risk gate`.

## Task 2: Delta classifier and complete policy corpus

**Files:**
- Modify: `src/pgschemadiff/application/sql_emit/risk.py`
- Modify: `tests/unit/application/sql_emit/test_risk.py`

**Interfaces:**
- Consumes: Task 1 `RiskLevel`, `RiskAssessment`, and `passes_risk_limit`.
- Produces: `classify_risk(delta: DeltaBase) -> RiskAssessment`; each known variant follows the spec matrix, with a final fail-closed `BLOCKED` branch.

- [ ] **Step 1: Write failing classifier tests.** Use valid instances of each public delta model and a parameterized corpus. Cover every concrete type and every conditional rule in the spec:
  - `CreateSchema` / `DropSchema`: `SAFE` / `DESTRUCTIVE`.
  - `CreateExtension` / `DropExtension`: `WARNING` / `DESTRUCTIVE`; `AlterExtension` with schema-only / version change: `WARNING` / `DANGEROUS`.
  - Ordinary / partition-child `CreateTable`: `SAFE` / `WARNING`; `DropTable`: `DESTRUCTIVE`; `RenameTable`: `WARNING`.
  - `AlterTableAttrs` owner/comment, tablespace, partition metadata, and mixed tablespace+partition changes: `SAFE`, `WARNING`, `DANGEROUS`, with mixed changes taking the highest level.
  - `AddColumn` nullable without default/identity/generated expression, plus non-null, default, identity, and generated variants: `SAFE` / `WARNING`; `DropColumn`: `DESTRUCTIVE`.
  - `AlterColumnType`: `DANGEROUS`; `SetColumnDefault`: `SAFE`; nullable / not-null `SetColumnNullability`: `SAFE` / `DANGEROUS`; `RenameColumn`: `WARNING`.
  - `CreateIndex`: `WARNING`; non-unique / unique `DropIndex`: `DANGEROUS` / `DESTRUCTIVE`; ordinary / unique-to-non-unique `ReplaceIndex`: `DANGEROUS` / `DESTRUCTIVE`.
  - `AddConstraint` / `DropConstraint`: `DANGEROUS` / `DESTRUCTIVE`; build AddConstraint cases using each of the five constraint payload kinds.

Define `RISK_CASES` as literal `pytest.param(delta, expected_level, id=...)`
entries for those cases; never calculate expected levels using classifier
logic. Build shared `ObjectRef`, table, column, index, schema, extension, and
constraint values with valid constructors. Use
`tests/unit/domain/delta/test_table.py`, `test_column.py`, `test_index.py`,
`test_constraint.py`, and `test_schema.py` as constructor references.

Use this assertion for each corpus row so assessment identity, level, and reason contract all get checked:

```python
@pytest.mark.parametrize(("delta", "expected_level"), RISK_CASES)
def test_classify_risk_matches_policy(delta: DeltaBase, expected_level: RiskLevel) -> None:
    assessment = classify_risk(delta)
    assert assessment.delta is delta
    assert assessment.level is expected_level
    assert assessment.reason.strip()
    assert classify_risk(delta).reason == assessment.reason
```

Add this unknown-type regression and assert it classifies as `BLOCKED` and
fails the gate even with `max_risk=RiskLevel.BLOCKED`:

```python
class UnsupportedDelta(DeltaBase):
    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["unsupported"] = "unsupported"


def test_unknown_delta_fails_closed() -> None:
    delta = UnsupportedDelta(op=DeltaOp.ALTER, target=_SCHEMA_REF)
    assessment = classify_risk(delta)
    assert assessment.level is RiskLevel.BLOCKED
    assert not passes_risk_limit((assessment,), max_risk=RiskLevel.BLOCKED)
```

Import `Literal`, `DeltaBase`, and `DeltaOp`; keep all shared value builders local to `test_risk.py`.

- [ ] **Step 2: Verify RED.** Run `uv run pytest tests/unit/application/sql_emit/test_risk.py -q`. Expected: classifier import/test failures because `classify_risk` is not implemented.
- [ ] **Step 3: Implement explicit classification branches.** Import concrete delta classes from `pgschemadiff.domain.delta`; use `isinstance` branches and inspect only documented payload fields. For `AlterTableAttrs`, take highest field severity; for `AddColumn`, require nullable and absence of default/identity/generated expression for `SAFE`; for index drops/replacements, classify loss of uniqueness as `DESTRUCTIVE`. Return a deterministic non-empty reason for every branch. Final fallback returns `BLOCKED` without serializing/repr-ing the delta.
- [ ] **Step 4: Verify GREEN.** Run `uv run pytest tests/unit/application/sql_emit/test_risk.py -q`; every policy case, unknown type, and gate test passes.
- [ ] **Step 5: Commit.** Commit implementation and tests as `feat(risk): classify schema deltas`.

## Task 3: Align ADR-0009 and run project gates

**Files:**
- Modify: `docs/adr/0009-five-level-risk-model.md`
- Verify: `src/pgschemadiff/application/sql_emit/risk.py`, `tests/unit/application/sql_emit/test_risk.py`

**Interfaces:**
- Consumes: Task 2 classifier contract and the approved spec.
- Produces: ADR-0009 consistent with external `RiskAssessment`, delta-only classification, default `DANGEROUS` gate, and absolute `BLOCKED` rejection.

- [ ] **Step 1: Update the ADR.** Replace “Each `Delta` carries a risk” with external per-delta assessments. Align the five level descriptions and examples with the spec, state default `DANGEROUS`, permit `DESTRUCTIVE` only with a higher explicit limit, state `BLOCKED` can never be overridden, define migration risk as the highest assessment, and document deferred table-size context.
- [ ] **Step 2: Review consistency.** Compare every ADR policy statement against `docs/specs/2026-10-22-p3-risk-01-risk-classifier-design.md`; remove claims that differ, especially `CREATE INDEX CONCURRENTLY` being `SAFE` without execution-mode context.
- [ ] **Step 3: Run full unit tests.** Run `uv run pytest tests/unit -q`; expected: all unit tests pass.
- [ ] **Step 4: Run static gates.** Run `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src tests`, `uv run lint-imports`, and `git diff --check`; all must exit successfully.
- [ ] **Step 5: Commit.** Commit ADR alignment as `docs(risk): align ADR with classifier`.

## Completion criteria

- Every current delta variant and every conditional mapping in the spec has a passing unit case.
- Unknown subclasses are `BLOCKED`; no gate threshold can allow `BLOCKED`.
- Default gate allows risks through `DANGEROUS` and rejects `DESTRUCTIVE`.
- ADR-0009 and the implementation use the same external-assessment contract and risk policy.
- Unit and static gates pass; no SQL emitter, CLI, domain delta, or dependency changes are introduced.
