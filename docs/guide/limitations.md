# Limitations

`pgsd` compares schema definitions, not table contents. It does not estimate
lock duration, row counts, replica lag, or execution time, and it does not
generate executable rollback SQL. Review and test generated SQL against your
PostgreSQL version and workload.

## Supported schema objects

The current inspection/diff pipeline covers schemas, extensions, tables,
columns, indexes, constraints (including foreign keys), sequences, enum,
composite and domain types, functions, procedures, views, materialized views,
triggers, and row-level security policies.

## Known limits and workarounds

- **Views depending on altered or dropped columns are not rebuilt.** Inspect
  dependent views and update/recreate them explicitly in a reviewed migration.
- **Policy expressions that reference other relations are not dependency-ordered.**
  Review referenced objects and split or order the migration manually.
- **Composite-type attribute type changes are not dependency-ordered.** Check
  dependent columns, routines, and views, then order the required DDL yourself.
- **`down.sql` is not executable rollback SQL.** It contains irreversibility
  notes only. Prepare a reviewed forward repair, or use your backup/restore
  process.
- **No table-data comparison is performed.** Use application-specific queries
  or data-validation tooling for row contents and invariants.
- **TUI profiles with non-empty `ignore_patterns` or a mode other than
  `schema-only` are rejected by comparison.** These filters are not applied.
  Remove unsupported profile settings; use `--schema` in the CLI for schema
  inclusion (there is no table-exclusion option).
- **Server version is not displayed by the TUI.** Check `SHOW server_version`
  directly and verify PostgreSQL-version-specific DDL behavior before rollout.
- **An interrupted non-transactional statement is not automatically resumed.**
  Inspect its effects manually; a failed concurrent index build may leave an
  INVALID index that must be removed before retrying.
- **The source fingerprint check is not atomic with apply.** Concurrent DDL can
  change the database after verification and before migration execution. Avoid
  concurrent schema changes during that window; locking across the guard and
  migration is not currently provided.

See [Bundles](bundles.md) for file integrity, transaction units, history, and
resume details.
