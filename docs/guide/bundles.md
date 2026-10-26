# Migration bundles

`pgsd generate` writes a bundle directory under the existing `--out` directory.
It does not apply the migration. The directory name combines a UTC timestamp
and the `--name` slug.

## Files

| File | Contents |
|---|---|
| `manifest.json` | Format/tool versions, bundle ID and slug, timestamps, schema fingerprints, delta assessments, ordered execution units, and the SHA-256 checksum for `up.sql`. |
| `up.sql` | Forward migration statements, transaction wrappers, and bundle/unit/delta markers. |
| `down.sql` | Irreversibility annotations only; no inverse SQL. Do not treat it as executable rollback. |
| `deltas.json` | Structured schema delta set. |
| `README.md` | Bundle summary, execution-unit table, file list, checksums, and operational warnings. |

`README.md` lists SHA-256 values for `up.sql`, `down.sql`, `manifest.json`, and
`deltas.json`. `apply` validates the bundle and the `up.sql` checksum before
execution. Review `manifest.json`, `README.md`, and `up.sql` before applying.

## Execution units and transactions

Statements are grouped into ordered execution units. Transactional units run
inside `BEGIN` / `COMMIT`; non-transactional statements run alone without those
wrappers. A standalone `CREATE INDEX CONCURRENTLY` is non-transactional. The
CHECK-constraint recipe adds the constraint and validates it in separate
units. Enum-value additions are isolated in their own unit.

Each apply records run and unit status in the target database under
`pgschemadiff.migration_runs` and `pgschemadiff.migration_units`. The history
schema is created on first apply. The applier serializes its own runs with a
migration lock and records unit checksums and transactional state.

## Failure and resume

An apply can resume a failed or cancelled run when completed units form a
prefix and the bundle/history layout still matches. Completed units are not
re-run. DDL and the applied marker for a transactional unit commit together;
a failed transactional unit rolls back as a unit.

A non-transactional unit is marked `running` before execution. If the process
stops while it runs, pgschemadiff refuses automatic resume and requires manual
inspection. An interrupted `CREATE INDEX CONCURRENTLY` can leave an INVALID
index: inspect and drop that index before retrying. Non-transactional work
cannot be rolled back by the tool.

`down.sql` is not an automatic recovery mechanism. Plan recovery as a reviewed
forward migration or use a database backup/restore procedure.
