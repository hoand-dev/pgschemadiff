# ADR-0009 — Five-level risk model: SAFE / WARNING / DANGEROUS / DESTRUCTIVE / BLOCKED

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

The same DDL statement can be fine on a 100-row dev table and catastrophic
on a 100M-row production table. The tool's job is not to ban changes — it
is to **classify** them so the operator decides. A binary "safe/unsafe"
flag is too coarse; a free-form severity string is too vague.

## Decision

Each `Delta` carries a `risk: RiskLevel` enum with **five** values:

| Level | Meaning | Examples |
|---|---|---|
| `SAFE` | Additive, no data change, no lock escalation | `CREATE INDEX CONCURRENTLY`, `ADD COLUMN NULL`, `CREATE FUNCTION`, `ALTER TYPE ADD VALUE` |
| `WARNING` | Additive but heavy lock or rewrite | `ADD COLUMN NOT NULL DEFAULT`, `CREATE INDEX` (non-concurrent), `VALIDATE CONSTRAINT` |
| `DANGEROUS` | Data-preserving but blocking-long | `ALTER COLUMN TYPE` (rewrite), `ADD PRIMARY KEY` (non-concurrent) |
| `DESTRUCTIVE` | Possible data loss | `DROP COLUMN`, `DROP TABLE`, `DROP CONSTRAINT` |
| `BLOCKED` | PostgreSQL cannot express this safely; refuses to generate | enum value removal, column reorder, rename without annotation |

The CLI gates generation behind `--max-risk <level>` (default: refuses
`DESTRUCTIVE` and `BLOCKED`). The TUI surfaces a coloured risk badge per
delta. The risk of a generated migration is `max(deltas.risk)`.

## Consequences

- **Positive:**
  - Operators have a clear vocabulary
  - Safe default (no destructive change without explicit opt-in)
  - CI pipelines can fail PRs that introduce `DESTRUCTIVE` changes
- **Negative:**
  - The classifier must encode PostgreSQL operational knowledge per delta
- **Neutral:**
  - `BLOCKED` is distinct from `DESTRUCTIVE`: a blocked change refuses to
    generate SQL at all, while a destructive one will generate `DROP` if
    the user opts in.

## References

- See `application/sql_emit/risk.py` (Phase 3, P3-RISK-01).
