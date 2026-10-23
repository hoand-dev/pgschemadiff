# P3-SQL-01 Emitter Dispatcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dispatch ordered deltas to SQL handlers and return ordered statements with transaction metadata.

**Architecture:** Add a pure `SqlEmitter` in `application/sql_emit/emitter.py` with an injected exact-type handler registry. It preserves input order, carries each source delta on its emitted statements, and fails closed for missing or invalid handlers.

**Tech Stack:** Python 3.13, `dataclasses`, `collections.abc`, pytest, Ruff, mypy.

**Spec:** `docs/specs/2026-10-23-p3-sql-01-emitter-dispatcher-design.md`

## Global Constraints

- Keep SQL emission in `application/sql_emit/`; do not add IO or SQL parsing.
- Use an injected exact-concrete-type handler registry; do not use global registration or default handler side effects.
- Preserve delta input order and each handler's statement order; do not sort.
- Missing handlers, empty handler output, blank SQL, or mismatched source-delta provenance raise `MigrationError`.
- Each frozen `SqlStatement` carries non-empty SQL, explicit `transactional: bool`, and originating `DeltaBase`.
- Emit forward SQL only; do not fabricate inverse SQL from deltas that lack prior values.
- The upstream generation use case applies `classify_risk` / `passes_risk_limit`; `SqlEmitter` does not own risk policy.
- Do not add concrete DDL, CLI, transaction splitting, migration writing, applier, domain delta changes, or dependencies.

---

## File structure

- `src/pgschemadiff/application/sql_emit/emitter.py` — immutable statement model, handler type, and ordered exact-type dispatcher.
- `tests/unit/application/sql_emit/test_emitter.py` — fake-handler tests for ordering, dispatch, failures, and immutability.

## Task 1: Ordered fail-closed dispatcher

**Files:**
- Create: `tests/unit/application/sql_emit/test_emitter.py`
- Create: `src/pgschemadiff/application/sql_emit/emitter.py`

**Interfaces:**
- Consumes: `DeltaBase` and `DeltaSet` from `pgschemadiff.domain.delta`; `MigrationError` from `pgschemadiff.shared.errors`.
- Produces:
  - `SqlStatement(sql: str, transactional: bool, delta: DeltaBase)` — frozen statement with source provenance.
  - `SqlHandler = Callable[[DeltaBase], Iterable[SqlStatement]]`.
  - `SqlEmitter(handlers: Mapping[type[DeltaBase], SqlHandler])`.
  - `SqlEmitter.emit(deltas: DeltaSet) -> tuple[SqlStatement, ...]`.

- [ ] **Step 1: Write the failing tests.** Create `test_emitter.py` with this complete test corpus:

```python
from dataclasses import FrozenInstanceError

import pytest

from pgschemadiff.application.sql_emit.emitter import SqlEmitter, SqlStatement
from pgschemadiff.domain.delta import (
    CreateSchema,
    DeltaBase,
    DeltaSet,
    DropSchema,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.shared.errors import MigrationError


def _schema_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )


_CREATE_REF = _schema_ref("created")
_DROP_REF = _schema_ref("removed")
_CREATE = CreateSchema(target=_CREATE_REF, pg_schema=Schema(ref=_CREATE_REF))
_DROP = DropSchema(target=_DROP_REF, pg_schema=Schema(ref=_DROP_REF))


def _emit_create(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    return (
        SqlStatement(sql="statement-a", transactional=True, delta=delta),
        SqlStatement(sql="statement-b", transactional=False, delta=delta),
    )


def _emit_drop(delta: DeltaBase) -> tuple[SqlStatement, ...]:
    return (SqlStatement(sql="statement-c", transactional=True, delta=delta),)


def _emit_nothing(_delta: DeltaBase) -> tuple[SqlStatement, ...]:
    return ()


def _emit_wrong_provenance(_delta: DeltaBase) -> tuple[SqlStatement, ...]:
    return (SqlStatement(sql="SELECT 1;", transactional=True, delta=_DROP),)


def test_emitter_preserves_delta_and_statement_order() -> None:
    deltas = DeltaSet.from_iterable((_CREATE, _DROP))
    emitter = SqlEmitter({CreateSchema: _emit_create, DropSchema: _emit_drop})

    statements = emitter.emit(deltas)

    assert tuple(statement.sql for statement in statements) == (
        "statement-a",
        "statement-b",
        "statement-c",
    )
    assert tuple(statement.transactional for statement in statements) == (True, False, True)
    assert tuple(statement.delta for statement in statements) == (_CREATE, _CREATE, _DROP)
    assert statements[0].delta is _CREATE
    assert deltas.deltas == (_CREATE, _DROP)


def test_empty_delta_set_emits_no_statements() -> None:
    assert SqlEmitter({}).emit(DeltaSet()) == ()


def test_missing_handler_raises_migration_error() -> None:
    with pytest.raises(MigrationError, match="CreateSchema"):
        SqlEmitter({}).emit(DeltaSet.from_iterable((_CREATE,)))


class DerivedCreateSchema(CreateSchema):
    pass


def test_subclass_does_not_fall_back_to_parent_handler() -> None:
    derived = DerivedCreateSchema(target=_CREATE.target, pg_schema=_CREATE.pg_schema)
    emitter = SqlEmitter({CreateSchema: _emit_create})

    with pytest.raises(MigrationError, match="DerivedCreateSchema"):
        emitter.emit(DeltaSet.from_iterable((derived,)))


def test_handler_must_emit_at_least_one_statement() -> None:
    with pytest.raises(MigrationError, match="no statements"):
        SqlEmitter({CreateSchema: _emit_nothing}).emit(DeltaSet.from_iterable((_CREATE,)))


def test_handler_cannot_attribute_statement_to_another_delta() -> None:
    with pytest.raises(MigrationError, match="provenance"):
        SqlEmitter({CreateSchema: _emit_wrong_provenance}).emit(
            DeltaSet.from_iterable((_CREATE,))
        )


def test_statement_rejects_blank_sql_and_is_frozen() -> None:
    with pytest.raises(MigrationError, match="blank"):
        SqlStatement(sql="  ", transactional=True, delta=_CREATE)

    statement = SqlStatement(sql="SELECT 1;", transactional=True, delta=_CREATE)
    with pytest.raises(FrozenInstanceError):
        statement.sql = "SELECT 2;"  # type: ignore[misc]
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --extra dev --no-sync pytest tests/unit/application/sql_emit/test_emitter.py -q`

Expected: collection fails with `ModuleNotFoundError` because `application.sql_emit.emitter` does not exist.

- [ ] **Step 3: Implement the minimum dispatcher.** Create `emitter.py`:

```python
"""Ordered dispatch from domain deltas to SQL statements."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from pgschemadiff.domain.delta import DeltaBase, DeltaSet
from pgschemadiff.shared.errors import MigrationError


@dataclass(frozen=True)
class SqlStatement:
    """One forward SQL statement and its execution/provenance metadata."""

    sql: str
    transactional: bool
    delta: DeltaBase

    def __post_init__(self) -> None:
        if not self.sql.strip():
            raise MigrationError("SQL statement must not be blank.")


SqlHandler = Callable[[DeltaBase], Iterable[SqlStatement]]


class SqlEmitter:
    """Dispatch deltas to exact-type handlers without changing their order."""

    def __init__(self, handlers: Mapping[type[DeltaBase], SqlHandler]) -> None:
        self._handlers = dict(handlers)

    def emit(self, deltas: DeltaSet) -> tuple[SqlStatement, ...]:
        statements: list[SqlStatement] = []
        for delta in deltas:
            handler = self._handlers.get(type(delta))
            if handler is None:
                raise MigrationError(
                    f"No SQL handler registered for delta type {type(delta).__name__}."
                )

            emitted = tuple(handler(delta))
            if not emitted:
                raise MigrationError(
                    f"SQL handler for {type(delta).__name__} emitted no statements."
                )

            for statement in emitted:
                if statement.delta is not delta:
                    raise MigrationError(
                        f"SQL statement provenance does not match {type(delta).__name__}."
                    )
                statements.append(statement)

        return tuple(statements)
```

- [ ] **Step 4: Verify GREEN.**

Run: `uv run --extra dev --no-sync pytest tests/unit/application/sql_emit/test_emitter.py -q`

Expected: all emitter tests pass; order, provenance, transaction flags, and fail-closed cases are covered.

- [ ] **Step 5: Run project gates.** Use a temporary project environment so `uv` does not replace the stale repository `.venv`:

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA 'Temp\opencode\pgschemadiff-p3-sql-01'
uv sync --extra dev --locked
uv run --extra dev --no-sync pytest tests/unit -q
uv run --extra dev --no-sync ruff check src tests
uv run --extra dev --no-sync ruff format --check src tests
uv run --extra dev --no-sync mypy src tests
uv run --extra dev --no-sync lint-imports
git diff --check
```

Expected: all unit tests and static gates pass. The repo `.venv` remains untouched.

- [ ] **Step 6: Commit.**

```powershell
git add -- src/pgschemadiff/application/sql_emit/emitter.py tests/unit/application/sql_emit/test_emitter.py
git diff --cached --check
git commit -m "feat(sql-emit): add ordered dispatcher"
```

## Completion criteria

- `SqlEmitter` dispatches by exact delta type and preserves input/handler order.
- Unsupported deltas, empty handler results, blank SQL, and mismatched provenance fail with `MigrationError`.
- `SqlStatement` is frozen and carries explicit transaction metadata and the originating delta.
- Empty input returns an empty tuple; no source delta or dependency changes are introduced.
- Unit tests, Ruff, formatting, mypy, import-linter, and `git diff --check` pass.
