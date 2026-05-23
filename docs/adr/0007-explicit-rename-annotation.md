# ADR-0007 — Explicit-annotation rename detection

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

When a column or table is renamed, the diff engine sees a "drop + add" by
default. Generating `DROP COLUMN` + `ADD COLUMN` will **destroy data** —
this is the single most catastrophic failure mode for a schema diff tool.

Heuristic detection (Levenshtein distance, type+nullability match, position
match) can recover renames automatically but produces false positives that
also destroy data (e.g. dropping `email_old` and adding `email_new` when
they are genuinely different columns).

## Decision

We will **not** detect renames heuristically. Renames are recognized only
via **explicit user annotation**, supplied as a YAML or TOML file passed to
`pgsd diff --renames renames.yml`:

```yaml
renames:
  - kind: column
    from: "public.users.email_addr"
    to:   "public.users.email"
  - kind: table
    from: "public.user_account"
    to:   "public.users"
```

Without annotation, the diff engine emits a `DESTRUCTIVE` `DropColumn` +
a `SAFE` `AddColumn`. The user must explicitly opt in via `--max-risk
DESTRUCTIVE` to generate the SQL.

A future ADR may add `--rename-hint` for interactive confirmation.

## Consequences

- **Positive:**
  - Zero false-positive renames
  - The user is forced to acknowledge data loss
  - Annotation file is checkable into version control
- **Negative:**
  - Worse UX for the common case of "I just renamed one column"
  - The user must learn the annotation format
- **Neutral:**
  - The TUI will offer a "looks like a rename — add annotation?" prompt.

## References

- See `docs/ROADMAP.md` Phase 2 → P2-DIFF-06.
