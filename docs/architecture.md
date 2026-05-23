# Architecture — pgschemadiff

This document describes the runtime structure of pgschemadiff. For the rationale
behind individual choices, see [`adr/`](adr/).

## Layers

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              presentation                                │
│   Textual TUI screens         │     typer CLI commands                   │
│   (presentation/tui/)         │     (presentation/cli/)                  │
└────────────────┬─────────────────────────────────┬───────────────────────┘
                 │                                 │
                 ▼                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                             application                                  │
│   Use cases (compare_schemas, generate_migration, apply_migration)       │
│   Diff engine + per-type Comparators + topo sort                         │
│   SQL emitters + risk classifier + transaction unit splitter             │
│   Depends only on `domain.ports.*` Protocols.                            │
└────────────────┬─────────────────────────────────┬───────────────────────┘
                 │                                 │
                 ▼                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                            infrastructure                                │
│   psycopg async pool, pg_catalog SQL queries, snapshot inspector         │
│   migration applier, filesystem writer                                   │
└────────────────┬─────────────────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                                domain                                    │
│   Pure Pydantic v2 frozen models. Zero IO. Zero async.                   │
│   QualifiedName, ObjectRef, Schema, Table, Column, Index, …, Database    │
│   Delta hierarchy (40+ discriminated subclasses).                        │
│   ports.py: SchemaInspector, MigrationWriter (Protocols).                │
└──────────────────────────────────────────────────────────────────────────┘

shared/  — logging, errors. Importable from any layer.
```

Boundaries enforced by `import-linter`. See [ADR-0005](adr/0005-clean-architecture-4-layers.md).

## Data flow — `pgsd generate <src> <tgt> -o ./migrations/`

```
src_url ─┐                                ┌─→ deltas.json
         │                                │
         ├─→ Inspector.snapshot() ─→ Database(src) ─┐
         │                                          │
                                                    ▼
                                          DiffEngine.diff()
                                                    │
                                          ┌─────────┴─────────┐
                                          ▼                   ▼
                                    DeltaSet (unordered)   risk per Delta
                                          │
                                  topo_sort.sort(deltas)
                                          │
                                          ▼
                                 ordered DeltaSet
                                          │
                                  emitter.emit(deltas)
                                          │
                                          ▼
                                  list[TransactionUnit]
                                          │
                                  migration_writer.write()
                                          │
        ┌─────────────────────────────────┴───────────────────────────┐
        ▼               ▼               ▼               ▼             ▼
     up.sql        down.sql      manifest.json     deltas.json    README.md
```

## Concurrency

- Inspector uses one `AsyncConnectionPool` (size 5 default).
- Snapshot consistency uses `REPEATABLE READ` + `pg_export_snapshot()`
  (see [ADR-0012](adr/0012-snapshot-consistency.md)).
- The applier serializes transactional units; non-tx units run sequentially
  outside any explicit `BEGIN`/`COMMIT`.

## Error handling

A shared exception hierarchy lives in `pgschemadiff/shared/errors.py`:

```
PgSchemaDiffError
├── DomainError          (invalid domain state)
├── InspectionError      (catalog query failed)
├── DiffError            (comparison cannot proceed)
│   └── CyclicDependencyError
└── MigrationError       (emit or apply failed)
    └── BlockedMigrationError
```

The CLI translates these to non-zero exit codes; the TUI surfaces them in
the status bar.

## Testing tiers

| Tier | What it covers | DB required? |
|---|---|---|
| unit | Domain validation, diff comparators, SQL emitters, topo sort | no |
| snapshot | SQL emitter output, JSON serialization | no |
| property | hypothesis-generated `Database`s → idempotent diff, round-trip | no (round-trip uses container) |
| integration | Inspector, applier, end-to-end round-trip | yes (testcontainers PG18) |
| benchmark | 10 000-object inspect + diff + generate | yes |

## Logging

`structlog` with two renderers (JSON for CI / file, console with color for
interactive use). Selected via `PGSD_LOG_FORMAT=json|console`.

Standard fields:

- `event` — short snake_case event name
- `object_ref` — qualified name of the object being processed (when relevant)
- `duration_ms` — for timed operations
- `risk_level` — for delta-emitting events
- `run_id` — for grouping log lines from a single CLI/TUI invocation
