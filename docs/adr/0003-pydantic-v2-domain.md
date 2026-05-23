# ADR-0003 — Pydantic v2 frozen models for the domain layer

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

The domain layer represents a PostgreSQL schema: tables, columns, indexes,
constraints, foreign keys, views, functions, sequences, enums, triggers, RLS
policies, types, etc. These models will be:

- Compared (deep equality)
- Serialized as JSON (TUI display, debugging, snapshot tests)
- Validated at the boundary (input from `pg_catalog`)
- Used as tagged unions in `Delta` (40+ subclasses)

## Decision

All domain types are **Pydantic v2 `BaseModel`** with `model_config =
ConfigDict(frozen=True, extra="forbid")`. Tagged unions (constraints, deltas)
use Pydantic's discriminated union with a `Literal[...]` `kind` or `op` field.

## Consequences

- **Positive:**
  - Free JSON serialization / deserialization
  - Validation at the inspector → domain boundary catches bugs early
  - `frozen=True` makes models hashable and comparable by value
  - Pydantic discriminator support is first-class
- **Negative:**
  - Slight runtime overhead vs. plain dataclasses (negligible at our scale)
- **Neutral:**
  - The `pydantic.mypy` plugin is enabled to keep `mypy strict` happy.

## Alternatives considered

- **`@dataclass(frozen=True, slots=True)`** — lighter but no JSON, no
  validation, no discriminator helpers; would force us to reinvent both.
- **attrs** — similar trade-offs to dataclasses; rejected for the same reasons.

## References

- https://docs.pydantic.dev/latest/concepts/models/
