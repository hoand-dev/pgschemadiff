# ADR-0008 — Multi-file migration output with manifest.json

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

A generated migration may contain statements that **cannot run in a single
transaction** — most notably `CREATE INDEX CONCURRENTLY`, `DROP INDEX
CONCURRENTLY`, `REINDEX CONCURRENTLY`, and (in some PG versions) `ALTER
TYPE ... ADD VALUE`. The applier needs to know which statements are
transactional and which must each run in their own implicit transaction.

A single `up.sql` blob loses this information. So does a single
`migrations.json` blob — humans read SQL.

## Decision

A migration is a directory:

```
migrations/20260523_120000_diff/
├── manifest.json   # ordered transaction units, risks, fingerprints
├── up.sql          # human-readable forward migration
├── down.sql        # best-effort rollback (annotated where irreversible)
├── deltas.json     # the DeltaSet that produced this migration
└── README.md       # auto-generated summary with risk table
```

`manifest.json` lists ordered "transaction units" with `{start_line,
end_line, transactional: bool, max_risk: str, reason: str}`. The applier
reads the manifest, slices `up.sql`, and executes each unit with the
correct `BEGIN`/`COMMIT` semantics.

## Consequences

- **Positive:**
  - Humans can read `up.sql` directly
  - Applier correctly handles non-tx statements
  - `deltas.json` enables re-running with different output options (e.g.
    swap risk thresholds without re-diffing)
  - `manifest.json` is a stable contract for third-party CI/CD integration
- **Negative:**
  - More files to ship than a single SQL blob
- **Neutral:**
  - The format is versioned via `manifest.json["tool_version"]`.

## References

- See `application/sql_emit/` (Phase 3).
