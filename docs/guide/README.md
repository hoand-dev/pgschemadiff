# User guide

## 30-second overview

`pgsd` compares two live PostgreSQL schemas. **Source is the current database
you will change; target is the desired schema.** `diff` reports schema changes,
`generate` writes a reviewed migration bundle, and `apply` runs that bundle on
the source/current database. The tool classifies risk and records migration
history; it does not compare table data, invent inverse SQL, or apply a diff
automatically.

Start here:

- [Getting started](getting-started.md) — install and run a first migration.
- [CLI reference](cli.md) — options, output streams, and exit codes.
- [TUI guide](tui.md) — profiles, screens, commands, and apply confirmation.
- [Bundles](bundles.md) — generated files, transactions, history, and resume.
- [Risk and safety](risk-and-safety.md) — risk levels and review workflow.
- [Limitations](limitations.md) — supported objects and known boundaries.
- [Safe-migration cookbook](cookbook/README.md) — executable examples.

Use `postgresql://app@localhost/current`-style URLs in CLI examples. Supply
secrets through `PGPASSWORD`, `.pgpass`, or a protected profile file; do not
commit credentials.

`docs/api.md`, `docs/migration.md`, `PROGRESS.md`, and `REVIEW.md` are legacy
references, not maintained user guides.
