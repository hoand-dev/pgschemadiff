# P2-CLI-01 — Diff command design

**Status:** Approved by user on 2026-10-22.
**Date:** 2026-10-22

## Goal

Implement `pgsd diff` for two live PostgreSQL databases. The command inspects
both databases, compares supported schema objects, orders the resulting deltas
by dependency, and writes stable, typed `DeltaSet` JSON to stdout.

## Decisions

- Inputs are two live connection URLs. Saved inspect JSON is out of scope.
- `--schema` is repeatable and filters schema-scoped objects in both
  inspections; extensions remain database-wide because they are a separate
  `Database` collection.
- `--renames PATH` loads existing YAML/TOML rename annotations.
- Ignore rules are accepted by the application use case, but no CLI ignore
  syntax or ignore-config loader is added.
- Add schema and extension comparators to the current table, column, index, and
  constraint comparator set.
- Use dependency edges and `topological_sort`; use `DeltaBase.sort_key` only to
  break ties between simultaneously ready deltas.
- Do not silently discard schema owner/comment or extension comment changes:
  raise `DiffError` because current delta models cannot represent them.
- CLI failures go to stderr with exit code 1. Connection URLs and credentials
  must not appear in output or logs.

## Components and flow

### Application use case

Add async `compare_schemas(source_inspector, target_inspector, *, renames=None,
ignore=None) -> DeltaSet` in `application/diff/compare_schemas.py`.

The use case depends only on the `SchemaInspector` protocol and application
components. It inspects source and target, builds a fresh `DiffEngine` with the
default comparator set, calls `diff(..., renames=..., ignore=...)`, orders the
result, and returns a `DeltaSet`. It does not serialize JSON or construct
infrastructure objects.

The default comparator set contains:

- `SchemaComparator`
- `ExtensionComparator`
- `TableComparator` with `ColumnComparator` and `ConstraintComparator`
- `IndexComparator`

### Comparators

Add per-kind modules and unit tests under
`application/diff/comparators/` and
`tests/unit/application/diff/comparators/`.

- Schema: create/drop. For a schema present on both sides, compare its
  owner/comment separately from its child tables and indexes; if owner or
  comment differs, raise `DiffError` because no alter-schema delta exists.
- Extension: create/drop and alter version/installed schema using existing
  delta types. If comment differs, raise `DiffError` because no extension
  comment delta exists.
- Existing table/column/index/constraint comparator behavior remains unchanged.

The current catalog inspector does not populate schema owner/comment or
extension installed schema/comment. Extend its catalog queries and row mapping
to populate these existing domain fields; add inspector tests so the comparator
does not compare default `None` values in place of database state.

### Dependency ordering

Add a pure `application/diff/dependencies.py` function that accepts a
`DeltaSet`, derives prerequisite edges from delta targets and structured
payloads, invokes `topological_sort`, and returns a new `DeltaSet`.

Only add an edge when both prerequisite and dependent deltas exist in the set.
Do not parse SQL expressions. Cover these relationships:

| Prerequisite | Dependent |
|---|---|
| Create schema | Create table, index, or create/alter extension targeting that installed schema |
| Create table | Add constraint or create/replace index owned by that table |
| Add column | Add constraint or create/replace index whose new definition uses that column |
| Drop constraint/index or replace index | Drop column or table using its owning/old definition |
| Drop table, index, or extension | Drop its containing schema |
| Create owning/referenced table or add owning/referenced column | Add foreign-key constraint, or create table whose payload contains that FK |
| Drop foreign-key constraint | Drop its owning or referenced table/column |
| Drop table whose payload contains an FK | Drop its referenced table/column |
| Table/column rename | Other deltas using the new identity |

For index replacements, derive creation prerequisites from `new_index` and
drop prerequisites from `old_index`. Use structured table and column refs;
never infer dependencies from SQL text. Schema membership for an extension
comes from its `installed_schema` on creation and `AlterExtension.new_schema`
on relocation, not the extension `ObjectRef` namespace.
`CreateTable` and `DropTable` carry constraints in their table payloads, so
extract FK dependencies from those payloads as well as `AddConstraint` and
`DropConstraint`. Do not create a self-edge for an FK contained in the same
table delta.

Use `DeltaBase.sort_key` for deterministic tie-breaking. Propagate
`CyclicDependencyError` to the CLI error boundary.

### CLI

Register `pgsd diff <source-url> <target-url>` in
`presentation/cli/main.py` and implement its command in
`presentation/cli/commands/diff.py`.

The presentation command constructs source/target `Pool`s and
`PgCatalogInspector`s, passing the same optional schema list to both. It loads
rename annotations when `--renames` is provided, calls the use case, and prints
`DeltaSet.model_dump_json(indent=2)` to stdout. No snapshot input, output-file
option, or CLI ignore option is added.

Connection, inspection, annotation, unsupported-field, and cycle errors are
reported on stderr with exit code 1. Error rendering must not expose source or
target URLs, usernames, or passwords.

## Tests and acceptance

- Comparator unit tests cover create/drop, extension version/schema changes,
  schema/extension unsupported-field errors, and no-change cases.
- Inspector tests cover schema owner/comment and extension installed
  schema/comment mapping.
- Dependency tests cover each edge family, FK references, rename ordering,
  stable ordering for unrelated deltas, and cycle propagation.
- Application tests verify both inspectors feed the default comparator set,
  programmatic ignore rules are applied, and the returned `DeltaSet` remains
  typed and ordered.
- CLI tests verify command registration/arguments, repeatable schema filters,
  database-wide extension comparison with a schema filter,
  rename loading, valid JSON on stdout, exit code 1 on errors, stderr handling,
  and credential redaction from output and captured logs (including raw driver
  exception messages).
- The command's JSON must parse and remain stable for identical inputs.

## Out of scope

- Loading snapshots from JSON files.
- CLI parsing or file loading for ignore rules.
- Schema owner/comment and extension comment alter deltas; those differences
  fail explicitly until domain delta models support them.
- SQL generation or migration application.
