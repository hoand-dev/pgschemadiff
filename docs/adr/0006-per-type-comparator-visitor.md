# ADR-0006 — Per-type Comparator + Visitor dispatcher for the diff engine

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

To diff two `Database` aggregates we can either:

1. Use a **generic deep-diff** (e.g. `deepdiff`) and post-process its output.
2. Implement a **per-object-type Comparator** that emits typed `Delta`
   subclasses.

PostgreSQL semantics differ sharply per object kind: a column reorder is
informational; an enum value removal is fatal; an index method change forces
a rebuild. Risk classification, dependency ordering, and SQL emission all
need to know which kind of change happened.

## Decision

Each `ObjectKind` has a dedicated `Comparator` (Protocol-typed). A central
`DiffEngine` dispatches `(source, target)` pairs to the right Comparator
based on `ObjectRef.kind`. Comparators emit `Delta` subclasses (a Pydantic
discriminated union) consumed downstream by the topo-sorter, risk classifier,
and SQL emitter.

## Consequences

- **Positive:**
  - Adding a new object kind = adding one Comparator class (Open/Closed)
  - Per-kind risk logic is colocated with the comparison logic
  - Easy to unit-test each Comparator in isolation
- **Negative:**
  - More code than a one-line `deepdiff(a, b)` call
- **Neutral:**
  - Naming convention: `application/diff/comparators/<kind>.py`.

## Alternatives considered

- **`deepdiff` + post-processing** — would need a custom semantic layer
  anyway; net code savings turn out negative once risk and dependency
  ordering are factored in.
- **Single mega-`Comparator`** — violates SRP; reject.

## References

- See `application/diff/engine.py` (Phase 2).
