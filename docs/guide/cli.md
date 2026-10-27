# CLI reference

Run `pgsd --help` or `pgsd <command> --help` for the installed version. Options
below reflect the current command help.

## Root command

```bash
pgsd --help
```

| Option | Default | Meaning |
|---|---:|---|
| `--version` | off | Show version and exit. |
| `--log-level TEXT` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`; also reads `PGSD_LOG_LEVEL`. |
| `--help` | — | Show help. |

Running `pgsd` without a subcommand launches the TUI. `pgsd tui` does the same.

## `inspect`

```bash
pgsd inspect <conn-url> [--schema TEXT ...]
```

`<conn-url>` is required. Repeat `--schema` / `-s` to inspect selected schemas;
the default is all user schemas. Schema JSON goes to stdout. Connection and
inspection errors go to stderr.

## `diff`

```bash
pgsd diff SOURCE_URL TARGET_URL [OPTIONS]
```

Both URLs are required. Source is current; target is desired.

| Option | Default | Meaning |
|---|---:|---|
| `--schema`, `-s TEXT` | all user schemas | Repeat to limit schemas inspected. |
| `--renames PATH` | none | YAML or TOML explicit rename annotations. |
| `--format [json\|summary\|html]` | `json` | Structured JSON, human-readable risk summary, or a self-contained HTML report. |
| `--max-risk [safe\|warning\|dangerous\|destructive\|blocked]` | no gate | Exit with a policy error if any change is above this level. The report is still printed. |
| `--help` | — | Show help. |

Diff output goes to stdout. Errors and progress go to stderr.

## `report`

```bash
pgsd report BUNDLE_DIR [--out FILE]
```

Read and validate a saved migration bundle, then render its changes, execution
units, and SQL as a self-contained HTML report. No database connection is used.
The report goes to stdout by default; `--out FILE` writes to a new file whose
parent directory must already exist. Existing output files are never replaced.

## `generate`

```bash
pgsd generate SOURCE_URL TARGET_URL --out PATH [OPTIONS]
```

`--out` is required and must be an existing directory.

| Option | Default | Meaning |
|---|---:|---|
| `--out PATH` | required | Existing parent directory for the bundle. |
| `--schema`, `-s TEXT` | all user schemas | Repeat to limit schemas inspected. |
| `--renames PATH` | none | YAML or TOML explicit rename annotations. |
| `--max-risk [safe\|warning\|dangerous\|destructive\|blocked]` | `dangerous` | Reject changes above the selected risk. `blocked` is never a valid generation limit; BLOCKED changes are never generated. |
| `--name TEXT` | `diff` | Bundle slug. |
| `--help` | — | Show help. |

On success, the bundle directory path goes to stdout. Progress and the generated
risk summary go to stderr. If there are no changes, `No schema changes.` goes to
stderr and no bundle is written.

## `apply`

```bash
pgsd apply BUNDLE_DIR DB_URL [OPTIONS]
```

`BUNDLE_DIR` and `DB_URL` are required. `DB_URL` is the database that receives
the migration—normally the source/current database used for `diff` and
`generate`.

| Option | Default | Meaning |
|---|---:|---|
| `--lock-timeout TEXT` | `5s` | Maximum wait for the migration lock. Accepts `0`, an integer followed by `ms`, `s`, or `min`; maximum 24 hours. |
| `--statement-timeout TEXT` | `0` | Maximum statement execution time. Same syntax; `0` means unlimited. |
| `--dry-run` | off | Validate bundle and check connectivity; execute no migration SQL. |
| `--yes` | off | Approve destructive-risk units without an interactive prompt. |
| `--skip-source-check` | off | Skip the format 2 source-fingerprint guard after review. |
| `--help` | — | Show help. |

Apply progress and errors go to stderr; the final success result goes to stdout.
Dry-run guard results and unit summaries go to stdout. Format 2 bundles are
checked against their recorded source schema and scope before confirmation or
dry-run. A mismatch exits `2`; format 1 bundles remain usable with a warning.
`--skip-source-check` bypasses this check and prints a warning. A destructive
bundle needs interactive approval, or `--yes` when stdin is non-interactive.
BLOCKED bundles are always refused. Successful non-resumed applies report
whether the resulting schema matches the bundle's desired fingerprint; a
post-apply mismatch is warning-only.

## `tui`

```bash
pgsd tui
```

The command has no options other than `--help`. See the [TUI guide](tui.md).

## Rename-file formats

The same document shape is accepted as YAML (`.yaml` / `.yml`) or TOML
(`.toml`). Pass it to both `diff` and `generate` with `--renames`.

```yaml
renames:
  - kind: column
    from: app.users.old_email
    to: app.users.email
```

```toml
[[renames]]
kind = "column"
from = "app.users.old_email"
to = "app.users.email"
```

Use `kind: table` with two-part `schema.table` paths for table renames. Column
paths use `schema.table.column`. Quote identifiers in paths when they contain
uppercase letters, dots, or other characters requiring PostgreSQL quoting.

## Output, color, and logs

- `inspect`: JSON on stdout.
- `diff`: JSON, summary, or HTML on stdout.
- `report`: validated bundle report on stdout, or to the new `--out` file.
- `generate`: bundle path on stdout; progress and summary on stderr.
- `apply`: final success on stdout; progress and errors on stderr.
- Logging is written to stderr. `PGSD_LOG_LEVEL` defaults to `INFO`; valid
  levels are `DEBUG`, `INFO`, `WARNING`, and `ERROR`.
- `PGSD_LOG_FORMAT` selects `console` (default) or `json` logging.
- Set `NO_COLOR=1` to disable terminal color.

## Language

Set `PGSD_LANG=vi` for Vietnamese CLI messages or `PGSD_LANG=en` for English.
Values are case-insensitive; any other set value selects English. If
`PGSD_LANG` is unset, the CLI checks the first non-empty value among `LC_ALL`,
`LC_MESSAGES`, and `LANG`. A locale beginning with `vi` selects Vietnamese;
other locales, or no locale, select English. There is no language flag.

Errors, warnings, confirmation prompts, progress, the `generate` summary,
`apply` outcomes, and dry-run explanatory notes are translated. Data and
technical output remains unchanged: `inspect` JSON, `diff` JSON and summary
stdout, the generated bundle path, dry-run unit lines, and `apply` event
records. Typer help, HTML reports, the TUI, and logs are also English.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success, including a diff with changes when no risk gate fails. |
| `1` | Runtime failure such as connection, inspection, comparison, or writing failure. |
| `2` | Usage or policy failure: invalid option/file/bundle, exceeded risk gate, unapproved destructive change, BLOCKED bundle, or source-schema mismatch. |
| `3` | Apply failed or was cancelled after it started. Earlier completed units may remain applied. |
