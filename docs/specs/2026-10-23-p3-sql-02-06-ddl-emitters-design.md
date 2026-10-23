# P3-SQL-02..06 — Concrete DDL emitters design

**Status:** Approved with review decisions (2026-10-23)  
**Date:** 2026-10-23

## Goal

Define forward-only SQL for every current `Delta` type, preserving dependency
order, transaction metadata, catalog expressions, and fail-closed behavior.

## Decisions

- Keep handlers in `application/sql_emit/`; they remain pure application code
  and import no infrastructure or presentation modules (ADR-0005).
- Add `table_emitter.py`, `column_emitter.py`, `index_emitter.py`, and
  `constraint_emitter.py` for P3-SQL-02..05. Add `schema_emitter.py` for
  proposed P3-SQL-06 (schema/extension DDL, absent from `TASKS.md`). Put
  identifier/literal helpers in `quoting.py` and the sole public
  `default_handlers()` factory in `registry.py`.
- `default_handlers()` returns a fresh exact-type mapping for `SqlEmitter`;
  handlers emit `SqlStatement(sql, transactional, delta)` with original delta
  identity. No registration side effects, sorting, risk checks, or rollback.
- Register every current concrete `Delta` member. The explicit unsupported
  type list is empty; unsupported *payloads* raise `MigrationError`. Unknown
  future subclasses remain unregistered and fail through `SqlEmitter`'s
  existing exact-type, fail-closed dispatch (P3-SQL-01).
- Keep the ordered `DeltaSet` from `order_deltas` as statement order. Add
  missing prerequisite edges described below; do not sort in the emitter.
- Emit one SQL statement per `SqlStatement`; each statement carries its own
  transaction flag (ADR-0008). No `IF EXISTS`, `IF NOT EXISTS`, or implicit
  `CASCADE`; migrations are not idempotent by default.
- Risk stays external to SQL generation. P3-RISK-01's delta-only classifier
  and gate remain upstream; emission does not inspect SQL or change a risk
  assessment (ADR-0009).

## Quoting and catalog fragments

- `quote_ident(value)` always double-quotes identifiers, doubles embedded `"`,
  and rejects empty strings, NUL, and identifiers over PostgreSQL's default
  63-byte limit with `MigrationError`. Always-quote is semantically equivalent
  to PostgreSQL `quote_ident`, preserves case, and gives stable snapshots
  without duplicating keyword/lowercase rules.
- Quote each qualified-name component separately:
  `quote_ident(namespace) + "." + quote_ident(name)`. Never quote a dotted
  `QualifiedName.fqn` as one identifier. Quote roles, tablespaces, columns,
  constraint/index names, and schema names the same way.
- `quote_literal(value)` wraps in single quotes and doubles embedded apostrophes;
  reject NUL. Use for comment text and extension versions. `None` means no
  comment statement. For `AlterTableAttrs.new_comment == ""`, emit
  `COMMENT ON TABLE ... IS NULL` per the delta contract.
- Emit catalog expressions verbatim; do not quote, parse, normalize, or invent
  them: `Column.default_expr`, `Column.generated_expression`,
  `CheckConstraint.expression`, `IndexKeyColumn.expression`,
  `Index.predicate`, `ExclusionConstraint.predicate` and
  `ExclusionElement.column_or_expr`, `PartitionInfo.partition_key`, and
  `PartitionOf.partition_bound`. `Column.data_type` is the canonical type SQL
  text from `format_type`/the type normalizer, not an identifier to quote.
- Catalog gaps are real: `indexes.sql` selects full `pg_get_indexdef`, but
  `_map_index` only parses key columns and discards the definition (and does
  not populate `include_columns` or `comment`). `constraints.sql` selects full
  `pg_get_constraintdef`; `_map_constraint` parses it and discards the full
  string. Check expressions are extracted verbatim, while failed parsers may
  leave `"?"` sentinels. Defaults/generated expressions and partition key/bound
  strings are retained from `pg_get_expr`/`pg_get_partkeydef`.
- Before index/constraint DDL is enabled, preserve raw definitions in their
  domain models and populate them in the inspector. Require a usable raw
  definition for index creation/replacement and PK/UNIQUE/CHECK/EXCLUSION
  addition; reject missing definitions or `"?"` sentinels with
  `MigrationError`. Keep raw definition fields out of semantic comparator
  equality. Build FK references from structured fields so
  `ref_namespace`/`ref_table` are always schema-qualified; fail if the typed
  model cannot represent the catalog definition.

## SQL contract

All names below are quoted by `quoting.py`; `Q` means the qualified object,
`L(x)` a quoted literal, `expr` a verbatim catalog fragment, and `tx` the
`SqlStatement.transactional` value. No statement is silently omitted.

### Table deltas — P3-SQL-02

| Delta | SQL template(s) | tx | Count |
|---|---|---:|---:|
| `CreateTable` | `CREATE TABLE Q (column-defs)`; or `CREATE TABLE Q PARTITION OF parent FOR VALUES ...`; optional separate `ALTER TABLE Q OWNER TO role`, `ALTER TABLE Q SET TABLESPACE space`, `COMMENT ON TABLE Q IS literal` | true | 1–4 |
| `DropTable` | `DROP TABLE Q RESTRICT` | true | 1 |
| `RenameTable` | `ALTER TABLE old-Q RENAME TO new-name` | true | 1 |
| `AlterTableAttrs` | One statement per present supported field: `ALTER TABLE Q OWNER TO role`; `ALTER TABLE Q SET TABLESPACE space`; `COMMENT ON TABLE Q IS literal` (`new_comment == ""` gives `IS NULL`) | true | 1–3 |

`CreateTable` emits ordered columns only; it does not inline constraints or
indexes. Column form is `name type [COLLATE collation] [DEFAULT expr |
GENERATED ...] [NOT NULL]`. Identity uses `GENERATED {ALWAYS | BY DEFAULT} AS
IDENTITY` with only supplied sequence options; stored generation uses
`GENERATED ALWAYS AS (expr) STORED`. A partition root appends
`PARTITION BY {raw pg_get_partkeydef output}`. A partition child uses
`PARTITION OF parent` plus the raw bound, or `FOR VALUES DEFAULT` when the bound
is `None`; it does not restate inherited columns. Owner, tablespace, and comment
are follow-up statements, each with `tx=True`.

### Column deltas — P3-SQL-03

| Delta | SQL template | tx | Count |
|---|---|---:|---:|
| `AddColumn` | `ALTER TABLE parent ADD COLUMN column-def` (same form/options as a created-table column) | true | 1 |
| `DropColumn` | `ALTER TABLE parent DROP COLUMN column` | true | 1 |
| `AlterColumnType` | `ALTER TABLE parent ALTER COLUMN column TYPE new-type [COLLATE collation] [USING expr]` | true | 1 |
| `SetColumnDefault` | `ALTER TABLE parent ALTER COLUMN column SET DEFAULT expr`, or `... DROP DEFAULT` when `new_default is None` | true | 1 |
| `SetColumnNullability` | `ALTER TABLE parent ALTER COLUMN column SET NOT NULL`, or `... DROP NOT NULL` when `nullable=True` | true | 1 |
| `RenameColumn` | `ALTER TABLE parent RENAME COLUMN old-name TO new-name` | true | 1 |

### Index deltas — P3-SQL-04

| Delta | SQL template(s) | tx | Count |
|---|---|---:|---:|
| `CreateIndex` | Raw `pg_get_indexdef` with only its leading `CREATE [UNIQUE] INDEX` changed to `CREATE [UNIQUE] INDEX CONCURRENTLY`; optional `COMMENT ON INDEX Q IS literal` | false for create; true for comment | 1–2 |
| `DropIndex` | `DROP INDEX CONCURRENTLY Q` | false | 1 |
| `ReplaceIndex` | `DROP INDEX CONCURRENTLY old-Q`; then raw new definition with `CONCURRENTLY` inserted as above; optional comment on new index | false for drop/create; true for comment | 2–3 |

The prefix rewrite is allowed only for the exact catalog-produced prefix;
anything else fails closed. Replacement is deliberately DROP-then-CREATE, not
atomic: there is a window with no index, and a failed create leaves it absent.
`CONCURRENTLY` is the fixed default, not a setting. Constraint-backed indexes
must never reach these handlers; their owning constraint DDL creates/drops
them.

### Constraint deltas — P3-SQL-05

| Delta / kind | SQL template(s) | tx | Count |
|---|---|---:|---:|
| `AddConstraint`: PK, UNIQUE, EXCLUSION | `ALTER TABLE parent ADD CONSTRAINT name {raw pg_get_constraintdef}` | true | 1 |
| `AddConstraint`: CHECK | `ALTER TABLE parent ADD CONSTRAINT name {raw CHECK definition} NOT VALID`; then `ALTER TABLE parent VALIDATE CONSTRAINT name` | true | 2 |
| `AddConstraint`: FK | `ALTER TABLE parent ADD CONSTRAINT name FOREIGN KEY (local-cols) REFERENCES ref-Q (ref-cols) [MATCH ...] [ON UPDATE ...] [ON DELETE ...] [DEFERRABILITY] NOT VALID`; then `ALTER TABLE parent VALIDATE CONSTRAINT name` | true | 2 |
| `DropConstraint` (all kinds) | `ALTER TABLE parent DROP CONSTRAINT name` | true | 1 |

Raw definitions exclude the constraint name; emitter quotes the name separately.
FK action/match/deferrability clauses come from typed inspector fields, and the
referenced relation is always qualified. Emit FK `MATCH`, `ON UPDATE`,
`ON DELETE`, and deferrability from their enum fields, including explicit
`NO ACTION`/`NOT DEFERRABLE` defaults for stable output. `NOT VALID` applies
only to CHECK/FK; PK, UNIQUE, and EXCLUSION have no equivalent form. Every
statement remains transactional. A constraint replacement is `DropConstraint`
then `AddConstraint`;
`dependencies.py` must add an explicit drop-before-add edge for same-name
replacements because topo tie-breaking uses `sort_key`, not comparator insertion
order.

### Schema and extension deltas — proposed P3-SQL-06

| Delta | SQL template(s) | tx | Count |
|---|---|---:|---:|
| `CreateSchema` | `CREATE SCHEMA name [AUTHORIZATION owner]`; optional `COMMENT ON SCHEMA name IS literal` | true | 1–2 |
| `DropSchema` | `DROP SCHEMA name RESTRICT` | true | 1 |
| `CreateExtension` | `CREATE EXTENSION name [WITH SCHEMA schema] VERSION literal`; optional `COMMENT ON EXTENSION name IS literal` | true | 1–2 |
| `DropExtension` | `DROP EXTENSION name RESTRICT` | true | 1 |
| `AlterExtension` | If both fields exist, first `ALTER EXTENSION name UPDATE TO literal`, then `ALTER EXTENSION name SET SCHEMA schema`; emit only present clauses | true | 1–2 |

Extension names are not schema-qualified; use `Extension.name`. Schema and
extension aggregates are payloads, not recursive DDL: their tables/indexes
arrive in their own deltas. Schema/extension drops use `RESTRICT`; existing
schema-drop dependencies order child drops first.

## Ordering and duplicate prevention

- Current `TableComparator` emits exactly one `CreateTable` when a table is new;
  its `table` payload contains all columns and constraints, with no separate
  `AddColumn`/`AddConstraint`. `IndexComparator` separately handles indexes.
- Change new-table comparison to emit `CreateTable` plus one `AddConstraint` per
  local target constraint. `CreateTable` consumes only columns/partition attrs;
  only `AddConstraint` consumes constraints. There are no `AddColumn` deltas for
  a new table. This makes CHECK/FK validation explicit and prevents duplicate
  constraint SQL.
- Extend `dependencies.py`: each `AddConstraint` depends on its owner and local
  columns; FK adds also depend on referenced table/columns. Remove FK edges from
  `CreateTable` payloads. Then even cyclic FKs wait until every table exists,
  while table-create nodes stay acyclic. A new partition child must depend on
  its parent-table create. Existing tables continue to use comparator-produced
  `AddConstraint`/`DropConstraint` deltas.
- The index catalog includes PK/unique/exclusion backing indexes, and current
  `IndexComparator` does not filter them. Add catalog/domain ownership metadata
  and suppress standalone index deltas for constraint-backed indexes; otherwise
  `CreateIndex`/`DropIndex` duplicates or conflicts with constraint DDL.
- For partition children, emit only local constraints; inherited constraints
  come from the parent. Add catalog filtering/metadata using
  `pg_constraint.conparentid`; until that distinction exists, fail closed rather
  than guessing which target constraints are inherited.
- `order_deltas` is deterministic Kahn sorting by `DeltaBase.sort_key`; it
  currently adds FK dependencies for constraints embedded in `CreateTable`, but
  does not add partition-parent or same-name constraint replacement edges.
  Implement and test those edges before claiming cyclic-FK support.

## Unsupported and error behavior

- Raise `MigrationError` for absent required raw definitions, blank/`"?"`
  catalog placeholders, invalid identifiers/literals, unsupported constraint
  forms, or handler output that cannot faithfully represent the delta.
- `AlterTableAttrs` with `new_partition_info` or `new_partition_of` is
  unsupported: PostgreSQL cannot change partition strategy/parent membership
  with a simple `ALTER TABLE`; do not fabricate detach/attach or row-movement
  SQL.
- `AlterColumnType` emits the supplied `USING` fragment only. If absent, emit
  bare `TYPE new-type` as the delta contract specifies implicit conversion;
  PostgreSQL rejects conversions requiring `USING`. Never synthesize a cast.
- `MATCH PARTIAL`, constraint options missing from the preserved definition,
  constraint-backed index deltas, and partition children with unclassified
  constraints fail closed. Do not add `CASCADE` to make dependency errors pass.
- No reverse SQL, source-state lookup, IO, or database execution belongs here;
  rollback remains out per P3-SQL-01 and ADR-0008.

## Tests and implementation split

- Add syrupy snapshots under `tests/unit/application/sql_emit/`, grouped by
  emitter module. Assert exact SQL, ordering, statement count, delta identity,
  and each statement's `transactional` value. P3-TEST-02 may extend this corpus.
- Add quoting unit tests for mixed case, keywords, embedded quotes/apostrophes,
  Unicode, empty values, and NUL. Add registry completeness test: every concrete
  `Delta` union member has exactly one handler or appears on a tested explicit
  unsupported list.
- Ordered implementation slices (at most three source files per slice, tests
  additional):
  1. Preserve index definition/INCLUDE/constraint ownership: `indexes.sql`,
     `domain/index.py`, `inspector.py` + inspector/model tests.
  2. Preserve constraint definition and inherited status: `constraints.sql`,
     `domain/constraint.py`, `inspector.py` + inspector/model tests.
  3. Change table/constraint/index comparators: `comparators/table.py`,
     `comparators/constraint.py`, `comparators/index.py` + comparator tests
     (new-table AddConstraints, raw-field equality, inherited and
     constraint-owned filtering).
  4. Fix prerequisites in `dependencies.py` + dependency tests (FK cycles,
     partition parent, constraint replacement).
  5. Add `quoting.py` + quoting tests.
  6. Implement `table_emitter.py` + table snapshots.
  7. Implement `column_emitter.py` + column snapshots.
  8. Implement `index_emitter.py` + index snapshots.
  9. Implement `constraint_emitter.py` + constraint snapshots.
  10. Implement `schema_emitter.py` and `registry.py` + schema/extension
     snapshots and registry completeness test.
- Done when every current delta is registered or explicitly unsupported,
  unsupported payloads fail with `MigrationError`, snapshots and quote tests
  pass, cyclic FKs order after all table creates, and no duplicate index or
  constraint DDL is emitted.

## Open questions

1. **Can the emitter work with today's lossy index/constraint models?** No:
   index definitions/INCLUDE and full constraint definitions are discarded, and
   backing-index ownership is missing. **Recommend** the domain/catalog/inspector
   prerequisites above; until present, fail closed for affected DDL.
2. **Is raw deparser SQL schema-qualified independently of `search_path`?**
   **Recommend** use structured FK namespace/name for references and require
   schema-qualified raw index table definitions; reject a raw definition that
   cannot be proven portable rather than rewriting SQL fragments.
3. **Can P3-SQL-02..06 include inspector gaps for table owner/tablespace/comment,
   collation namespace, and persistence?** `tables.sql` reads persistence but
   `_build_tables` drops it; table owner/tablespace/comment are not selected,
   and column collation stores only a local name. **Recommend** add the missing
   metadata before promising round-trip fidelity; fail closed for known
   non-default values without qualified data.
4. **Should `AlterColumnType` require explicit `using_expression`?** Its model
   explicitly defines `None` as an implicit cast, but lacks old type data to
   preflight PostgreSQL's cast. **Recommend** retain the current bare-`TYPE`
   behavior and never guess `USING`; require explicit expression only if future
   generation policy demands pre-execution cast proof.
5. **Does `PartitionInfo.partition_key` always hold the complete
   `pg_get_partkeydef` clause?** The inspector stores that function's output,
   while the domain doc calls it an expression. **Recommend** confirm with one
   catalog snapshot and standardize the field as the complete clause before
   rendering `PARTITION BY`.

## Review decisions (2026-10-23)

- **Q1, Q2, Q4:** accepted as recommended.
- **Q3:** do not block P3-SQL on table owner/tablespace/comment capture; the
  inspector yields `None`, so no statement is emitted and round-trip equality
  holds. Track `relpersistence` (UNLOGGED/TEMP) as follow-up `TD-INSPECT-01`;
  until captured, `CreateTable` emits a regular (logged) table.
- **Q5:** verify in slice 6 with a catalog snapshot test before rendering
  `PARTITION BY`.
- **VALIDATE CONSTRAINT needs its own transaction unit.** `NOT VALID` only
  helps when validation commits separately from the `ADD CONSTRAINT` lock.
  `SqlStatement` stays `transactional=True`; P3-TX-01 must split before each
  `VALIDATE CONSTRAINT`. Slice 9 must expose this (e.g. a statement-level
  marker or a documented rule the splitter can rely on without parsing SQL).
- **Dropped tables:** `IndexComparator` still emits `DropIndex` for indexes of
  a dropped table, ordered before `DropTable`. This is redundant but correct;
  keep it for now, do not add suppression logic in these slices.
