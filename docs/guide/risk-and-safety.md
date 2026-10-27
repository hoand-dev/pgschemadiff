# Risk and safety

Risk levels are static classifications with reasons, not estimates of runtime,
lock duration, or row count. Treat them as review signals, not guarantees that a
change is safe in a particular workload.

## Levels

| Level | Meaning | Examples |
|---|---|---|
| **SAFE** | Usually does not rewrite or remove existing data. Still review dependencies and application behavior. | Add a nullable column without default/identity/generated expression; create an empty table. |
| **WARNING** | Operationally sensitive or may block depending on execution conditions. | Add a NOT NULL/default column; create a standalone index; rename a column. |
| **DANGEROUS** | May rewrite/validate data, change access behavior, or be irreversible. | Change a column type; add and validate a CHECK; add an enum value; change row-level security. |
| **DESTRUCTIVE** | Removes data or behavior. Explicit approval required to apply. | Drop a column, table, schema, or policy. |
| **BLOCKED** | The tool cannot safely generate or apply this change. | Replace a view when output-column names, order, or types change; an unsupported delta with no risk policy. |

Each assessment includes a reason. The [cookbook](cookbook/README.md) shows
actual summaries and SQL for common changes.

## Risk gates and approval

`diff --max-risk` reports changes and exits with code `2` if any change exceeds
the chosen ceiling. With no `--max-risk`, `diff` has no risk gate.

`generate --max-risk` refuses changes above the ceiling; its default is
`dangerous`. `BLOCKED` changes are never generated, even if `--max-risk
blocked` is requested. `apply` also refuses every bundle containing a BLOCKED
unit.

Destructive apply needs explicit approval. On a terminal, CLI asks for
confirmation; in a non-interactive run, pass `--yes`. The TUI requires a
confirmation modal for every real apply and labels destructive approval
explicitly. A dry run executes no migration SQL.

## Timeouts and review workflow

`apply` defaults to `--lock-timeout 5s` and `--statement-timeout 0` (`0` means
unlimited). Choose values for the target workload. A timeout limits waiting or
execution; it does not make a change online or guarantee that it can be safely
retried.

Recommended workflow:

1. Compare current/source with desired/target and review every delta and risk reason.
2. Check existing data, dependencies, application compatibility, and PostgreSQL-version behavior.
3. Generate a bundle with a limit that matches the changes you reviewed.
4. Inspect `README.md`, `manifest.json`, fingerprints and schema scope, `up.sql`, transaction units, and checksums.
5. Back up important data; run `apply --dry-run` to check source state and connectivity.
6. Apply during an appropriate window with chosen timeouts and explicit destructive approval if required. Use `--skip-source-check` only after reviewing why the source fingerprint differs.
7. Review the post-apply fingerprint result, verify application behavior, and compare again to confirm the target schema.

Dry-run does not prove permissions or future execution success. Completed units
can remain applied after a later unit fails or an apply is cancelled; see
[bundle resume behavior](bundles.md#failure-and-resume).
