# Phase 3b — MVP-B object types design

**Status:** Draft for review
**Date:** 2026-10-26

## Goal and scope

Define the shared catalog → domain → diff → dependency → risk → SQL path for the
ten MVP-B object families in P3-MVPB-01..10. Each supported change must produce
deterministic forward DDL and pass a PostgreSQL 18 inspect/diff/generate/apply/
re-inspect round trip. This document proposes design decisions; no code or task
status changes are included.

MVP-B extends the existing PostgreSQL 18-only MVP-A contract. It does not add a
SQL parser, `CASCADE`, rollback SQL, runtime data comparison, or automatic
dependency repair. Unsupported or insufficiently represented catalog state
fails closed as `BLOCKED` at risk classification or raises `DiffError`,
`InspectionError`, or `MigrationError` at the responsible layer.

## Current architecture and baseline

- `PgCatalogInspector` reads six catalog queries in one `REPEATABLE READ`
  transaction, sets `search_path = pg_catalog`, assembles a frozen `Database`,
  and excludes the reserved `pgschemadiff` schema.
- `Schema` currently aggregates tables and indexes; `Database` aggregates
  schemas and extensions. `ObjectKind` already names all ten MVP-B kinds.
  `ObjectRef` already requires argument signatures for functions/procedures and
  table parents for triggers/policies.
- `DiffEngine` currently fetches only schema, extension, table, and index
  objects. Its `QualifiedName`-keyed maps cannot distinguish overloaded
  routines. Unknown kinds currently produce no fetched objects; MVP-B must not
  silently inherit that behavior.
- Comparators return typed immutable deltas. `order_deltas()` is deterministic
  Kahn sorting over structured prerequisites. Emitters use exact-type dispatch,
  preserve input order, return `SqlStatement` provenance/transaction metadata,
  and fail closed for unregistered deltas. Risk is a separate, delta-only
  assessment; unknown deltas are `BLOCKED`.
- The PG18 MVP-A round-trip corpus is green in CI (48 integration cases, 0
  expected failures at CI `0c9536b`). Extend the existing corpus rather than
  creating a second end-to-end framework.

## Cross-cutting design decisions

### 1. Domain ownership and identity

- Add immutable object models and typed deltas/comparators/emitters. Keep domain
  models pure and preserve the existing Clean Architecture boundaries.
- Add top-level collections to `Schema` for views, materialized views, routines,
  sequences, and types. Keep policies and table triggers as table-owned child
  objects because their DDL identity is `(table, local name)`; `ObjectRef.parent`
  already supports both kinds. MVP trigger scope is ordinary/partitioned tables;
  view and foreign-table triggers are excluded until parent identity supports
  those relation kinds.
- Keep functions and procedures as distinct domain kinds and delta families.
  Share catalog extraction of `pg_proc`, not a generic public factory or a
  one-size-fits-all comparator.
- Use `ObjectRef` as the identity key for every fetched kind. For routines,
  `arg_signature` is the ordered canonical PostgreSQL input-argument type list
  from the catalog, excluding names and defaults. Keep names, modes, defaults,
  return type, and other behavior in the routine payload. This distinguishes
  overloads without treating a default change as a new overload.
- Extend the engine's explicit kind/fetcher/comparator registry. A registered
  kind with a missing fetcher/comparator, duplicate identity, or malformed
  routine signature raises `DiffError`; it must never become an empty diff.
  Keep explicit rename annotations as the only rename mechanism. Automatic
  rename guessing remains out of scope; unsupported rename cases must not be
  disguised as safe replacements.
- Compare structured semantic fields. For definitions available only as
  catalog-deparsed SQL (view query, routine body, trigger condition, policy or
  domain expression), that text is semantic input and is compared exactly on
  PG18; retain the full deparsed DDL as a separate emitter payload. Do not parse
  SQL or invent normalization. For objects whose semantics are fully represented
  by structured fields, raw full-DDL formatting is excluded from equality.
- Capture and emit object owners where listed in the family contract. New
  objects use a follow-up `ALTER ... OWNER TO` when the desired owner differs
  from the migration role; owner roles must already exist and be usable by the
  applier. Existing `CREATE OR REPLACE` operations preserve owner/permissions
  where PostgreSQL specifies that behavior.

### 2. Catalog and snapshot contract

- Add catalog queries under `infrastructure/postgres/catalog/` and execute them
  through the existing inspector snapshot/transaction. Proposed query groups:
  `views.sql`, `materialized_views.sql`, `routines.sql`, `sequences.sql`,
  `enums.sql`, `triggers.sql`, `policies.sql`, `types.sql`, and a shared
  dependency query. Extend inspector assembly and schema filtering once; do not
  make per-type database calls outside the consistent snapshot.
- Query only requested user schemas, but retain qualified references to
  dependencies outside that schema set. Continue to exclude `pgschemadiff`,
  system/temp schemas, and extension-owned objects. Use extension dependency
  metadata rather than schema/name heuristics to avoid comparing extension
  members as independently managed objects.
- Keep deparsers under `search_path = pg_catalog`. Preserve raw
  `pg_get_viewdef`, `pg_get_functiondef`, `pg_get_triggerdef`, and expression
  output as opaque catalog fragments; qualify object references in structured
  fields where PostgreSQL provides them.
- Map catalog dependencies into explicit `ObjectRef` prerequisites. The
  proposed query uses `pg_depend` for database-local objects and `pg_shdepend`
  for shared role dependencies. Store dependent → prerequisite orientation;
  create prerequisites before dependents and drop dependents before
  prerequisites. Keep extension membership as a filter, not an ordinary edge.
  Exact joins, dependency types, and coverage are **unverified until exercised
  against PG18 integration fixtures**.
- Inspector failures to represent a selected object or dependency faithfully
  raise `InspectionError`; do not skip malformed rows or emit placeholder
  expressions.

### 3. Diffs, dependencies, and safe replacement

- Add per-kind delta types and exact comparators. A create delta owns only its
  object's DDL; child objects remain separate deltas where the catalog exposes
  them independently. This avoids duplicate DDL and makes risk attributable.
- Carry dependency references in domain snapshots/deltas as structured data.
  Extend `order_deltas()` for create prerequisites, reverse drop prerequisites,
  owner/child relationships, and same-object drop-before-create replacements.
  Preserve deterministic `sort_key` tie-breaking and raise the existing cycle
  error on an unresolved cycle.
- Extend `AlterTableAttrs` with optional RLS enabled/forced state rather than
  introducing a second table-attribute delta family. For a new table, carry the
  state in `CreateTable`; its SQL stays in the same transaction as that table's
  policy deltas. For an existing table, order policy changes before enabling or
  forcing RLS.
- Every drop uses PostgreSQL's restrictive default/explicit `RESTRICT`; never
  add `CASCADE`. Before emitting a drop/recreate, inspect incoming dependencies:
  all affected dependents must be represented and ordered in the plan, or be
  proven unaffected. `RESTRICT` is the final safety guard, not dependency
  discovery. If dependency coverage cannot support that proof, classify the
  destructive delta `BLOCKED` rather than relying on a late apply failure.
- Catalog dependency tracking is not a complete parser for string-bodied
  routines. In particular, routine bodies can contain references not recorded
  as object dependencies. Treat bodies as trusted opaque source; use catalog
  dependencies for known signature/object edges, document the limitation, and
  do not claim dependency-complete routine-body validation.

### 4. Emitters, transaction metadata, and risk

- Add handlers in `application/sql_emit/`; `default_handlers()` remains the only
  public registry. Handlers emit forward SQL only, preserve each originating
  delta, and do not inspect the database or rewrite/sort deltas.
- Quote identifiers/literals using existing `quoting.py` rules. Emit structured
  names safely and raw catalog fragments verbatim. Missing definitions,
  sentinels, unsupported catalog variants, or unsafe prefix rewrites raise
  `MigrationError`.
- Use transactional statements by default. Enum `ALTER TYPE ... ADD VALUE` is
  emitted as one non-transactional/autocommit statement per label. This
  deliberate commit boundary ensures a newly added label is usable by later
  migration units under PostgreSQL 18; it does not claim PostgreSQL requires the
  command itself to run outside a transaction.
- Preserve transaction units through existing `SqlStatement.transactional`
  metadata. Any new multi-statement handler documents whether it needs
  `new_unit=True`; the splitter must not parse SQL.
- Add explicit `RiskLevel` mappings for every new delta. Apply existing meanings:
  additive definitions are generally `SAFE` or `WARNING`; behavior/validation
  changes are `WARNING` or `DANGEROUS`; object removal or lost guarantees are
  `DESTRUCTIVE`; unsupported semantics are `BLOCKED`. Reasons stay deterministic
  and delta-only. No new delta may rely on the classifier's unknown-type
  fallback. Owner-role changes are `DANGEROUS` because they can change effective
  access; changing a sequence's `OWNED BY` relationship is `WARNING`.
- Preserve the existing migration convention: no `IF EXISTS`, `IF NOT EXISTS`,
  or `CASCADE`. `RESTRICT` is explicit where supported and otherwise remains
  PostgreSQL's restrictive default.

## Object-family contracts

In this table, “replace” means changing an existing object to desired semantics;
all SQL is qualified and all identifiers/literals are quoted. Catalog definitions
are retained separately from semantic comparison fields.

| Task / object | Catalog and semantic model | Comparator and emitted DDL | Risk and prerequisites |
|---|---|---|---|
| **P3-MVPB-01 View** | `pg_class`/`pg_rewrite`, output columns in ordinal order, `pg_get_viewdef`, check option, `security_barrier`, `security_invoker`, owner. | Create with `CREATE VIEW`; compatible query/options change with `CREATE OR REPLACE VIEW`; set owner with `ALTER VIEW ... OWNER TO`; drop with `DROP VIEW ... RESTRICT`. For replacement, existing output column names/order/types must remain unchanged; target may append columns only. If not compatible, classify `BLOCKED` unless a separately proven drop/recreate plan has no external dependents. | Create `SAFE`; replace `DANGEROUS`; drop `DESTRUCTIVE`. Order referenced relations/views/functions/types before creation and dependents before drop. |
| **P3-MVPB-02 Materialized view** | Relation/query definition, output columns, access method, storage parameters/tablespace where supported, owner; `ispopulated` is observed but not part of schema equality. Any non-default physical option not modeled is `BLOCKED`. | Create with `CREATE MATERIALIZED VIEW ... AS ... WITH DATA`; set owner with `ALTER MATERIALIZED VIEW ... OWNER TO`; replace via restrictive drop then create (no `OR REPLACE`); drop with `DROP MATERIALIZED VIEW ... RESTRICT`. Until index ownership/lifecycle is captured, block create/replace/drop when the matview has attached indexes rather than silently losing or omitting them. | Create/replace `DANGEROUS` because creation evaluates the defining query and replacement can lose stored contents; drop `DESTRUCTIVE`. Order query prerequisites, then matview, then its indexes; reverse on drop. No refresh/data synchronization. |
| **P3-MVPB-03 Function** | `pg_proc` rows with `prokind='f'`; identity input types, argument names/modes/defaults, return type/shape (`SETOF`, `OUT`/`TABLE`), language/body, transforms, volatility, strictness/leakproof/security, parallel/cost/rows/support/config, owner; `pg_get_functiondef` retained as DDL. MVP supports `sql` and `plpgsql`; other languages fail closed. | Create with `CREATE FUNCTION`; same-identity supported body/attribute/default change with `CREATE OR REPLACE FUNCTION`; set owner with `ALTER FUNCTION ... OWNER TO`; drop with exact identity argument types. Return-type changes are `BLOCKED`; changed input signatures are distinct overload add/drop operations, never in-place replacements. MVP does not auto-pair a changed signature or parameter name/mode/output shape into a drop/create. | Create `WARNING`; replace `DANGEROUS` (runtime behavior changes); drop `DESTRUCTIVE`. Order argument/return types and catalog-known prerequisites before creation. Changing defaults can change call resolution; emit only after checking for conflicting overload/default combinations, otherwise `BLOCKED`. |
| **P3-MVPB-04 Procedure** | `pg_proc` rows with `prokind='p'`; identity input types, modes/names/defaults, language/body, transforms, security/config, owner. Exclude aggregate/window `prokind` rows. | Create with `CREATE PROCEDURE`; same-identity supported changes with `CREATE OR REPLACE PROCEDURE`; set owner with `ALTER PROCEDURE ... OWNER TO`; drop with exact identity argument types. Changed input signatures are distinct overload add/drop operations, never in-place replacements. MVP does not auto-pair changed signatures or parameter name/mode/output shape into a drop/create. | Create `WARNING`; replace `DANGEROUS`; drop `DESTRUCTIVE`. Order signature types and catalog-known prerequisites first. Procedure transaction behavior is body semantics and is not executed by the applier during migration. |
| **P3-MVPB-05 Sequence** | Sequence type, start/increment/min/max/cache/cycle, owner, and owned-by relation/column. Exclude identity backing sequences created by table identity clauses to prevent duplicate ownership; include serial-style owned sequences when their explicit default/ownership must be recreated. Runtime `last_value`/`is_called` are data state and are not compared or copied. | Create with `CREATE SEQUENCE`; alter supported options with `ALTER SEQUENCE`; set object owner with `ALTER SEQUENCE ... OWNER TO`; set/clear column ownership with `OWNED BY`; drop with `DROP SEQUENCE ... RESTRICT`. Do not emit `RESTART` or copy current values. Fail closed if ownership cannot be represented. | Unowned create `SAFE`; create of a column-owned/serial sequence `DANGEROUS` because target data state is not copied; option/`OWNED BY` change `WARNING`; owner-role change `DANGEROUS`; drop `DESTRUCTIVE`. Create sequence before defaults that reference it; establish `OWNED BY` after owner table/column exists; drop owner-dependent objects first. |
| **P3-MVPB-06 Enum** | `pg_type`/`pg_enum`; ordered label strings by PostgreSQL sort order and owner. | Create with `CREATE TYPE ... AS ENUM`; additions with `ALTER TYPE ... ADD VALUE`, selecting `BEFORE`/`AFTER` anchor to preserve target ordering; set owner with `ALTER TYPE ... OWNER TO`; drop with `DROP TYPE ... RESTRICT`. Removal, rename, and reorder of existing labels are `BLOCKED`; do not synthesize a replacement type/cast/data rewrite. | Create `SAFE`; each added label `DANGEROUS` because it is irreversible and changes accepted values; drop `DESTRUCTIVE`. Emit each addition in its own autocommit unit so dependent statements run only after commit. |
| **P3-MVPB-07 Trigger** | Non-internal `pg_trigger` rows; table/function refs, timing/events/columns/WHEN, constraint/deferral metadata, and enabled state; retain `pg_get_triggerdef`. Ignore partition-clone rows (`tgparentid != 0`) because parent trigger DDL creates them. | Create regular table triggers with `CREATE [OR REPLACE] TRIGGER`; constraint triggers cannot use `OR REPLACE`, so replace them by restrictive drop/create with a dependency edge. Emit `ALTER TABLE ... ENABLE|DISABLE|ENABLE REPLICA|ENABLE ALWAYS TRIGGER` for enabled state. Drop with `DROP TRIGGER ... ON table RESTRICT`. | Create/replace `WARNING`; drop `DESTRUCTIVE`. Table and trigger function must exist first. Internal/system and partition-clone triggers are excluded. |
| **P3-MVPB-08 RLS policy** | `pg_policy`: command, permissive/restrictive, role list, USING/WITH CHECK expressions. Add table `relrowsecurity`/`relforcerowsecurity` state to the table model; it is required for a policy round trip. On new tables, `CreateTable` carries the flags; its statements and policy deltas remain in one transaction, so no intermediate state is externally visible. Roles are external shared objects, not migrated here. | Create with `CREATE POLICY`; use `ALTER POLICY` for roles and expressions when command/permissiveness are unchanged; otherwise drop/create. Policy name changes use drop/create; no policy rename inference in MVP. Emit table `ENABLE|DISABLE ROW LEVEL SECURITY` and `FORCE|NO FORCE ROW LEVEL SECURITY` transitions as `AlterTableAttrs` fields for existing tables, ordered after policy changes when enabling. Drop with `DROP POLICY ... ON table`. | Policy/flag changes `DANGEROUS` because they alter access behavior; drop `DESTRUCTIVE`. Table must exist. Referenced roles must already exist on target; do not create roles or grants. |
| **P3-MVPB-09 Composite type** | `pg_type` composite relation and ordered live `pg_attribute` entries: name, type, collation, owner. Exclude dropped attribute placeholders from semantic equality, but retain ordinal positions correctly. | Create with `CREATE TYPE ... AS (...)`; support appended attribute, attribute rename, type change, and drop through `ALTER TYPE`; set owner with `ALTER TYPE ... OWNER TO`; use restrictive drop for object removal. Attribute reorder or unsupported catalog layout is `BLOCKED`, not simulated by destructive reconstruction. | Create `SAFE`; type/rename changes `DANGEROUS`; attribute/type removal `DESTRUCTIVE`. Attribute types precede creation; dependents precede destructive alterations/drops. |
| **P3-MVPB-10 Domain type** | `pg_type` domain metadata: base type, collation, default, not-null flag, owner, and ordered named check constraints with validation state. | Create with `CREATE DOMAIN`; alter supported default/nullability/constraint changes with `ALTER DOMAIN`; set owner with `ALTER DOMAIN ... OWNER TO`; add checks `NOT VALID` then validate in a separate transaction unit where supported; drop with `DROP DOMAIN ... RESTRICT`. Base-type/collation changes have no safe in-place path and are `BLOCKED` unless dependent-safe reconstruction is explicitly proven. | Create `SAFE`; default change `SAFE`; set not-null/add or validate checks `DANGEROUS`; remove checks or drop domain `DESTRUCTIVE`. Base type/collation and dependent objects are prerequisites. |

### PostgreSQL 18 semantics relied on

These are documentation-verified behavior, not claims that the proposed catalog
queries or emitters have already been exercised:

- `CREATE OR REPLACE VIEW` must retain existing output column names, order, and
  types; adding columns at the end is allowed. Other incompatible output changes
  require a different plan.
- `CREATE OR REPLACE FUNCTION` can change argument defaults. It cannot change
  input argument types or return type in place. Therefore defaults do **not**
  require drop/create; any earlier assumption to that effect is rejected.
  Replacement also restricts input parameter-name changes and, for multiple
  output parameters, output-name changes. Defaults can make calls ambiguous
  across overloads, so that case requires an explicit conflict check.
- `ALTER TYPE ... ADD VALUE` can run in a transaction, but a value added in that
  transaction cannot be used until the transaction commits. MVP emits each add
  as a separate autocommit unit to make the boundary explicit.
- PostgreSQL 18 supports `ALTER TYPE ... RENAME VALUE`; MVP still blocks label
  rename because opaque routine bodies/client code can contain the old literal
  and cannot be safely rewritten. Removing an enum value or changing existing
  sort order has no in-place operation.
- PostgreSQL 18 supports `CREATE OR REPLACE TRIGGER` for regular triggers, but
  not constraint triggers. Matview replacement has no `CREATE OR REPLACE`
  equivalent. Enum labels can be added at a specified position but cannot be
  removed/reordered in place. Regular triggers can be attached to views too;
  MVP deliberately limits trigger parents to tables until `ObjectRef` can
  represent view-owned triggers.
- `CREATE MATERIALIZED VIEW` evaluates its query with `WITH DATA` by default;
  materialized contents and sequence runtime values are not schema snapshots.
- PostgreSQL dependency catalogs expose tracked object dependencies, not every
  reference hidden in string-bodied routine source. No complete routine-body
  dependency guarantee is claimed.

## Explicit exclusions and fail-closed cases

- PostgreSQL versions below 18; system schemas, temp schemas, reserved
  `pgschemadiff`, and extension-owned objects.
- Aggregate and window routines, event triggers, foreign tables, user-defined
  languages other than SQL/PLpgSQL, and unsupported object kinds discovered in
  the queried catalogs.
- Sequence runtime state, materialized-view stored rows/refresh state, table
  data, grants/ACLs, security labels, and comments. Owners and security-relevant
  routine/view attributes are included where stated above; referenced roles are
  external prerequisites and are not created. Because routine ACLs are not
  modeled, creating a new `SECURITY DEFINER` function or procedure is `BLOCKED`
  unless effective privilege parity is separately proven; do not assume the
  target's default `EXECUTE` grants are safe. Replacing an existing routine
  preserves its owner/permissions, but ACL differences are not part of equality.
- Automatic rename inference; arbitrary SQL parsing; routine-body dependency
  extraction; `CASCADE`; reverse/rollback DDL; silently ignoring malformed or
  unsupported catalog rows.
- Materialized-view indexes until inspector/domain ownership is explicit. A
  destructive operation that would discard such an unmodeled index is blocked.
- Enum label removal/rename/reorder, incompatible view output changes, routine
  return/input-signature changes without proven dependency-safe reconstruction,
  composite attribute reorder, domain base-type/collation change, and any
  dependent-object rewrite whose full dependency set is unknown.

## Implementation slices

Keep each slice independently testable and, where practical, at no more than
three production source files plus tests. A slice is not complete until catalog,
model, comparator, dependency, risk, emitter, and round-trip coverage for its
supported cases agree. Cross-cutting groundwork is first; per-object slices then
follow dependency order rather than adding ten disconnected implementations.

| Order | Task | Slice and key acceptance |
|---:|---|---|
| 0 | Shared foundation | Extend `Database`/`Schema` assembly and explicit inspector/diff registries; switch fetch keys to `ObjectRef`; add dependency snapshot representation, dependency ordering for create/drop/replace, registry/risk completeness assertions. Existing MVP-A corpus remains unchanged. |
| 1 | P3-MVPB-06 Enum | Catalog/domain/delta/comparator/emitter; ordered additions, autocommit unit per addition, blocked removal/rename/reorder; PG18 enum round trips. |
| 2 | P3-MVPB-09 Composite types | Attributes and dependency edges; create/add/rename/type-change/drop supported forms; blocked reorder and dependent-unsafe drops. |
| 3 | P3-MVPB-10 Domain types | Base/default/nullability/check model; `NOT VALID`/validation transaction boundary; blocked base-type changes. |
| 4 | P3-MVPB-05 Sequences | Standalone/serial sequence ownership and table/column edges; identity sequence suppression; prove runtime state is not copied. |
| 5 | P3-MVPB-03 Functions | Overload-safe identity, body/default/attribute replacement, SQL/PLpgSQL scope, exact signature drops, output/default behavior in PG18. |
| 6 | P3-MVPB-04 Procedures | Shared `pg_proc` catalog mapping; procedure-specific model/deltas and `CREATE OR REPLACE PROCEDURE`; overload round trips. |
| 7 | P3-MVPB-01 Views | Definition/output-column/options catalog; compatible replace and incompatible-column blocker; chains of dependent views. |
| 8 | P3-MVPB-02 Materialized views | Definition/options, create/drop/recreate, data-state exclusion, index ownership blocker and query dependency order. |
| 9 | P3-MVPB-07 Triggers | Function/table dependencies, regular and constraint-trigger replacement branches, enabled state, internal-trigger exclusion. |
| 10 | P3-MVPB-08 RLS policies | Policy expressions/roles, table enable/force flags, alter vs drop/create, role prerequisite and access-behavior round trips. |

For every slice: add exact-type handler and classifier coverage; unit tests for
identity, comparison, dependency ordering, risk, quoting, SQL/transaction
metadata; and PG18 corpus scenarios. Do not mark a P3-MVPB task complete based
only on a unit snapshot.

## PostgreSQL 18 round-trip acceptance scenarios

Extend `tests/integration/test_round_trip_corpus.py` with separate labeled cases
and combined cases. For each supported change, assert: correct catalog load,
expected delta count/kind, deterministic ordered DDL, successful apply to an
independent target, and no remaining supported-schema delta after re-inspection.
Also assert unsupported cases fail before SQL execution with `BLOCKED` or the
documented domain/application error.

1. **Views:** create; compatible definition/options replacement; append output
   column; reject rename/reorder/type change; multi-view prerequisite ordering;
   restrictive drop with dependent view.
2. **Materialized views:** create populated matview without attached indexes;
   compare query/options; drop/recreate; verify stored rows are not compared;
   assert matview operations block when attached indexes are not accounted for.
3. **Functions:** zero-argument and overloaded functions; SQL and PL/pgSQL
   bodies; defaults changed by `CREATE OR REPLACE`; return-type/parameter-shape
   change blocked; input-type change represented only as explicit overload
   add/drop with dependent-drop preflight; exact overload drop; mixed-case
   identifiers and schema-qualified custom types.
4. **Procedures:** overloads, modes/defaults, body replacement, owner and
   security-invoker attributes, exact drop signature; prove functions and
   procedures do not collide in identity or dispatch. Assert new
   `SECURITY DEFINER` routines fail closed while ACLs are not modeled.
5. **Sequences:** create and alter increment/bounds/cache/cycle; owned-by order;
   serial-style dependency; identity backing sequence not duplicated; target
   `last_value` remains untouched; column-owned creation receives DANGEROUS risk.
6. **Enums:** create labels; append and insert labels with `BEFORE`/`AFTER`; each
   addition commits before later statements use it; reject removal, rename, and
   reorder; verify label order after re-inspection.
7. **Triggers:** regular trigger create/replace; constraint trigger drop/create;
   trigger function created first; enabled/disabled/replica/always state;
   internal trigger omitted.
8. **Policies:** permissive/restrictive, commands, quoted role list, USING and
   WITH CHECK; `ALTER POLICY`-compatible changes; drop/create for unsupported
   in-place changes; RLS enabled/forced table-state round trip; missing-role
   prerequisite reported as an execution limitation.
9. **Composite types:** ordered attributes, add/rename/type-change/drop; reject
   reordering and dependent-unsafe operations.
10. **Domains:** base type/default/not-null/check constraints; invalid existing
    data causes validation failure without silently bypassing validation;
    check addition/validation transaction boundaries; base-type change blocked.
11. **Cross-family:** enum/domain/composite before routine signatures and table
    columns; routine before trigger; sequence before serial default and owner
    attachment after table; view chain ordering; policy and RLS state on a new
    table; reverse dependency ordering on safe drops.
12. **Boundaries:** selected-schema references to unselected schemas remain
    qualified; extension-owned objects and `pgschemadiff` remain excluded;
    unsupported languages/objects and ambiguous dependencies fail closed.

The acceptance gate is a green PG18 corpus in CI with no expected failures for
supported cases, plus existing unit/lint/type/import gates. Docker/Testcontainers
availability locally is not assumed; CI remains the authoritative integration
environment when local Docker is unavailable.

## Open questions and verification items

1. **Dependency completeness:** verify `pg_depend`/`pg_shdepend` joins, object
   class mapping, extension membership, and partition/internal dependency
   filtering against PG18 fixtures. Until then, destructive operations involving
   ambiguous or unmodeled dependencies remain blocked.
2. **Routine support surface:** confirm maintainers accept SQL and PL/pgSQL only
   for MVP-B. Other languages depend on server-installed handlers or external
   binaries and are not reproducible from this snapshot. Verify procedure
   parameter replacement edge cases separately from the function rules.
3. **Raw deparser portability:** verify every stored definition under
   `search_path = pg_catalog` is schema-qualified and round-trips for quoted
   names, custom types, collations, and cross-schema dependencies. Reject an
   unproven definition instead of rewriting SQL text.
4. **Matview indexes:** decide whether MVP-B will extend existing index catalog
   ownership to materialized views in the matview slice or defer all destructive
   matview changes when indexes are present. The default in this design is
   fail-closed.
5. **Role and privilege boundary:** confirm role provisioning remains external.
   Policies and owners require existing roles. Routine ACLs remain outside this
   MVP; creating `SECURITY DEFINER` routines stays blocked unless permission
   parity can be proven.
6. **Definition equality:** confirm which routine/view options are semantic
   fields versus retained raw DDL only; catalog output formatting must not
   produce false diffs.
7. **Nontransactional enum units:** verify applier history/resume behavior for
   one autocommit `ALTER TYPE ... ADD VALUE` per unit, including connection loss
   after server commit and before history recording. Existing applier semantics
   require operator inspection for indeterminate nontransactional units.
8. **Selected schemas:** verify dependency behavior when a referenced object is
   outside the selected schema set and cannot be compared or migrated in the
   same plan.
9. **Domain checks in containers:** PG18 documents limitations for adding or
   validating domain constraints when the domain (or a derived domain) appears
   inside composite/array/range columns. Verify detection; block these cases
   until the inspector can prove the operation is supported.

## PostgreSQL 18 references

- [CREATE VIEW](https://www.postgresql.org/docs/18/sql-createview.html)
- [CREATE MATERIALIZED VIEW](https://www.postgresql.org/docs/18/sql-creatematerializedview.html)
- [CREATE FUNCTION](https://www.postgresql.org/docs/18/sql-createfunction.html)
- [CREATE PROCEDURE](https://www.postgresql.org/docs/18/sql-createprocedure.html)
- [CREATE SEQUENCE](https://www.postgresql.org/docs/18/sql-createsequence.html) and [ALTER SEQUENCE](https://www.postgresql.org/docs/18/sql-altersequence.html)
- [ALTER TYPE](https://www.postgresql.org/docs/18/sql-altertype.html)
- [CREATE TRIGGER](https://www.postgresql.org/docs/18/sql-createtrigger.html)
- [CREATE POLICY](https://www.postgresql.org/docs/18/sql-createpolicy.html) and [ALTER POLICY](https://www.postgresql.org/docs/18/sql-alterpolicy.html)
- [CREATE DOMAIN](https://www.postgresql.org/docs/18/sql-createdomain.html) and [ALTER DOMAIN](https://www.postgresql.org/docs/18/sql-alterdomain.html)
- [Dependency tracking](https://www.postgresql.org/docs/18/ddl-depend.html), [`pg_depend`](https://www.postgresql.org/docs/18/catalog-pg-depend.html), and [`pg_shdepend`](https://www.postgresql.org/docs/18/catalog-pg-shdepend.html)

## Review decisions

Reviewed 2026-10-26.

- **Accepted as written:** cross-cutting decisions 1–4, object-family contracts,
  exclusions, and slice order (enum → composite → domain → sequence → function →
  procedure → view → matview → trigger → policy).
- **Open questions 1–6, 8, 9:** accepted as recommended. Dependency coverage
  that cannot be proven keeps destructive operations `BLOCKED`; MVP-B routines
  are `sql` and `plpgsql` only; unproven deparsed definitions are rejected, not
  rewritten; matview indexes stay fail-closed in the matview slice; roles and
  ACLs remain external and new `SECURITY DEFINER` routines stay `BLOCKED`;
  references outside the selected schema set stay qualified and missing ones
  are an apply-time limitation (documented, not auto-migrated); domain checks
  used inside composite/array/range columns are `BLOCKED`.
- **Open question 7 — changed:** do **not** emit `ALTER TYPE ... ADD VALUE` as
  autocommit. Emit it as a *transactional* statement isolated in its own unit
  (the unit closes after it, so later statements that use the label start a new
  unit after the commit). This keeps the applier's atomic per-unit history
  marker and safe resume; an autocommit unit would make every crash window an
  indeterminate-resume stop. Slice 1 adds the minimal splitter support (for
  example a statement flag that also ends the unit) with tests.
- **Slice 0 split:** keep each slice at ≤3 production files. 0a: ObjectRef-keyed
  engine fetch/comparator registry with completeness assertions (MVP-A behaviour
  unchanged). 0b: catalog dependency snapshot (`pg_depend`) + domain
  representation + `order_deltas` create/drop/replace edges, exercised first by
  the enum slice (column type → enum). Each lands with the existing corpus green.
- **Per-slice gate:** a P3-MVPB task is done only when its PG18 corpus scenarios
  pass in CI with no xfails for supported cases.
