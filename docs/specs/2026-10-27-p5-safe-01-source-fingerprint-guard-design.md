# P5-SAFE-01 — Source fingerprint guard design

**Status:** Approved by reviewer; implementation complete (CI `c549bd2`). Added outcome `skipped_applied` for an already-applied bundle.
**Date:** 2026-10-27
**Task:** new `docs/TASKS.md` row P5-SAFE-01 "Refuse apply when the database is not the bundle's source state"
**Plan:** `docs/plans/2026-10-27-p5-safe-01-implementation-plan.md`

## Problem

A bundle is a list of changes computed against one schema state (the
*current* database at generate time). Nothing checks that the database it is
applied to is still in that state. `generate_migration` accepts
`source_fingerprint` / `target_fingerprint`, but the CLI and TUI pass `None`,
so the manifest fields are always `null`.

Consequences: a bundle applied to the wrong database, to the right database
after someone changed it, or twice in different environments runs DDL that
was never reviewed for that state. The TUI direction bug fixed in `04fb3bb`
(bundle generated for one database, applied to the other) would have been
caught by this guard.

## Goals

1. Every new bundle records a fingerprint of the current schema and of the
   desired schema, plus the schema scope they were computed over.
2. Before a real apply or a dry run, the applier re-inspects the target
   database with the same scope and refuses on mismatch.
3. Explicit, auditable override in the CLI only.
4. Old bundles (format 1, no fingerprints) keep working with a warning.

## Fingerprint

`application/diff/fingerprint.py` (pure, no IO):

```python
def schema_fingerprint(database: Database) -> str  # "sha256:<64 hex>"
```

- SHA-256 over canonical JSON of the snapshot:
  `database.model_dump(mode="json")` with the top-level `name` removed,
  serialised with `sort_keys=True, separators=(",", ":"), ensure_ascii=False`.
- The database name is excluded so a bundle generated against a restored copy
  (e.g. staging restored from production) validates against the original.
- Before relying on it, verify the snapshot contains no volatile values
  (OIDs, statistics, sequence `last_value`, timestamps). If any exist, exclude
  them explicitly in this function and list them in a comment. Ordering must
  be deterministic: the inspector's catalog SQL already uses `ORDER BY`;
  confirm, and sort any collection that is not ordered.

## Manifest format 2

- `format_version: 2`; new required key `inspected_schemas`: list of schema
  names passed to the inspector, or `null` meaning "all user schemas".
- `source_fingerprint` / `target_fingerprint` are required non-null strings
  in format 2 (`sha256:` + 64 lowercase hex).
- `load_bundle` accepts format 1 (unchanged rules; fingerprints may be null,
  `inspected_schemas` absent → treated as unknown) and format 2. Any other
  version is rejected as today.
- `render_bundle` writes format 2 only. Bundle `README.md` already prints
  fingerprints when present; add the schema scope line.
- `MigrationPlan` gains `inspected_schemas: tuple[str, ...] | None`.

## Generate

- `presentation/cli/commands/generate.py` and the TUI Migration view compute
  both fingerprints from `SchemaComparisonResult.source` / `.target` (the TUI
  stores snapshots by profile role — current is `session.last_comparison.target`;
  get this right and test it) and pass `inspected_schemas` (CLI `--schema`
  list or `None`; TUI `profile.schemas or None`).

## Apply guard

Application use case in `application/migration/guard.py`:

```python
class SourceStateMismatchError(MigrationError): ...

async def verify_source_state(
    bundle: ValidatedBundle,
    inspector: SchemaInspector,
    history: MigrationHistoryReader | None = None,
) -> GuardResult  # MATCH | SKIPPED_LEGACY | SKIPPED_RESUME
```

- Format 1 bundle → `SKIPPED_LEGACY` (caller prints a warning:
  "Bundle has no source fingerprint (format 1); the database state cannot be verified.").
- If the history shows a previous run of the same bundle id that is not
  `applied` (a resume) → `SKIPPED_RESUME`: completed units already changed the
  schema, so the original fingerprint cannot match. If the run is already
  `applied`, the existing applier behaviour (already applied) is unchanged.
- Otherwise inspect with `bundle.inspected_schemas`, compute the fingerprint,
  and raise `SourceStateMismatchError` if it differs from
  `bundle.source_fingerprint`. The error message names both short
  fingerprints (first 12 hex) — never connection data.

Wiring:
- CLI `apply` (real and `--dry-run`): run the guard before confirmation
  prompts. Mismatch → stderr
  `Error: Database schema does not match the bundle's source state (expected <a>, found <b>). Re-run generate against this database, or pass --skip-source-check after review.`
  exit **2**. New flag `--skip-source-check` skips it and prints a warning
  line. Dry run reports the guard result.
- TUI apply and dry run: same guard; mismatch shows the same text (without the
  flag hint) in the Apply view and does not open the confirmation modal. No
  override in the TUI.
- Inspector and history reader come from `presentation/composition.py`
  (reuse `open_inspectors`-style pool setup for a single connection; add a
  small `open_inspector(conninfo, schemas)` helper).

## Post-apply verification (report only)

After a successful real apply (not resume), re-inspect and compare with
`bundle.target_fingerprint`; print `Verified: database now matches the desired
schema.` or a warning `Warning: database does not match the desired schema
after apply; run diff to inspect.` Exit code stays 0. Skip for format 1.

## Non-goals

- No data checks, no locking between the guard and the apply (a concurrent
  DDL change in that window is out of scope; document it).
- No fingerprint in `diff` output.

## Tests

- Unit: fingerprint determinism, name exclusion, sensitivity to a column type
  change; manifest v1/v2 load and v2 render (update snapshots); guard
  match/mismatch/legacy/resume with fake inspector and history; CLI apply
  exit 2 on mismatch, `--skip-source-check`, dry-run reporting, legacy
  warning; TUI mismatch blocks the modal; TUI generate uses the current
  (profile target) snapshot for `source_fingerprint`.
- Integration (PG18): generate on db A, apply to db B with a different schema
  → exit 2; apply to A → success and "Verified"; inspect the same database
  twice → identical fingerprint; two databases with identical DDL but
  different names → identical fingerprint.
- Cookbook and round-trip integration tests must keep passing.

## Docs

`docs/guide/bundles.md` (format 2, fingerprints, scope), `cli.md`
(`--skip-source-check`, new exit-2 case), `risk-and-safety.md` (workflow step),
`limitations.md` (guard-to-apply window). `docs/TASKS.md` row P5-SAFE-01.

## Done when

Gate green, CI green (all integration incl. cookbook), docs updated.
