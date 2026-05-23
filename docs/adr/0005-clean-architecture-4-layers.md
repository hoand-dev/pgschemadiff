# ADR-0005 — Clean Architecture, 4 layers, enforced by import-linter

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

The project must remain maintainable as it grows from MVP (~5 object types)
to full PG18 coverage (~15 object types) and gains a TUI, CLI, HTML report,
and possibly a daemon/server mode. Without a layered architecture, business
logic tends to leak into the presentation layer and IO concerns infect the
domain.

## Decision

We adopt **Clean Architecture** with four layers, packaged as four
sub-packages under `src/pgschemadiff/`:

```
presentation/   ← Textual TUI, typer CLI                       (composition root)
infrastructure/ ← psycopg async inspector, file IO, applier    (implements ports)
application/    ← use cases: CompareSchemas, GenerateMigration (orchestrates)
domain/         ← pure Pydantic models, ports (Protocols)      (no IO, no async)
```

`shared/` holds cross-cutting utilities (logging, errors) and is importable
from any layer.

**Boundaries are enforced by `import-linter`** with four contracts:

1. Layered: `presentation → infrastructure → application → domain` (one-way)
2. Domain layer forbids `psycopg`, `asyncio`, `anyio`, `textual`, `typer`,
   `click`
3. Application forbids `pgschemadiff.infrastructure` and `psycopg`
4. Domain forbids any sibling layer

CI runs `lint-imports` on every commit.

## Consequences

- **Positive:**
  - Refactors localized to one layer
  - Use cases unit-testable without Docker (mock the `SchemaInspector` port)
  - TUI and CLI can ship independently because both depend only on
    `application/`
- **Negative:**
  - Boilerplate: extra `ports.py` Protocols
  - Slightly more imports than a flat layout
- **Neutral:**
  - Newcomers must read this ADR before adding files.

## References

- Robert C. Martin, *Clean Architecture* (2017)
- https://import-linter.readthedocs.io/
