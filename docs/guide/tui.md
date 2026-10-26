# TUI guide

Launch with `pgsd` or `pgsd tui`. The app reads a profile file, compares its
source and target, and provides screens for reviewing and applying a saved
bundle.

A profile reads like a promotion: `dev → staging` means "make staging's
schema match dev". The profile **target is the database that changes** — the
TUI generates a bundle that moves the target toward the source, and dry run,
apply and history all use the target. (The CLI takes the same two databases in
the other order: `pgsd diff <current> <desired>`, i.e. `<target> <source>` in
profile terms.)

## Profiles

The configuration file contains a top-level `profiles` list. Each profile has
`name`, `source`, `target`, `schemas`, `ignore_patterns`, and `mode`. A
connection has `host`, `database`, `user`, optional `port` (default `5432`), and
optional `password` (default empty). `schemas` defaults to `[public]`,
`ignore_patterns` to `[]`, and `mode` to `schema-only`.

```yaml
profiles:
  - name: dev → staging
    source:              # schema to promote (not modified)
      host: localhost
      port: 5432
      database: app_dev
      user: app
    target:              # database the bundle is applied to
      host: localhost
      port: 5432
      database: app_staging
      user: app
    schemas: [app]
    ignore_patterns: []
    mode: schema-only
```

Profile path precedence:

1. An explicit path supplied by the app.
2. `PGSCHEMADIFF_CONFIG` (with `~` expanded).
3. `./config/profiles.yaml`, if it exists in the current directory.
4. `$XDG_CONFIG_HOME/pgschemadiff/profiles.yaml`, or
   `~/.config/pgschemadiff/profiles.yaml` when `XDG_CONFIG_HOME` is unset.

Avoid storing credentials in committed files. If a profile must contain a
password, protect the file and its backups. The TUI omits profile passwords and
DSNs from its connection and settings views.

The TUI includes schemas from `schemas`. Non-empty `ignore_patterns` and modes
other than `schema-only` are currently rejected by comparison; they are not
applied as filters.

## Screens

- **Connection** — source and target profile details, included schemas, saved
  profiles, profile selection, and **Test both** to compare the selected pair.
  SSL, server version, latency, and size currently display as `n/a`.
- **Overview** — added, modified, dropped, and blocked counts plus a table of
  changes, risk, and reasons. Select a row to open its Diff view.
- **Diff** — one delta's risk reason and source/target definitions. Choose
  `side`, `inline`, or `tree`; generated forward SQL appears after a plan exists.
  Rollback SQL is not generated.
- **Migration** — select a maximum risk, generate a plan, preview `up.sql`,
  inspect transaction units and risk reasons, choose an existing output
  directory, and save a bundle. Rollback tab contains notes only. No lock-time
  or row-count estimator is provided.
- **Apply** — selected target, validated saved bundle, risk/unit summary,
  lock/statement timeouts, connectivity-only dry-run, apply progress, and event
  log.
- **History** — persisted runs for the selected target, run details, checksum,
  status, and unit timeline; refresh to query again.
- **Settings** — read-only theme, runtime diff mode, apply timeout defaults,
  profile path, and a redacted profile summary.

## Keyboard and command palette

Global keys: `Escape` leaves command mode, `?` opens help, `:` enters the
command bar, `Ctrl+B` toggles the sidebar, and `Ctrl+T` tests both configured
connections. Navigation chords are `gc` (Connection), `go` (Overview), `gd`
(Diff), `gm` (Migration), `ga` (Apply), `gh` (History), and `gs` (Settings).
`gT` toggles between the mocha and latte themes, `/` focuses sidebar search,
and `ZZ` quits.

The help screen lists these command-palette commands:

| Command | Action |
|---|---|
| `:o` / `:overview` | Open Overview. |
| `:d` / `:diff [qualified-name]` | Open Diff or select a matching delta. |
| `:m` / `:migration` | Open Migration. |
| `:a` / `:apply [--dry-run]` | Open Apply; `--dry-run` starts a connectivity check. |
| `:h` / `:history` | Open History. |
| `:c` / `:conn` / `:connection` | Open Connection. |
| `:conn switch <profile>` | Select a profile by name. |
| `:rollback <id>` | Select a history run; rollback is unavailable. |
| `:set bg=mocha\|latte` | Set theme. |
| `:s` / `:settings` | Open Settings. |
| `:help` / `:?` | Show help. |
| `:q` / `:quit` | Quit. |

## Apply confirmation

Save a bundle in Migration, then open Apply. The TUI reads and validates the
bundle before enabling dry-run or apply. Dry-run checks target connectivity
only; it runs no SQL and does not touch migration history. Every real apply
opens a confirmation modal showing the target and unit/delta counts. Destructive
units require the explicit **Approve destructive apply** action. A BLOCKED
bundle cannot proceed. Cancelling an apply does not undo earlier completed
units; an in-flight non-transactional statement may need manual inspection.
