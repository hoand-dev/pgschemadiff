# P3-APPLY-01 — PostgreSQL bundle applier + `pgsd apply` design

**Status:** Approved with review decisions · **Date:** 2026-10-24

## Goal

Safely validate and apply P3-OUT-01 bundles against PostgreSQL, preserving
transaction-unit boundaries, fail-fast behavior, redaction, resumability, and
the immutable bundle contract. `down.sql` remains annotation-only and is never
executed.

## Decisions

### 1. Layering and responsibilities

- Add a pure application bundle model/parser/validator in
  `application/migration/bundle.py`. It accepts manifest and `up.sql` bytes and
  returns a validated immutable bundle; it performs no filesystem or database
  IO and does not parse SQL.
- Keep file IO behind an application-owned `BundleReader` port, implemented by
  `infrastructure/fs/bundle_reader.py`. It reads only `manifest.json` and
  `up.sql`; other bundle files are not needed to execute, and `down.sql` is
  never read by the applier.
- Add an async `MigrationExecutor` port in
  `application/migration/ports.py`, implemented by
  `infrastructure/postgres/applier.py`. The adapter owns psycopg connection
  setup, advisory locks, history persistence, transaction/autocommit mechanics,
  and execution of already-validated statement strings.
- The application `apply_migration` use case validates policy, loads history,
  chooses the resume point, iterates units/statements, emits progress, and
  stops on the first error. The executor applies one unit at a time and returns
  a safe failure containing unit index, statement index, error class, and
  optional SQLSTATE. Neither layer tokenizes or interprets SQL.
- `presentation/cli/commands/apply.py` composes the reader, validator, use case,
  and PostgreSQL adapter, following the existing `diff` command's generic
  connection-error boundary. Keep `domain/` unchanged; add no dependency.

### 2. Bundle v1 validation

Use the P3-OUT-01 manifest field names and meanings exactly; do not infer
boundaries from comments, semicolons, or SQL syntax.

- Parse strict UTF-8 JSON; reject duplicate keys, unsupported
  `format_version`, missing/extra v1 fields, invalid field types, and malformed
  SHA-256 values. Version 1 requires the existing top-level fields, ordered
  assessments/units, and `checksums.up_sql_sha256`.
- Verify `checksums.up_sql_sha256` against the complete raw `up.sql` bytes.
  Require canonical UTF-8/LF text with one final LF, as emitted by
  `render.py`.
- Validate zero-based contiguous unit indexes, `transactional` booleans, known
  risk values, and positive one-based inclusive line ranges in bounds. Statement
  ranges must be ordered, non-overlapping, contained by their unit, and each
  unit range must span its first through last statement. Every statement
  `delta_id` must exist in assessments; unit `delta_ids` must equal the ordered
  unique statement delta IDs; all assessments must be represented. Recompute
  unit and overall max risk from linked assessments and reject inconsistencies.
- Re-derive each statement's bytes from its `up.sql` line range, append exactly
  one LF, concatenate statements in order, and verify the unit's
  `sql_sha256`. This matches `render.py`: SQL ranges exclude comments,
  transaction wrappers, and the standalone `;` terminator line. Require every
  non-transactional unit to contain exactly one statement, per P3-TX-01.
- Execute only extracted statement ranges. The applier does not execute the
  header `SET` or `BEGIN`/`COMMIT` lines from `up.sql`; it applies equivalent
  session settings and transaction boundaries itself. Hashes detect accidental
  corruption, not authorship: only apply bundles from trusted sources.

### 3. Session setup and qualification

- Pin one psycopg async connection for the entire real run (reuse `Pool` with a
  single connection and keep it acquired). Configure autocommit for standalone
  non-transactional statements; use explicit transaction contexts for
  transactional units.
- Set `standard_conforming_strings = on`, `lock_timeout` (default `5s`),
  `statement_timeout` (default `0`, unlimited), fixed
  `application_name = 'pgschemadiff apply'`, and `search_path = pg_catalog` at
  session scope. Validate timeout values before applying them; use bound
  `set_config` values rather than interpolating user input.
- Keep `search_path` at `pg_catalog`: current emitters quote and qualify user
  objects; the P3-SQL contract requires schema-qualified raw index definitions
  and structured qualified FK references. TD-INSPECT-03 is complete and runs
  deparsers with `search_path = pg_catalog`, so catalog expressions qualify
  user objects while built-ins remain resolvable in `pg_catalog`. History SQL
  must also qualify its own schema and table names.
- Session settings disappear when the pinned connection closes. Never put a
  database URL or bundle-controlled value in `application_name`.

### 4. Unit execution and failure semantics

- Apply units sequentially in manifest order. A transactional unit runs all its
  statements in one `BEGIN`/`COMMIT`; on any statement error, roll back that
  whole unit. A non-transactional unit runs its single statement in autocommit.
- Stop at the first failure; never start a later statement or unit. Report the
  zero-based unit index, statement index, `delta_id`, line range, safe error
  class, and SQLSTATE when available. Do not include driver exception text or
  SQL in the error report.
- For a failed non-transactional index operation, use validated manifest delta
  metadata, not SQL parsing, to identify the index case. Clearly warn that
  PostgreSQL may leave an INVALID index; require operator inspection/manual
  cleanup before retry. Never automatically drop an index or other object.
- Earlier committed units remain applied after failure or cancellation. A
  cancellation rolls back only the currently open transactional unit; it does
  not undo prior units or non-transactional work. Do not describe cancellation
  as a full rollback.

### 5. History, partial apply, and resume

Choose target-database history over a local JSON log: it is visible to every
client applying to that target, survives local-machine loss, and allows
transactional DDL and its completion marker to commit atomically.

- On first real apply, after acquiring the advisory lock, create reserved schema
  `pgschemadiff` and tables `migration_runs` and `migration_units` in a separate
  transaction. Create one run row and pending unit rows before executing bundle
  SQL. If the schema exists without the expected history layout, fail closed;
  do not adopt arbitrary objects.
- `migration_runs` stores bundle `id`, `up_sql_sha256`, status, start/finish
  timestamps, and safe run-level error class/SQLSTATE. `migration_units` stores
  bundle id, unit index, unit checksum, transaction mode, status, start/finish
  timestamps, failed statement index, and safe error class/SQLSTATE. Use
  `running`, `applied`, `failed`, and `cancelled` run states; unit states are
  `pending`, `running`, `applied`, and `failed`. Store no SQL text, bound values,
  exception messages, connection URLs, or credentials.
- For a transactional unit, update its `applied` marker inside the same
  transaction as its DDL. If it fails, the DDL and marker roll back together;
  record failure in a fresh transaction. For a non-transactional unit, commit a
  `running` marker before executing, then mark `applied` immediately after
  success. A known failure is recorded as `failed` after execution.
- A repeated apply with the same bundle id and matching `up_sql_sha256` and all
  unit checksums resumes at the first non-applied unit. A fully applied bundle
  is an explicit no-op error. A bundle-id or checksum mismatch, corrupt/non-
  prefix history, or changed unit layout fails before bundle SQL runs.
- A failed transactional unit is safe to retry because its transaction rolled
  back. A failed non-transactional unit may need manual repair first; the next
  explicit `pgsd apply` retries that unit but never auto-drops its object. If a
  non-transactional unit is still `running` after process/connection loss, its
  outcome is indeterminate: refuse automatic resume and require operator
  inspection. This covers the crash window between successful DDL and recording
  completion.
- Reserve `pgschemadiff` for this metadata and exclude it from normal schema
  inspection so history tables do not appear as application drift. If a user
  schema already uses this reserved name, applying must fail rather than
  silently commandeer it.
- For the later `HistoryView` wiring, project run/unit statuses and timestamps
  into the timeline and join bundle metadata for risk, delta count, and
  fingerprints when available. Do not persist source/target URLs or author;
  show unknown labels when no safe labels exist. Dry runs are transient and do
  not create history records in MVP.

### 6. Concurrency safety

- Acquire a session-level `pg_advisory_lock` on one fixed two-int key for the
  target database, before history bootstrap, and hold it through run completion.
  A global per-database key is safer than a bundle-id key: two different
  bundles can still touch the same objects. Release in `finally`; connection
  closure also releases it. Bound lock waiting with `lock_timeout` and report a
  concurrent apply without exposing connection details.
- PostgreSQL scopes advisory locks to a database. This serializes pgsd applies
  to that database, not unrelated SQL clients or applies to other databases.

### 7. Drift preflight

Defer target drift checking. P3-OUT-01 fingerprints are nullable and no stable
canonical snapshot fingerprint exists today; a `null` fingerprint is not
evidence of a match. Do not re-inspect the target or block apply on fingerprints
in MVP. Revisit an opt-in drift check once a canonical fingerprint is defined;
use a consistent inspection snapshot per ADR-0012.

### 8. CLI and safety boundary

```text
pgsd apply BUNDLE_DIR DB_URL [--lock-timeout 5s]
                     [--statement-timeout 0] [--dry-run] [--yes]
```

- Defaults: `--lock-timeout 5s`; `--statement-timeout 0` (unlimited).
  Destructive means a unit `max_risk >= DESTRUCTIVE`; require an interactive
  confirmation unless `--yes` is given, and require `--yes` when stdin is
  non-interactive. The application use case also requires explicit destructive
  approval so non-CLI callers cannot bypass the gate. `BLOCKED` is always
  rejected; `--yes` only bypasses the confirmation prompt.
- `--dry-run` validates the bundle first, then verifies target connectivity
  with a harmless `SELECT 1` and prints unit index, transaction mode, risk,
  statement count, delta IDs, and ranges. It executes no bundle SQL, takes no
  advisory lock, and creates/updates no history. It does not prove permissions
  or future execution success. Show destructive-risk warnings without asking
  for confirmation because no migration SQL runs.
- Exit codes: `0` applied/resumed successfully or dry-run complete; `1` bundle
  file IO or database connection failure; `2` bundle/format/checksum validation,
  invalid option, or declined/missing pre-execution risk confirmation; `3`
  execution/history/lock failure, already-applied bundle, or indeterminate
  resume state.
- Redact like `diff`: never print DB URLs, driver exception messages, SQL,
  parameters, or credentials. Print generic connection/IO categories; for
  execution failures print unit/statement/delta identity and safe error
  class/SQLSTATE only.

### 9. Progress events and cancellation

The application use case accepts a typed event callback independent of Textual
and Typer. Use immutable event records for `RunStarted`, `UnitStarted`,
`StatementStarted`, `StatementFinished`, `UnitFinished`, `UnitFailed`,
`RunFinished`, and `RunCancelled`. Include unit/statement indexes, counts,
`delta_id`, line ranges, elapsed time, and safe error metadata as applicable;
never include SQL or URLs. CLI formats the same events as concise progress/log
lines. The TUI worker can consume them for per-unit/per-statement progress and
live log output, and cancel the running task. Cancellation stops at a safe
statement boundary where possible, rolls back the open transaction, records
partial status, and releases the session lock; an in-flight non-transactional
statement may have an indeterminate outcome and follows the resume rule above.

### 10. Tests and ordered implementation split

- Pure bundle tests: valid P3-OUT-01 fixture; strict UTF-8/duplicate JSON keys;
  unknown version; malformed/missing fields; altered whole-file or unit hash;
  invalid/overlapping/out-of-bounds ranges; inconsistent delta/risk metadata;
  and exact range re-derivation. Assert the validator never parses SQL.
- Application tests with a fake executor: ordered units/statements and events;
  transactional/non-transactional metadata; exact failed statement; stop at
  first failure; transactional rollback/retry; checksum mismatch; fully-applied
  error; non-transactional `running` refusal; cancellation and destructive gate.
- Adapter tests: session settings, one pinned connection, advisory lock cleanup,
  history bootstrap/collision, transactional marker atomicity, non-transactional
  `running`/`applied` transitions, and redaction. Include a failed concurrent
  index case proving no automatic drop.
- Add one PG18 Testcontainers round-trip integration test: create separate
  source and target databases with a small supported schema difference; inspect
  and generate/write a bundle; apply it to target; re-inspect and assert no
  remaining application-schema delta. Exercise at least one transactional unit
  and one `CREATE INDEX CONCURRENTLY` unit; exclude reserved `pgschemadiff`
  history metadata from schema comparison. This seeds P3-TEST-01.

Ordered slices (maximum three production source files per slice; tests may add
files):

1. **Pure bundle contract:** `application/migration/bundle.py` and
   `application/migration/ports.py`. Done when valid v1 bundles round-trip from
   bytes, all checksum/range/schema failures are covered, and no IO/SQL parser
   or infrastructure imports enter application code.
2. **Use-case orchestration:** `application/migration/apply.py`. Done when fake
   executor tests prove risk approval, resume selection, typed event ordering,
   cancellation, and stop-on-first-failure behavior.
3. **PostgreSQL execution/history:**
   `infrastructure/postgres/applier.py`, `infrastructure/postgres/inspector.py`,
   and `infrastructure/postgres/catalog/schemas.sql`. Done when real adapter
   tests prove session/lock behavior, unit transaction semantics, atomic history
   markers, fail-closed resume, and exclusion of reserved history schema.
4. **Filesystem and CLI wiring:** `infrastructure/fs/bundle_reader.py`,
   `presentation/cli/commands/apply.py`, and `presentation/cli/main.py`. Done
   when CLI flags, confirmation, exit codes, redaction, dry-run, and event
   printing are tested without editing the concurrently owned generate command.
5. **Round-trip acceptance:** PG18 Testcontainers integration test for
   P3-TEST-01. Done when generated bundle applies cleanly and the re-inspected
   application schemas match.

## Open questions

1. **Canonical fingerprint/drift policy:** `target_fingerprint` is currently
   nullable and not canonical. Recommend defer drift checks until the fingerprint
   contract is stable; then add an explicit opt-in check using ADR-0012 snapshot
   consistency.
2. **Reserved history namespace:** reserve exact schema `pgschemadiff`, hide it
   from normal inspection, and fail on an incompatible pre-existing schema.
   Confirm maintainers accept this reserved-name contract before implementation.
3. **Stale non-transactional `running` rows:** MVP refuses automatic replay and
   requires manual inspection because DDL may have succeeded before history
   commit. Recommend defer a dedicated history-repair command; do not weaken
   fail-closed behavior to improve resume convenience.
4. **Bundle authenticity:** v1 SHA-256 fields are unkeyed integrity checks, not
   signatures; a party able to edit SQL can also recompute hashes and risk
   metadata. Recommend MVP trust local bundle provenance and defer signatures
   until bundles cross an untrusted distribution boundary.

## Review decisions (2026-10-24)

- Open questions 1–4 accepted as recommended: drift checks deferred; schema
  `pgschemadiff` reserved and excluded from inspection (fail on an incompatible
  existing schema); stale non-transactional `running` rows stay fail-closed with
  no repair command in MVP; bundles are trusted local artifacts (no signatures).
- Manifest risk values are bundle-controlled. The destructive-approval gate
  uses them (consistent with the trust decision); revisit together with
  signatures.

