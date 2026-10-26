# P4-TUI-WIRING — Wire the Textual TUI to real use cases

**Status:** Proposed for review · **Date:** 2026-10-26

## Goal

Wire the seven views under `presentation/tui/` to the existing inspection,
comparison, migration-generation, application, and history capabilities. Keep
the TUI a presentation adapter: it owns no schema or migration policy and
reuses the same application use cases and infrastructure adapters as the CLI.

## Verified baseline

- `docs/ui-design.md` defines seven screens, but each view and the main chrome
  currently imports data from `presentation/tui/_mock.py`. The app also imports
  `ai_for()` from that module. `_mock.py` includes static URLs, SQL, lock/time
  estimates, preflight claims, fake history, AI copy, and a TOML preview.
- The installed `pgsd` entry point uses `presentation/cli/main.py`; its command
  modules construct `Pool`, `PgCatalogInspector`, `FilesystemMigrationWriter`,
  `FilesystemBundleReader`, and `open_executor` around application use cases.
  Their synchronous `*_cmd` functions use `asyncio.run()` and print/exit, so
  those functions are not TUI APIs. `diff.compare_urls()` is an async
  composition helper, but returns only `DeltaSet`.
- `compare_schemas()` inspects each endpoint once, then returns only the
  ordered `DeltaSet`. The TUI needs the inspected `Database` snapshots too.
  Add a small application result/use case returning source snapshot, target
  snapshot, and deltas; preserve `compare_schemas()`'s existing return contract
  for CLI callers.
- `Database` contains schemas, extensions, object definitions, and an optional
  `server_version`. `PgCatalogInspector._assemble()` currently creates it with
  `name="inspected"` and does not set `server_version`. It does not collect
  database size, row counts, free space, replica lag, or operation duration
  estimates.
- `classify_risk()` returns a static `RiskAssessment(delta, level, reason)`; it
  does not inspect SQL, transaction mode, or live database state. The generator
  supplies context for created tables and resolved view dependencies. The TUI
  must reuse this classification context rather than infer locks from risk.
- `MigrationPlan` contains ordered delta assessments and transaction units.
  `render_bundle()` produces `up.sql`, `down.sql`, checksums, and metadata;
  `down.sql` is comments/irreversibility annotations only, not rollback SQL.
  `FilesystemMigrationWriter.write()` publishes a complete bundle below an
  existing parent directory and never overwrites an existing bundle.
- `apply_migration()` already emits typed run/unit/statement events. Its
  `MigrationExecutor.apply_unit()` receives a `StatementObserver`, and the
  PostgreSQL executor calls it immediately before and after each statement.
  No progress-port addition is needed for ApplyView.
- Apply history is persisted in target-database tables
  `pgschemadiff.migration_runs` and `pgschemadiff.migration_units`. The schema
  stores status, checksums, timestamps, unit transaction mode, and safe failure
  metadata; there is no list-history port, author/source labels, snapshot data,
  or dry-run history. The task table's “manifest store” wording does not match
  this implementation.
- `ProfileLoader` reads/writes `Profile` YAML at a caller-supplied path. It has
  no default path. `Profile` carries name, source/target host/port/database/user/
  password, schemas, ignore-pattern strings, and mode. Its `display()` omits the
  password but still returns a URL; `dsn()` includes the password. The current
  diff `IgnoreRules` uses exact object/attribute references, not glob patterns.
- `presentation/tui/app.py` currently logs the full command-palette input.
  `presentation/cli/commands/diff.py` and `apply.py` use generic redacted
  database errors; `inspect.py` currently prints `str(exc)` on inspection
  failure. TUI error handling must not copy that inspect exception behavior.
- `src/pgschemadiff/__main__.py` still launches the older
  `presentation/app.py` / `presentation/screens/` flow. `pgsd` and
  `pgsd tui` launch the newer `presentation/tui.PgsdApp`. Thus the older flow is
  legacy, but not currently unreachable. Keep its tracked files in place; route
  `python -m pgschemadiff` to the supported TUI in place and leave old screens
  inert rather than deleting or renaming them.
- Textual `App.run_test()`/Pilot is already used in `tests/unit/test_tui.py`.
  `pytest-textual-snapshot` is not declared in `pyproject.toml`; no new test or
  runtime dependency is needed.

**Unverified:** No user profile file or live database was read during this
design task. Actual credentials, network behavior, server permissions, and
deployment-specific timeout needs remain environment-dependent.

## Decisions

### 1. Composition, state, and layer boundaries

1. Make `presentation/composition.py` the shared presentation composition
   seam. It resolves the profile path, constructs `ProfileLoader`, creates
   source/target `Pool` + `PgCatalogInspector` scopes, and supplies the
   stateless writer/reader plus executor/history-reader factories. Reuse the
   existing infrastructure classes and application functions. Refactor the
   CLI's async resource helper(s) to use the same composition seam; do not call
   the CLI `*_cmd` functions from Textual because they own `asyncio.run()`,
   terminal output, and process exits.
2. Preserve the existing profile-path precedence from `__main__.py` when
   centralizing it: `PGSCHEMADIFF_CONFIG`, existing `./config/profiles.yaml`,
   `$XDG_CONFIG_HOME/pgschemadiff/profiles.yaml`, then
   `~/.config/pgschemadiff/profiles.yaml`. `PgsdApp` accepts injected
   dependencies so `run_test()` can use fakes and opening the app does not
   connect to PostgreSQL.
3. Add an application comparison result containing `source: Database`,
   `target: Database`, and `deltas: DeltaSet`. Implement it by extracting the
   current `compare_schemas()` flow; keep `compare_schemas()` as a compatibility
   wrapper returning only `.deltas`. The TUI then inspects each endpoint once,
   retains the snapshots, and uses the same diff engine as CLI.
4. Add a presentation-layer `TuiSession` (not a domain model) as the one
   current-workspace state holder: selected `Profile` (and its source/target
   `ConnectionInfo`s), loaded profiles, last source/target `Database`,
   `DeltaSet`, assessments, selected delta, `MigrationPlan`, rendered/validated
   bundle and path, `ApplyResult`, current apply events, and target history.
   Changing profile, schemas, or rename input invalidates comparison, plan,
   bundle, and apply state. Views do not retain independent mock copies.
5. Introduce presentation `view_models.py` dataclasses for rendered rows/cards.
   Keep raw domain/application objects in `TuiSession`; map them to display
   values in presentation. Do not promote `_mock.py` dataclasses into domain or
   application APIs. Keep `_mock.py` physically present for isolated demo/test
   fixtures only; it must not be imported by live TUI code or used as an
   automatic fallback when profiles/database are unavailable.
6. View actions bubble as typed Textual messages to `PgsdApp`; the app starts
   work and commits results to the session on the UI loop. It then updates
   reactive view state or sends typed session/progress messages to affected
   widgets. The session/controller never owns widgets or Rich markup.

Import-linter already permits `presentation → infrastructure → application →
domain` and presentation importing any inner layer. Therefore composition may
import infrastructure adapters, application use cases/ports, and domain types.
Views may import presentation view models and application/domain result types,
but must not construct psycopg objects or implement diff/risk/migration policy.
`application/` must not import presentation, infrastructure, psycopg, or
psycopg_pool; `domain/` stays pure and cannot import any higher layer, Textual,
asyncio, or IO libraries.

### 2. Async work, progress, cancellation, and errors

- Every database operation (connect/test, compare, history read, dry-run probe,
  apply) runs in an async Textual `run_worker()` with an explicit group and
  `exclusive=True`. Use a read group for connect/compare/history so a newer
  profile request cancels stale reads; use a separate apply group and disable
  profile changes/read actions while apply is active. Do not start concurrent
  apply and read workers against the selected target.
- Await the application async functions in the worker; never call
  `asyncio.run()` inside Textual. Do not mutate widgets from worker callbacks.
  Synchronous rendering, bundle validation, and filesystem writing use
  `asyncio.to_thread()` so large bundles or slow filesystems do not stall the
  event loop.
- Keep CLI-compatible connection defaults: inspector pool `open_timeout=5s`
  and default pool acquire timeout `30s`; apply `lock_timeout=5s` and
  `statement_timeout=0` (unlimited) unless the user changes explicit Apply
  options. The existing mock's `30min` statement timeout is not a real default.
  Apply options are passed to `open_executor()`; no global worker timeout may
  silently interrupt a statement. User cancellation remains available.
- Cancelling a read is safe and clears its loading state. Cancelling apply calls
  `Worker.cancel()`, propagates `CancelledError` into `apply_migration()`, and
  lets its existing `RunCancelled`/`finish_run("cancelled")` handling persist
  status and release the lock. A cancelled transactional unit rolls back, but
  previously committed units remain applied; an in-flight non-transactional
  statement may have an indeterminate outcome. Never label this “rollback”.
- Drive progress from existing `RunStarted`, `UnitStarted`,
  `StatementStarted`, `StatementFinished`, `UnitFinished`, `UnitFailed`,
  `RunFinished`, and `RunCancelled` events. Show unit/statement indexes,
  elapsed time, delta ID, and safe error class/SQLSTATE. Existing
  `StatementObserver` already exposes statement boundaries; add no new
  applier port for progress.
- Map connection, inspection, diff, bundle, apply, and unknown errors to short
  generic UI messages. Never surface raw `psycopg_error` text, chained
  exceptions, DSNs, passwords, SQL, parameters, or raw profile validation
  errors in error messages or logs. `RiskGateError` and safe `ApplyResult`
  failure metadata may be shown after escaping markup. Log only an allow-listed
  command verb/event, never the full palette text or arguments. Do not accept
  raw DSNs in the command palette.

### 3. View models and field mapping

Fields below are from the current rendered views and their mock records; where
`docs/ui-design.md` describes a field not currently rendered, that difference
is called out. “N/A” means the UI explicitly labels the value unavailable;
“hide” means remove that mock-only control/column rather than leave fake data.

#### Connection (`P4-TUI-02`)

| Current field | Real source / decision |
|---|---|
| Source/target label | `Profile.name`; safe display text. |
| Connection URL/string | Hide. Render host, port, database, and user as separate fields; never render even a password-redacted URL because the requirement forbids rendering DSNs. |
| Host, database, role | `ConnectionInfo.host`, `.database`, `.user`; port may be shown as a separate real field. Escape profile-controlled text. |
| Schemas | `Profile.schemas`; `[]` is passed as `None` (all schemas), matching CLI semantics. |
| SSL mode | N/A; `ConnectionInfo` has no SSL field. |
| Server version | N/A for current inspector: `Database.server_version` exists but `_assemble()` leaves it unset. |
| Latency | N/A; no ping latency is persisted. Do not substitute mock milliseconds. |
| Table count | Derive `len(Database.all_tables())` from the last snapshot. |
| Database size | N/A; inspector does not collect it. |
| Online/target “+N tables” chips | Online only after successful inspect; table delta derives from the two snapshots. No optimistic online state. |
| Compare options: include schemas | Real, read-only `Profile.schemas`. |
| Exclude tables | Do not claim `ignore_patterns` are active: strings/globs cannot be passed to exact-reference `IgnoreRules`. If non-empty, show “unsupported filters” and block compare until cleared or a proper mapping exists. |
| Include data | Hide; only schema comparison exists. Show profile mode `schema-only` if useful; reject unsupported modes. |
| Owner roles, storage params, extensions, generated columns, comments, case sensitivity | Not user-selectable comparison options. Show only as fixed behavior if useful; otherwise hide the mock option controls. Existing domain/comparators determine comparisons. |
| Saved profile name and route | Derive from `Profile.name` and source/target database names. |
| Last used and owner | Hide; `Profile` has neither field. |
| Current profile marker | Derive from selected `Profile`; never from mock `current=True`. |
| Test both | Real async inspect/compare worker. |
| Save profile | Hide until an actual profile editor exists. `ProfileLoader.save()` serializes passwords into YAML, so do not add an implicit save path. |

Use `ProfileLoader` only through injected composition dependencies. Its YAML
validation errors can contain input values; report a generic profile-load error
instead of exposing its exception text.

#### Overview (`P4-TUI-03`)

| Current field | Real source / decision |
|---|---|
| Profile breadcrumb / inspected time | Profile name plus local timestamp captured by the completed worker; label it “inspected”, not “generated”. |
| Added / modified / dropped counts | Derive from each ordered delta's `op`; group modify/replace/rename operations consistently. |
| Conflict count | Not represented by `DeltaSet`; replace with a `blocked` count from risk assessments. `BLOCKED` is not a conflict. |
| Card delta text/object-type counts | Derive only from typed deltas and target kinds. No fabricated row counts or “data loss” quantities. |
| Table row ID, operation, kind, schema, object | Operation from `delta.op`; kind/qualified name/schema from `delta.target`; use stable ordinal until a `MigrationPlan` supplies bundle-local `d0001…` IDs. |
| Detail / risk | Detail from escaped typed delta fields. Risk and reason from the application's contextual risk assessment; reuse the generator's created-table/view-dependency context through a small application helper, not a TUI reimplementation. |
| Lock and estimated time | The UI-design contract mentions these columns and `_mock.ChangeRow` has them, but current `OverviewView` does not render them. If added, show N/A; no risk-to-lock or invented duration heuristic. |
| Click row → Diff | Select the corresponding real delta by identity/key and open Diff. |
| AI review cards/hints | Hide; no AI application service or CLI capability exists. |
| Dependency graph | Hide the static mock graph. Current implementation is ASCII, not the SVG described in design; there is no generic application graph result. Revisit only when an application-owned edge model exists. |

#### Diff (`P4-TUI-04`)

| Current field | Real source / decision |
|---|---|
| Type tag, qualified name, breadcrumb | `delta.target.kind`, its qualified name, and selected profile. |
| Summary | Derive a concise op/kind label; otherwise show changed typed fields. Do not invent semantic summaries. |
| Side-by-side source/target SQL | No generic DDL renderer exists for both snapshots; `SqlEmitter` emits forward migration statements only. Keep side mode as before/after domain-object data from the retained snapshots; show “absent” for create/drop sides. Label it as definitions, not SQL. |
| Inline lines/signs/line numbers | Mock `DiffLine` has no real source. Render the actual typed delta fields; do not fabricate line numbers or a unified SQL diff. |
| Tree mode | Render nested fields from the typed Pydantic delta/object data. |
| Forward DDL | Show only statements from the current `MigrationPlan` matched to this delta; otherwise show “Generate a plan to preview SQL”. |
| Rollback snippet / “tested” badge | Never show executable rollback. If a plan exists, show its `down.sql` irreversibility annotation and warning; otherwise N/A. |
| Jump chips | Derive from changed targets in the actual `DeltaSet`; no `_mock.DIFFS` fallback. |
| Conflict flag | Hide. There is no conflict delta type; show the true risk assessment (including `BLOCKED`) instead. |
| Accept / skip | Hide or disable. Current handlers only notify and do not alter the set; CLI generation has no per-delta accept/skip API. |
| AI action | Hide; no AI service exists. |

#### Migration (`P4-TUI-05`)

| Current field | Real source / decision |
|---|---|
| Header timestamp, line/change counts | `MigrationPlan.created_at`, `len(delta_set)`, and rendered `up.sql` lines. Do not show “conflicts skipped”. |
| Forward SQL | Pure `render_bundle(plan)` output / ordered transaction-unit statements. Never include source/target URLs in SQL headers or UI. |
| Save `.sql` | Rename to “Save bundle”: `FilesystemMigrationWriter` writes all five bundle files under a user-selected existing parent directory. Do not bypass bundle checksums or emit an ad-hoc SQL file. |
| Generate action / max risk | Add explicit Generate action using `generate_migration()` and default `RiskLevel.DANGEROUS`. Selecting `DESTRUCTIVE` is an explicit generation opt-in; `BLOCKED` always fails closed. No bundle SQL/files on risk-gate failure. |
| Execution plan statement kind/order | Derive from `MigrationPlan.units`, statements, and linked delta IDs. Show transactional/non-transactional unit mode and risk/reason. |
| Estimated duration / downtime | N/A; no estimator or live row counts. Hide mock values. |
| Lock estimates, lock mode, row counts | Replace the mock table with an explicit “N/A — no lock/row-count estimator” note. Risk is not a lock estimate. |
| Migration toggles | Hide fake toggles. Unit boundaries and SQL are determined by current emitters/splitter; there are no UI settings for archive/data/conflict behavior. |
| `up.sql` / `down.sql` tabs | `up.sql` is executable generated content; `down.sql` is annotations only per P3-OUT-01. Label the latter “Rollback notes — not executable”. |
| Line count, file size, checksum | Derive from rendered bundle bytes/manifest. |
| AI review | Hide. |
| Apply button | Open Apply only when a validated, written bundle and target profile are available. |

The plan is in-memory first. Applying uses the exact CLI path: writer publishes
the bundle, `FilesystemBundleReader` reads `manifest.json` + `up.sql`,
`load_bundle()` validates it, then `open_executor()` and `apply_migration()`
apply it. The writer requires an existing parent directory; ask for/validate
one and report a safe error rather than silently creating it or writing
somewhere unexpected.

#### Apply (`P4-TUI-06`)

| Current field | Real source / decision |
|---|---|
| Target, delta count, estimated duration | Target profile label and bundle delta count; estimated duration N/A. |
| Connection ping | Real connectivity check (`SELECT 1`) in dry-run; a real apply connection is established by `open_executor()`. |
| Lock budget | Actual `lock_timeout` option (default `5s`), not an estimate. |
| Replica lag, free space, active transaction scan, snapshot/backup | N/A; no such probes or backup port exist. Hide mock success claims or display N/A. |
| Advisory-lock status | Report acquired only after `open_executor()` succeeds; it acquires the lock before history bootstrap/run. Do not claim a preflight availability probe. |
| Conflict / destructive warning | Derived from validated bundle assessments/units. `BLOCKED` rejects; `DESTRUCTIVE` requires explicit approval. Never skip a blocked unit. |
| Command preview | Hide raw DB URLs. If retained, use placeholders only (`pgsd apply <bundle-dir> <target>`), not a copyable secret-bearing command. |
| Progress bar/steps | Drive from actual typed ApplyEvents. Count units/statements; no hard-coded step labels or success claims. |
| Log | Append local receipt time + safe event metadata. Never include SQL, parameters, credentials, or driver text. |
| Stop / pause / continue | Keep Cancel only. Pause/continue are unsupported. Label stop “Cancel run”; explain that earlier units remain applied and a non-transactional in-flight statement can be indeterminate. |
| Final result / rollback offered | Show `ApplyResult` status, applied/total units, resumed flag, elapsed time, and safe failure metadata. No automatic rollback or “rollback offered”; `down.sql` is annotation-only. |
| Dry run | Validate bundle and connectivity only; no advisory lock, bundle SQL, or history mutation, matching CLI. Show destructive warning without asking approval. |

Always show an explicit `ConfirmApplyModal` before a real apply, including for
non-destructive bundles. For `DESTRUCTIVE`, list the affected units and require
a distinct affirmative action; only then pass `approve_destructive=True` to
`apply_migration()`. For lower risks pass `False`. `BLOCKED` has no proceed
action. This is stricter than CLI's prompt behavior for low-risk runs, while
preserving its risk semantics: generation's `--max-risk` gate is separate from
apply's explicit destructive approval, and neither can override `BLOCKED`.

#### History (`P4-TUI-07`)

Add an application-owned `MigrationHistoryReader` port and
`list_migration_history()` use case, implemented by a read-only PostgreSQL
adapter for the currently selected target. Do not use `open_executor()` for
history reads: it acquires the migration advisory lock. Missing history schema
means an empty list; an incompatible existing layout means “history
unavailable”, not a guessed result. The port returns safe persisted run/unit
fields only.

| Current field | Real source / decision |
|---|---|
| Run ID / timestamp / status | `bundle_id`, `started_at`/`finished_at`, and `running`/`applied`/`failed`/`cancelled` from DB history. |
| Source/target route | Only current target profile/database is known. Do not attribute the current source to old runs; hide source route. |
| Author | N/A; not persisted. Hide. |
| Change count | N/A unless matching bundle metadata is explicitly available in the current session; do not infer from number of units. |
| Duration | Derive from persisted start/end timestamps; N/A if unfinished. Unit duration can be derived from unit timestamps. |
| Dry/pending/rolled-back chips | Dry runs are not persisted; pending/rolled-back are not run states. Map persisted `running`, `applied`, `failed`, `cancelled` only. |
| Checksum | Real `up_sql_sha256` from run history. |
| Snapshot, dump size, rollback availability | Hide/N/A; none is persisted and rollback SQL is unavailable. |
| Timeline | Unit status, timestamps, transaction mode, and safe failure index/class/SQLSTATE from `migration_units`. Statement-by-statement history is not persisted; current-session apply events may show live statements only. Never fabricate SQL or durations. |
| `:rollback <id>` | May select/show the run and its warning only. No rollback command/use case exists; never execute `down.sql`. |

This resolves the P4-TUI-07 “manifest store” wording in favor of the existing
target-database history schema specified by P3-APPLY-01.

#### Settings (`P4-TUI-08`)

| Current setting/preview | Real source / decision |
|---|---|
| Theme | `PgsdApp.theme` (`catppuccin-mocha`/`catppuccin-latte`), already reactive. |
| Font family/size, line spacing, line numbers, compact tree | No application settings source; hide. Terminal font is terminal-owned. |
| Keymap | “vim (fixed)” is derived from current hard-coded bindings. No configurable keymap/leader; hide editable value. |
| Leader, command timeout | No stored setting or 30s timeout; hide. |
| Confirm on apply/drop | Apply confirmation is always required by this design. No drop/profile-delete UI setting; hide toggles. |
| Mouse support, auto-save profile | No app setting or save flow; hide. |
| Default diff mode | Current `DiffView.mode` reactive value (default `side`); show read-only runtime state, not a persisted preference. |
| Wrap lines, auto rollback, shadow DB, auto archive | No corresponding behavior/config; hide. |
| Concurrent indexes / transaction wrapping | Emitter and transaction splitter determine actual statement/unit behavior; show generated unit facts, not toggles. |
| Statement/lock timeout | Actual Apply options: `0`/unlimited and `5s` defaults from CLI/applier; show as read-only defaults unless Apply options expose edits. Do not show mock `30min`. |
| AI enable/provider/upload/auto-apply | No AI or telemetry service/config; hide. |
| Anonymous reports/update channel | No source; hide. |
| Live `config.toml` preview | No TUI TOML preferences loader exists. Replace with a read-only **redacted current profile** summary from `ProfileLoader`: profile name, host/port/database/user, schemas, mode, and filter state. Never serialize or display password/DSN. Do not invent a TOML file or write credentials from this screen. |

#### Header, sidebar, statusbar, and AI modal

| Current field | Real source / decision |
|---|---|
| Header product/version | Package version; replace hard-coded `v0.0.0`. |
| NORMAL/COMMAND mode, active view, theme | Existing app/reactive state. |
| Source/target pills | Selected profile name/database labels only; no DSN. |
| “branch main” | Remove; no git branch source exists. |
| Sidebar schema/group/object labels | Derive from the two snapshots; use actual schemas and object kinds. |
| Sidebar status glyphs/badges | Derive from typed deltas and operation counts; no mock conflict status. |
| Statusbar selected object | Current selected delta/object key. |
| Statusbar change count | `len(DeltaSet)`; show blocked count only if computed by application assessments. Do not label blocked deltas as conflicts. |
| AI modal target/model/severity/change/title/body/patch/accept label | No real source for any field. Do not open the modal or call `ai_for()`; remove its actions from live views/help. Keep the source file only as legacy/demo code if retained. |
| Command bar hints/theme/help/quit | Existing UI state. Palette logging must omit command arguments. |

### 4. Security and risk gates

- Keep DSNs and passwords only in profile/worker memory. Never put them in
  widgets, markup, progress messages, logs, command history, exceptions,
  notifications, output bundle metadata, or test failure strings. Use explicit
  non-secret profile fields; do not call `ConnectionInfo.dsn()` for display.
- Do not log the full command palette input (current `PgsdApp` does). The
  palette accepts allow-listed commands/profile names, not URL arguments; log
  only an allow-listed verb. Map `PgCatalogInspector`/psycopg errors to generic
  categories because `InspectionError` currently chains driver text and the
  CLI inspect path currently prints it.
- Preserve distinct generation and apply gates. Generation defaults to
  `DANGEROUS`; `DESTRUCTIVE` requires the user to select a higher
  `max_risk`; `BLOCKED` is never generated. Real apply always has the modal;
  destructive approval becomes `approve_destructive=True`; `BLOCKED` is
  non-overridable. Dry-run does not execute migration SQL and needs no
  destructive approval.
- Trust only the validated bundle's existing manifest checksums/risk metadata,
  consistent with P3-APPLY-01's local-bundle trust decision. Do not infer SQL
  boundaries or weaken `load_bundle()` validation.

### 5. Command palette and CLI parity

Current `_dispatch_command()` is a hard-coded view/theme router; there is no
shared application command parser. `:apply` currently only opens a view,
`:rollback` only displays a hint, and `:diff <name>` currently ignores its
argument. Typer's CLI wrappers are not safe to call from the UI.

For this phase support a small explicit TUI command set: `:diff [qualified-name]`,
`:overview`/`:o`, `:migration`/`:m`, `:apply [--dry-run]`,
`:conn switch <profile>`, `:set bg=mocha|latte`, help, and quit. `:generate`
opens/starts the explicit Migration generation flow; it must still ask for
max-risk and output directory where needed. `:apply` opens the confirmation
flow and cannot bypass it. `:rollback <id>` may select a history record but
must say rollback is unavailable. Connection inspection starts from the
Connection view's profile action; raw DSNs are not palette arguments.

Defer full parser/flag parity with `pgsd inspect|diff|generate|apply`: no
application-level command parser exists today, and parser extraction is not
needed to share the use cases. Keep application use cases and adapters shared;
do not imply TUI-only options are accepted by CLI.

### 6. Testing

- Use existing `PgsdApp.run_test()`/Pilot with injected fake profiles,
  inspectors, writers/readers, history reader, and `MigrationExecutor`. Cover
  profile load/error redaction, empty and populated states, one inspection per
  endpoint, typed delta navigation, risk gates, generated bundle display,
  confirm/cancel/blocked behavior, ordered apply progress and cancellation,
  history empty/error/populated states, and settings with missing values.
- Assert no test opens a database for TUI behavior. Use `tmp_path` for bundle
  writing and fake ports for DB use cases. Include an assertion that a sentinel
  password/DSN never appears in rendered screen text, log messages, or surfaced
  error text.
- Do not add `pytest-textual-snapshot`; current `run_test()`/Pilot and normal
  assertions are sufficient. Use existing pytest/pytest-asyncio.
- No new TUI-specific PG18 integration suite is required. If the history reader
  port is added, extend/add a CI-only Testcontainers PG18 test: apply a bundle,
  list target history, verify ordered unit statuses/timestamps/checksum and
  safe failure metadata, verify empty/isolated target behavior, and assert no
  SQL/DSN/password is returned. Local Docker is unavailable per task
  environment; that integration check belongs in CI.

### 7. Ordered implementation slices

Every slice has at most three production files; tests may add files. Order
follows data dependency: obtain trusted connection/snapshots first, then present
and select deltas, then create a bundle before adding apply/history consumers.

1. **Shared composition + supported entrypoint** — `presentation/composition.py`
   (new), `presentation/cli/commands/tui.py`, `src/pgschemadiff/__main__.py`.
   **P4-TUI-02 foundation.** Done when profile-path resolution and injected
   factories are shared, app startup performs no DB IO, `pgsd` and
   `python -m pgschemadiff` launch the same TUI, and legacy screen files remain
   present but are not on the supported path.
2. **Retain snapshots without changing CLI contract** —
   `application/diff/compare_schemas.py`, `presentation/composition.py`,
   `presentation/cli/commands/diff.py`. **P4-TUI-02 foundation.** Done when
   source/target are each inspected once, the TUI receives snapshots + deltas,
   and existing CLI callers still receive `DeltaSet` with same error/output
   behavior.
3. **Session and Connection** — `presentation/tui/session.py` (new),
   `presentation/tui/app.py`, `presentation/tui/views/connection.py`.
   **P4-TUI-02.** Done when profiles load via injected `ProfileLoader`, profile
   selection/testing uses a worker, safe connection fields render, and
   unsupported ignore patterns fail closed.
4. **Chrome and Overview** — `presentation/tui/screens/main.py`,
   `presentation/tui/widgets/header.py`,
   `presentation/tui/widgets/statusbar.py`. **P4-TUI-03 foundation.** Done
   when tree/header/status values come from session/snapshots and no mock labels,
   branch, counts, or conflict numbers remain.
5. **Overview rows** — `presentation/tui/views/overview.py` plus any one
   application risk-assessment helper file (prefer reusing
   `application/migration/generate.py`; no TUI risk copy). **P4-TUI-03.** Done
   when cards/rows are derived from typed deltas and contextual risk, row click
   selects the matching real delta, AI/static graph are absent, and lock/time
   values are N/A or omitted.
6. **Diff** — `presentation/tui/views/diff.py`,
   `presentation/tui/views/_common.py`, `presentation/tui/app.py`.
   **P4-TUI-04.** Done when all three modes use real typed/snapshot data,
   forward SQL appears only from the generated plan, rollback is explicitly
   non-executable, and accept/skip/AI have no fake success handlers.
7. **Migration generation/rendering** — `presentation/tui/views/migration.py`,
   `presentation/tui/app.py`, `presentation/tui/view_models.py` (new).
   **P4-TUI-05.** Done when explicit risk selection calls
   `generate_migration()`, displayed SQL/checksum/size come from
   `render_bundle()`, save writes the atomic bundle through the existing writer,
   and no estimates or inverse SQL are fabricated.
8. **Apply and confirmation** — `presentation/tui/views/apply.py`,
   `presentation/tui/screens/confirm_apply.py` (new),
   `presentation/tui/app.py`. **P4-TUI-06.** Done when reader + validator +
   executor + `apply_migration()` are reused, every real run is explicitly
   confirmed, blocked/destructive rules match the application gate, real
   statement events drive progress, and cancellation reports partial-apply
   semantics.
9. **History read contract** — `application/migration/ports.py`,
   `application/migration/history.py` (new),
   `infrastructure/postgres/history.py` (new). **P4-TUI-07.** Done when the
   read-only port/use case returns validated safe run/unit records without
   acquiring the migration lock and fake-port tests cover absent/corrupt/error
   states.
10. **History view wiring** — `presentation/tui/views/history.py`,
    `presentation/composition.py`, `presentation/tui/app.py`. **P4-TUI-07.**
    Done when the selected target's DB history populates list/detail/unit
    timeline, unsupported author/snapshot/rollback fields are absent, and
    read failures are redacted.
11. **Settings/profile summary** — `presentation/tui/views/settings.py`,
    `presentation/tui/session.py`. **P4-TUI-08.** Done when current theme and
    actual runtime defaults are shown, unsupported settings are hidden, and
    preview contains only safe profile fields (never YAML serialization or
    secrets).
12. **Palette/help consistency** — `presentation/tui/app.py`,
    `presentation/tui/screens/help.py`, `presentation/tui/widgets/cmdbar.py`.
    **P4-TUI-02..08 cross-cutting.** Done when documented commands match actual
    actions, command args are not logged, apply cannot bypass confirmation, and
    rollback help does not claim executable rollback.

### 8. Open questions

1. **What should `P4-TUI-07` mean by “manifest store”?** Recommend the existing
   target-database history schema; it is the only implemented persistent run
   store and supports applied/failed/cancelled status. Do not create a second
   local history source.
2. **Should users see history for only selected target or all saved profiles?**
   Recommend selected target only for this phase. The history tables are
   database-local and do not persist a safe connection/profile identity.
3. **What to do with non-empty `Profile.ignore_patterns`?** Recommend fail
   closed with a clear, redacted “unsupported profile filters” message until
   there is a reviewed mapping to exact `IgnoreRules`; silently ignoring a
   configured filter can generate unsafe migrations.
4. **Should Settings create an editable `config.toml` format?** Recommend no.
   There is no preferences schema/loader today; show current theme, apply
   defaults, and redacted YAML profile data, then defer editable settings to a
   separate contract.
5. **Should AI review and dependency graph remain visible as empty panels?**
   Recommend hide both in live mode until real application services/data exist;
   do not show empty mock-shaped affordances or fallback suggestions.
6. **Should `:rollback` execute `down.sql`?** Recommend no. Current generated
   `down.sql` is annotation-only and the applier has no rollback use case;
   palette/help may select a history row and state that rollback is unavailable.

## Review decisions

Reviewed 2026-10-26.

1. Open questions 1–6: accept every recommendation. History is the target
   database's `pgschemadiff` schema for the selected target only; non-empty
   `ignore_patterns` fail closed; no editable `config.toml`; AI panels and the
   dependency graph are hidden in live mode; `:rollback` never executes SQL.
2. Hidden design elements (AI review, dependency graph, lock/time estimates,
   preflight probes without a real source) are hidden, not removed from the
   design. `docs/ui-design.md` §10 is updated when M5 closes to say which
   panels wait for backend data.
3. Slice 3 also stops `PgsdApp` logging the full command-palette input (it
   touches `app.py`); log the allow-listed verb only.
4. The history reader (slice 9) runs in a `READ ONLY` transaction with
   `search_path = pg_catalog` and a bounded `statement_timeout`, takes no
   advisory lock, and does not create the history schema.
5. The Migration view's bundle directory is an input defaulting to
   `./migrations` under the working directory. It must already exist; the TUI
   never creates it, matching `FilesystemMigrationWriter`.
6. The last slice adds a guard test: no module under `presentation/tui/`
   other than `_mock.py` itself imports `_mock`.
7. Slices are strictly sequential; several share `app.py`.
8. Out of scope here and already fixed separately: `pgsd inspect` printed
   driver/inspection exception text (commit `2c9df63`).
9. `Database.server_version` stays N/A in this phase; filling it in the
   inspector is a separate follow-up.
