# P3-SQL-01 — SQL emitter dispatcher design

**Status:** Design sections approved in chat; written spec pending user review.
**Date:** 2026-10-23

## Goal

Dispatch an ordered `DeltaSet` to SQL handlers and return ordered SQL statements
with explicit transaction metadata. The dispatcher is a pure application-layer
component and fails clearly when no handler supports a delta.

## Decisions

- Keep SQL emission in `application/sql_emit/`; do not add IO or SQL parsing.
- Add `SqlEmitter` in `application/sql_emit/emitter.py` with an injected,
  exact-concrete-type handler registry. No global registration or default
  handler side effects.
- `SqlEmitter.emit(DeltaSet)` preserves both delta input order and each
  handler's statement order. It does not sort; callers provide already ordered
  deltas.
- A handler may emit one or more statements for one delta. Missing handlers and
  empty handler output raise `MigrationError`; no delta is silently skipped.
- Each frozen `SqlStatement` carries non-empty SQL, an explicit
  `transactional: bool`, and the originating `DeltaBase`. Explicit transaction
  metadata lets handlers mark statements such as `CREATE INDEX CONCURRENTLY`
  without parsing SQL later. Delta provenance lets a later transaction-unit
  builder associate emitted statements with risk assessments.
- P3-SQL-01 emits forward SQL only. Several current alteration deltas contain
  only desired values, not prior values, so a dispatcher cannot reliably
  synthesize rollback SQL from `DeltaSet` alone. P3-OUT-01 must either receive
  source state or explicitly annotate rollback as unavailable/irreversible;
  it must not fabricate inverse SQL.
- Risk classification and `passes_risk_limit` remain separate. The generation
  use case must apply the risk gate before invoking the emitter.
- Concrete DDL remains in P3-SQL-02..05. This task adds no SQL handlers, CLI,
  transaction splitter, migration writer, applier, delta-model changes, or
  dependencies.

## API contract

```python
@dataclass(frozen=True)
class SqlStatement:
    sql: str
    transactional: bool
    delta: DeltaBase


SqlHandler = Callable[[DeltaBase], Iterable[SqlStatement]]


class SqlEmitter:
    def __init__(
        self,
        handlers: Mapping[type[DeltaBase], SqlHandler],
    ) -> None: ...

    def emit(self, deltas: DeltaSet) -> tuple[SqlStatement, ...]: ...
```

Dispatch uses `type(delta)` lookup, not subclass fallback. This mirrors the
fail-closed policy for unknown delta subclasses. An unsupported delta raises
`MigrationError` with its kind/type in the message. `SqlStatement` rejects
blank SQL with `MigrationError`; the dispatcher also raises `MigrationError`
when a handler returns no statements or attributes a statement to a different
delta. An empty `DeltaSet` returns an empty tuple.

## Error handling and boundaries

- No database, filesystem, logging, SQL parser, or external dependency calls.
- The dispatcher validates dispatch/output contracts only; it does not decide
  whether SQL is safe, order dependencies, split transactions, or create
  rollback SQL.
- `MigrationError` represents missing/invalid emission. Risk-policy rejection
  remains the responsibility of the upstream generation use case.

## Tests and acceptance

Create `tests/unit/application/sql_emit/test_emitter.py` with fake handlers. It
must cover:

- registration and exact-type dispatch;
- stable preservation of delta order and handler statement order;
- multiple statements from one delta and source-delta provenance;
- explicit transactional metadata;
- empty input returning no statements;
- unsupported deltas and unknown subclasses failing with `MigrationError`;
- empty handler output, blank SQL, and mismatched statement provenance failing
  clearly;
- no mutation of the input `DeltaSet`.

P3-SQL-01 is complete when the dispatcher contract and tests pass, without
introducing concrete DDL or changing existing domain deltas.

## Open downstream contract

ADR-0008 requires `down.sql`, but the current delta API lacks old values for
some alterations. Before implementing P3-OUT-01, decide whether rollback
generation receives source state or records unavailable/irreversible changes
in the migration bundle. `MigrationWriter` currently accepts one SQL string and
will also need a separate contract update in P3-OUT-01.
