# Getting started

## Install

```bash
uv tool install pgschemadiff
```

Or install with pipx:

```bash
pipx install pgschemadiff
```

The executable is `pgsd`. Use `PGPASSWORD`, `.pgpass`, or another protected
credential mechanism instead of putting passwords in connection URLs.

## Compare current with desired

Direction is consistent throughout the tool: **source is the current database
to change; target is the desired schema.** The generated bundle is applied to
the source/current database.

```bash
pgsd diff postgresql://app@localhost/current postgresql://app@localhost/desired --format summary
```

By default, `diff` prints JSON. `--format summary` prints a human-readable list
with risk levels and reasons. Review every change, including renames and
destructive operations.

## Generate a bundle

`--out` must name an existing directory:

```bash
mkdir -p ./migrations
```

```bash
pgsd generate postgresql://app@localhost/current postgresql://app@localhost/desired --out ./migrations
```

Generation does not apply SQL. The default risk limit is `dangerous`; use a
higher limit only after reviewing the changes. Inspect the bundle's `README.md`,
`manifest.json`, and `up.sql` before applying it.

## Validate, then apply

Run a connectivity-only dry run first:

```bash
pgsd apply ./migrations/<bundle-directory> postgresql://app@localhost/current --dry-run
```

Dry-run validates the bundle and checks target connectivity. It executes no
migration SQL and does not prove permissions or future execution success.

Apply the reviewed bundle to the same current/source database:

```bash
pgsd apply ./migrations/<bundle-directory> postgresql://app@localhost/current
```

Destructive units require interactive approval or `--yes` in a non-interactive
run. `BLOCKED` units cannot be applied. Back up important data, choose lock and
statement timeouts for the workload, and verify the resulting schema with
application-specific checks. `down.sql` is annotation only, not rollback SQL.

See [Risk and safety](risk-and-safety.md) and [Bundles](bundles.md) before
applying to production.
