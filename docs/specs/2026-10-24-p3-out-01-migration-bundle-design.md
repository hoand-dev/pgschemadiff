# P3-OUT-01 — Migration bundle writer design

**Status:** Approved with review decisions (2026-10-24)  
**Date:** 2026-10-24

## Goal

Turn an ordered `DeltaSet` into a risk-gated, deterministic migration plan and
an atomically written ADR-0008 bundle. Keep generation pure, preserve each
statement's transaction metadata, and never invent rollback SQL.

## Decisions

- Add the application use case in `application/migration/generate.py`.
  Accept an ordered or unordered `DeltaSet`, `max_risk` (default
  `RiskLevel.DANGEROUS`), optional source/target fingerprints, a path-safe
  `slug` (default `diff`), and injectable `clock` and `id_factory`. The default
  clock returns aware UTC time; the default ID factory returns a UUID string.
- Generation steps: call `order_deltas`; classify every ordered delta once with
  `classify_risk`; call `passes_risk_limit`; on rejection raise `MigrationError`
  listing each offending delta's stable bundle ID, kind/target, risk level, and
  reason; only after the gate passes, emit with
  `SqlEmitter(default_handlers())`, then call `split_units`. Do not emit SQL or
  write files for a rejected plan.
- Return a frozen application-layer `MigrationPlan` containing the generated
  ID, slug, UTC `created_at`, ordered `DeltaSet`, optional fingerprints,
  per-delta risk/reversibility assessments, ordered units with per-unit max
  risk, and overall max risk (`None` for an empty set). Assign bundle-local
  delta IDs `d0001`, `d0002`, … by ordered position; retain original delta
  identity when associating emitted statements with those IDs.
- Keep `MigrationPlan` and its unit/assessment records in
  `application/migration/model.py`, using frozen dataclasses consistent with
  `RiskAssessment`, `SqlStatement`, and `TransactionUnit`. The plan combines
  application SQL/risk concepts and must not become a domain model.
- Move `MigrationWriter` from `domain/ports.py` to the application-owned
  output port `application/migration/ports.py`. A domain port cannot type
  reference an application plan without reversing the ADR-0005 dependency.
  `domain/ports.py` remains the home of domain-facing inspection ports.
- Use sync filesystem port `write(plan: MigrationPlan, output_dir: Path) ->
  Path`; `output_dir` is the bundle parent and the returned path is the created
  bundle directory. The filesystem adapter lives in
  `infrastructure/fs/migration_writer.py`.

## Rollback contract

- MVP-A chooses option **(b)**: `down.sql` is explicitly non-executable. It
  contains a warning header and one `-- IRREVERSIBLE: <reason>` comment for
  every delta. The manifest records `reversible: false` and a reason per delta,
  including deltas whose inverse might appear obvious. MVP does not infer
  inverse SQL from incomplete deltas.
- Never fabricate inverse SQL. In a later version, generation may accept the
  source `Database` snapshot and emit inverse DDL only for deltas whose old
  schema state is complete; data removed by drops remains irreversible without
  a separate backup/restore contract.

## Bundle contract

Create `<output_dir>/<YYYYMMDD_HHMMSS>_<slug>/` with exactly these files:

```text
up.sql
down.sql
manifest.json
deltas.json
README.md
```

The timestamp is UTC, seconds precision. Validate `slug` against a conservative
lowercase ASCII filename form; reject separators, `.`/`..`, and empty values.
If the destination already exists, fail; do not append a suffix or overwrite.
A same-second/same-slug collision is therefore a typed error, not a
non-deterministic rename.

### SQL rendering

- `up.sql` is a human-readable, psql-runnable script. Render exactly this
  structure, omitting optional risk values only where shown as `none`:

  ```sql
  -- pgschemadiff migration: <id>
  -- created_at: <UTC ISO-8601 timestamp>
  -- max_risk: <RiskLevel.value|none>
  -- pgschemadiff unit: <zero-based index> transactional=<true|false> max_risk=<value>
  BEGIN;
  -- delta: <delta_id>
  <statement SQL>
  COMMIT;

  -- pgschemadiff unit: <zero-based index> transactional=<true|false> max_risk=<value>
  -- delta: <delta_id>
  <statement SQL>
  ```

  The `BEGIN;` / `COMMIT;` lines appear only for transactional units; each such
  unit gets its own pair, including `new_unit` splits. Non-transactional SQL is
  outside wrappers. A transactional unit may contain multiple statements;
  each gets its own delta comment. Preserve each `statement.sql` except convert
  CRLF/CR to LF and remove trailing LF characters; add exactly one LF after it.
  Add one blank line between units, none between statements beyond their
  required final LF, and exactly one final LF in the file. Statement line
  ranges cover SQL text only, excluding delta/unit comments and wrappers; unit
  ranges span first through last statement SQL. Empty plans contain the three
  header lines and no units. Use `psql -v ON_ERROR_STOP=1 -f up.sql` for
  fail-fast manual use.
- `down.sql` starts with `-- pgschemadiff rollback unavailable: <id>` and
  `-- MVP-A emits no inverse SQL; following entries are annotations only.` Then
  emit one line per ordered delta:
  `-- <delta_id> IRREVERSIBLE: MVP-A does not derive inverse SQL from DeltaSet; complete prior state may be missing.`
  It has no `BEGIN`, `COMMIT`, or SQL statements, and ends with exactly one LF.
- `deltas.json` is the exact ordered `DeltaSet.model_dump_json(indent=2)`
  representation printed by `pgsd diff`, followed by one LF. Do not add risk or
  bundle metadata to this file.
- `README.md` is deterministic and summarizes ID/date, fingerprints when
  present, delta count, overall risk, unit transaction/risk table, file list,
  checksums, and the irreversible rollback warning. Do not include database
  URLs or credentials.

### `manifest.json` version 1

Use UTF-8, two-space indentation, fixed field declaration order, LF line
endings, and one final LF. Preserve ordered arrays; do not depend on map/set
iteration order. Store risk levels using `RiskLevel.value` (lowercase). The
top-level fields, in order, are:

| Field | Meaning |
|---|---|
| `format_version` | Integer `1`; bundle schema version, independent of tool version. |
| `tool_version` | Installed pgschemadiff version. |
| `id`, `slug`, `created_at` | Plan identity, directory label, UTC ISO-8601 timestamp. |
| `source_fingerprint`, `target_fingerprint` | Optional caller-supplied stable fingerprints; `null` when unavailable. Never store connection URLs. |
| `delta_count`, `overall_max_risk` | Count and highest assessed level; `null` risk for no deltas. |
| `assessments` | Ordered entries `{delta_id, kind, target, level, reason, reversible, reversibility_reason}`. |
| `units` | Ordered execution units, as defined below. |
| `checksums` | `{up_sql_sha256}` and no self-checksum. |

Each unit has `index` (zero-based), `transactional`, `start_line` and `end_line`
(one-based inclusive span of its SQL), `max_risk`, ordered unique `delta_ids`,
`statements`, and `sql_sha256`. Each statement entry has its `delta_id` and
one-based inclusive `start_line`/`end_line` in `up.sql`. Preserve statement
order and provenance; do not make the applier parse SQL to find boundaries.
`sql_sha256` is SHA-256 over the exact UTF-8 bytes of that unit's statement SQL
in order, with one LF appended to each statement. `checksums.up_sql_sha256` is
SHA-256 over the complete `up.sql` bytes, including comments and wrappers.
P3-APPLY-01 verifies both before execution, then executes statement ranges
according to unit transaction metadata.

The manifest gives the future MigrationView its SQL ranges, unit plan, risk,
reversibility, and checksum. It gives HistoryView generated-plan identity,
creation time, fingerprints, count, risk, checksum, and rollback status. Apply
status, duration, and execution timeline are not known at generation time and
belong to P3-APPLY-01 run-history records, not mutation of this bundle.

## Port and atomic filesystem behavior

- `MigrationWriter.write(plan, output_dir) -> Path` is synchronous and
  infrastructure-independent at its boundary. Keep the renderer pure in the
  application layer; the adapter performs only file operations.
- Render all file bytes before exposing the destination. Create a unique temp
  sibling directory under `output_dir`; write every file in binary mode, flush
  and `fsync` each file, then `fsync` the temp directory where supported. Rename
  the complete directory atomically to the final name, then sync the parent
  where supported. Check for an existing final path before work and again
  immediately before rename. Never merge with or replace an existing bundle.
- On an `OSError`, clean up only the adapter-created temp directory on a
  best-effort basis and raise `MigrationError` with the operation/path context
  and original exception as cause. The final bundle path must never expose a
  partially written bundle. Windows rename/delete/fsync restrictions are
  implementation risks to test, not reasons to weaken the layout contract.

## Determinism and errors

- Same ordered delta values, options, fingerprints, injected clock, and injected
  ID produce byte-identical files. Defaults are intentionally time/ID varying;
  tests inject both. Render UTC timestamps canonically with `Z`; use LF only,
  UTF-8, fixed JSON field order, stable delta IDs, and exactly one final LF in
  every text file.
- Risk-gate failures use `MigrationError` and include offending deltas and
  levels in deterministic order. Emission/splitting contract failures continue
  to propagate `MigrationError`. Filesystem failures are mapped to
  `MigrationError`; never return a plan as though writing succeeded.
- No SQL parsing, database access, filesystem access, or risk policy belongs in
  rendering. No new dependency is needed.

## Tests and implementation split

Tests are unit-only; no Docker or live database is required.

- Generation/model tests: injected clock and ID yield stable plan metadata;
  ordering is deterministic; one assessment and ID per delta; empty input
  passes and has `None` overall risk; gate errors include all offending levels
  and prove emission was not called; accepted plans use `default_handlers()` and
  `split_units()`; unit risks and delta IDs match statement provenance; optional
  fingerprints survive unchanged.
- Renderer snapshot tests: exact UTF-8/LF bytes and final newline for all five
  artifacts; psql-correct transaction wrappers including non-transactional
  statements outside wrappers; statement offsets and unit/up checksums; stable
  manifest order; `deltas.json` equals `pgsd diff` JSON; down file contains
  comments only and one irreversible entry per delta.
- Port/adapter `tmp_path` tests: expected layout and returned path; no overwrite
  of existing bundle; checksums recalculate; inject failures during file write,
  `fsync`, and rename; assert typed `MigrationError`, no partial final
  directory, and temp cleanup where possible. Run rename/fsync cases on Windows
  CI as well as POSIX.
- CLI wiring test under P3-CLI-01: `compare_schemas` result flows through
  `generate_migration` and the injected writer; `--max-risk` reaches the gate;
  errors use the existing stderr/exit-code boundary and expose no credentials.

Ordered implementation slices (no more than three production source files per
slice; tests/snapshots are additional):

1. **Plan model + generation:** `application/migration/model.py` and
   `application/migration/generate.py`. Done when model invariants, ordering,
   gate-before-emission, deterministic injection, risks, unit grouping, and
   empty plans have unit coverage.
2. **Pure bundle rendering:** `application/migration/render.py`. Done when all
   five outputs are snapshot-tested, SQL is psql-correct, offsets/checksums
   agree byte-for-byte, and rollback contains no executable SQL.
3. **Port relocation:** `domain/ports.py`, `domain/__init__.py`, and
   `application/migration/ports.py`. Done when `MigrationWriter` references the
   application plan without a domain-to-application import and existing domain
   port exports/tests are updated.
4. **Filesystem adapter:** `infrastructure/fs/migration_writer.py` (plus its
   package initializer only if needed). Done when atomic success, collision,
   write/fsync/rename failure, typed errors, and cleanup are covered by
   `tmp_path` tests on supported platforms.
5. **P3-CLI-01 composition point:** add the generate command and register it in
   `presentation/cli/main.py` (at most two production files, plus tests). It
   calls `compare_schemas`, then the application use case, then the injected
   writer; do not put ordering, risk policy, SQL rendering, or filesystem code
   in the command.

## Open questions

1. **Fingerprint and display-label source:** `compare_schemas` returns only a
   `DeltaSet`, and no canonical snapshot fingerprint exists. Recommend nullable
   fingerprints supplied by a future caller with a documented canonical hash;
   never substitute database URLs. Until then, TUI may display `unknown`.
2. **Slug source and collisions:** P3-OUT does not define a CLI name option.
   Recommend optional `--name` in P3-CLI-01, defaulting to `diff`; preserve
   strict no-overwrite behavior and report collisions rather than adding a
   random suffix.
3. **History after apply:** an immutable manifest cannot truthfully contain
   eventual status, duration, or timeline. Recommend P3-APPLY-01 store those in
   separate run-history records and let P4-TUI-07 combine records with bundle
   manifests.

## Review decisions (2026-10-24)

- **Open questions 1–3:** accepted as recommended (nullable caller-supplied
  fingerprints; optional `--name` slug defaulting to `diff`, strict
  no-overwrite; run history stored separately by P3-APPLY-01).
- **Session settings in `up.sql`:** `quote_literal` assumes
  `standard_conforming_strings = on`. Insert `SET standard_conforming_strings = on;`
  as the first non-comment line, outside any unit and before unit 0; it is not
  part of any unit range or unit checksum (it is covered by
  `up_sql_sha256`). P3-APPLY-01 must set the same on its session. Lock and
  statement timeouts stay applier options, not hard-coded in `up.sql`.
- **README warning:** state that a failed `CREATE INDEX CONCURRENTLY` leaves an
  INVALID index that must be dropped before retrying, and that
  non-transactional units cannot be rolled back.

