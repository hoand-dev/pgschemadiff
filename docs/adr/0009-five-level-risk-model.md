# ADR-0009 — Five-level risk model: SAFE / WARNING / DANGEROUS / DESTRUCTIVE / BLOCKED

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

Risk needs to describe operational impact without changing the domain diff
contract. The same change can have different impact depending on table size,
but current deltas do not carry row-count or size estimates. A binary
safe/unsafe flag is too coarse, and a free-form severity string is too vague.

## Decision

Risk is an external assessment of each domain delta; a `Delta` does not carry
risk metadata. The immutable `RiskAssessment` contains the original `delta`,
its `RiskLevel`, and a deterministic, non-empty `reason`. Classification is
static and delta-only. It does not inspect SQL, execution mode, or live catalog
state. Conditional rules use the highest applicable severity.

The five levels are ordered explicitly from least to most severe:

| Level | Meaning | Examples |
|---|---|---|
| `SAFE` | Additive or metadata-only change with no expected data rewrite or material lock. | Create an empty schema or table; add a nullable column without a default, identity, or generated expression; change owner/comment or a column default; allow NULLs. |
| `WARNING` | Usually data-preserving, but may need operator attention for locking, table work, or extension scripts. | Install or relocate an extension; create a partition child; rename a table or column; change tablespace; add a column with a default, `NOT NULL`, identity, or generated expression; create an index when execution mode is unspecified. |
| `DANGEROUS` | May block for a material duration, require validation/rebuild, or change operational/integrity behavior. | Update an extension version; change partition metadata; alter a column type; set `NOT NULL`; drop a non-unique index; rebuild an index; add a constraint. |
| `DESTRUCTIVE` | Removes data, schema objects, or an enforced integrity guarantee. Requires explicit opt-in above the default limit. | Drop a schema, table, column, extension, or constraint; drop a unique index; replace a unique index with a non-unique one. |
| `BLOCKED` | No explicit risk policy exists or the operation is unsupported. Never generate. | An unrecognized `DeltaBase` subclass. |

`CreateIndex` is `WARNING`: the delta has no execution-mode field, so the
classifier cannot prove that `CONCURRENTLY` will be used. Classifications are
policy assessments, not guarantees about PostgreSQL execution, errors, or
downtime.

The risk limit defaults to `DANGEROUS`: `SAFE`, `WARNING`, and `DANGEROUS`
assessments pass; `DESTRUCTIVE` does not. `DESTRUCTIVE` passes only when the
caller explicitly raises the limit, for example to `DESTRUCTIVE`. `BLOCKED`
never passes, even when selected as the limit. A migration's aggregate risk is
the highest delta assessment; an empty assessment set has no risky delta.

Table-size/row-count estimates and other live catalog context are deferred
until the domain or inspector can supply that information.

## Consequences

- **Positive:**
  - Risk explanations stay outside domain deltas, preserving the diff contract.
  - The default gate rejects destructive changes, and unsupported deltas fail closed.
- **Negative:**
  - Static rules are conservative and cannot refine risk using table size or execution context.
  - The classifier must maintain explicit operational policy for each delta type.
- **Neutral:**
  - `BLOCKED` is distinct from `DESTRUCTIVE`: a destructive assessment can pass
    with an explicit higher limit; a blocked assessment cannot pass any limit.

## References

- `docs/specs/2026-10-22-p3-risk-01-risk-classifier-design.md`
- `src/pgschemadiff/application/sql_emit/risk.py` (P3-RISK-01).
