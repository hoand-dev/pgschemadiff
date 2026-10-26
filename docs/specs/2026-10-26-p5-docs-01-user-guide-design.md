# P5-DOCS-01 — User guide and safe-migration cookbook design

**Status:** Approved by reviewer; implementation pending.
**Date:** 2026-10-26
**Task:** `docs/TASKS.md` P5-DOCS-01 "User guide + safe-migration cookbook" ·
roadmap row "Implemented behavior → CLI guide, safe migration và rollback limitations; ví dụ phải chạy được"
**Plan:** `docs/plans/2026-10-26-p5-docs-01-implementation-plan.md`

## Goal

A user who has never seen the repository can install `pgsd`, compare two
databases, read the risk report, generate a bundle, and apply it safely —
and knows exactly what the tool does **not** do. Every cookbook example is
executed in CI, so the documentation cannot drift from behaviour.

## Principles

- **Describe implemented behaviour only.** Every claim is checked against the
  code, `--help` output, or tests. Nothing from the design-only TUI panels
  hidden in `docs/ui-design.md` §10 (AI review, dependency graph, lock/duration
  estimates, replica lag, executable rollback).
- **Direction convention stated once and used everywhere:** source =
  *current* database (the one you will change), target = *desired* schema;
  the bundle is applied to the source/current database.
- English, plain and short. No marketing. Commands in fenced `bash` blocks,
  one command per block where a user would copy it.
- No real hostnames, users or passwords. Use `postgresql://app@localhost/current`
  style placeholders and say passwords come from `PGPASSWORD`/`.pgpass` or the
  profile file.

## Deliverables (`docs/guide/`)

| File | Content |
|---|---|
| `README.md` | Guide index and the 30-second overview (what it compares, what it emits, what it never does). |
| `getting-started.md` | Install (`uv tool install` / `pipx`), direction convention, first `diff --format summary`, `generate`, `apply --dry-run`, `apply`. |
| `cli.md` | Reference for `inspect`, `diff`, `generate`, `apply`, `tui`: every option with default (from `--help`), output streams (stdout vs stderr), JSON vs summary, exit codes 0–3, timeouts syntax, `--renames` file format (YAML and TOML), `NO_COLOR`, logging env vars (`PGSD_LOG_LEVEL`, `PGSD_LOG_FORMAT`). |
| `tui.md` | `profiles.yaml` format (fields, schemas, mode, `ignore_patterns` currently rejected by compare), profile path resolution order (`PGSCHEMADIFF_CONFIG`, `./config/profiles.yaml`, XDG, `~/.config`), views and what each shows, key bindings and command palette commands exactly as `screens/help.py` and the palette implement them, apply confirmation flow. |
| `bundles.md` | Bundle layout (`manifest.json`, `up.sql`, `down.sql`, `deltas.json`, `README.md`), checksums, transaction units (transactional vs non-transactional, e.g. `CREATE INDEX CONCURRENTLY`), history tables in schema `pgschemadiff`, resume behaviour, what an interrupted non-transactional statement can leave (INVALID index). |
| `risk-and-safety.md` | Five risk levels with real examples from the classifier, `--max-risk` on `diff` (check) vs `generate` (gate, `blocked` refused), destructive approval (`--yes`, interactive prompt, TUI modal), BLOCKED never applied, lock/statement timeouts, recommended review workflow. |
| `limitations.md` | Supported object types; known limits (policy expressions referencing other relations and composite attribute type changes are not dependency-ordered; views depending on altered/dropped columns are not rebuilt; `down.sql` is notes only — no automatic rollback; data comparison not supported; profile `ignore_patterns` not applied by the TUI compare; `server_version` not shown). Each limit says what to do instead. |
| `cookbook/README.md` + one file per recipe | Safe-migration recipes (below). |

Also: root `README.md` links to `docs/guide/README.md`; `docs/README.md`
index lists the guide, this spec and plan.

## Cookbook recipes

Each recipe is one Markdown file with a fixed structure:

1. Title and when to use it.
2. ```` ```sql current ```` block — schema of the current database.
3. ```` ```sql desired ```` block — schema of the desired database.
4. ```` ```text summary ```` block — the exact stdout of
   `pgsd diff <current> <desired> --format summary`.
5. Short explanation of the generated SQL and its risk, with an
   ```` ```sql up ```` excerpt (statements that must appear in `up.sql`,
   checked by substring, so formatting-insensitive details may be omitted).
6. Operational advice (timeouts, approval, verification query).
7. Optional ```` ```yaml renames ```` block (at most one): written to a file and
   passed as `--renames` to both `diff` and `generate` (added during
   implementation for the rename recipe).

Recipes (adjust to actual behaviour; if the tool cannot do one safely, the
recipe documents the limitation instead of pretending):

| File | Scenario |
|---|---|
| `add-nullable-column.md` | Add a nullable column (SAFE). |
| `add-not-null-column.md` | Add a NOT NULL column with a default. |
| `create-index.md` | Add an index — emitted `CONCURRENTLY`, non-transactional unit. |
| `add-check-constraint.md` | Add a CHECK constraint — `NOT VALID` then `VALIDATE`. |
| `widen-column-type.md` | `integer → bigint` and its risk level. |
| `rename-column.md` | Rename with a `--renames` file instead of drop + add. |
| `drop-column.md` | Destructive change: gate, `--yes`, and data loss warning. |
| `add-enum-value.md` | `ALTER TYPE … ADD VALUE` in its own unit. |
| `row-level-security.md` | Enable RLS and add a policy (DANGEROUS). |

Recipes use their own schema name (e.g. `cookbook`) and `CURRENT_USER` for
roles; no role names.

## Executable documentation

- `tests/unit/docs/test_cookbook_format.py` (unit): every recipe file has
  exactly one `sql current`, one `sql desired`, one `text summary` block and
  zero or more `sql up` blocks; every link inside `docs/guide/` resolves to an
  existing file or anchor-free path.
- `tests/integration/test_docs_cookbook.py` (integration, CI), parametrized
  over recipe files: seed two fresh databases with the `current` / `desired`
  blocks; run `pgsd diff … --format summary` through Typer's `CliRunner`;
  assert stdout equals the `text summary` block (trailing whitespace
  normalised); run `generate` (`--max-risk destructive`) into `tmp_path` and
  assert each `sql up` excerpt is a substring of `up.sql`; apply the bundle
  with destructive approval; assert a second `diff` reports no changes.
- The recipe parser lives in the test package (e.g. `tests/docs_cookbook.py`),
  shared by both tests. No production code.

## Non-goals

- No changes to production code. If writing the docs reveals a bug, record
  it in the final report (with evidence) instead of fixing it here.
- No docs site generator (MkDocs etc.); plain Markdown on GitHub.
- No Vietnamese translation (P5-I18N-01 covers messages, not docs).
- Legacy/obsolete docs (`docs/api.md`, `docs/migration.md`, `PROGRESS.md`,
  `REVIEW.md`) are not rewritten; the guide index says they are not user docs.

## Done when

1. All files above exist, cross-linked, every statement backed by code/tests.
2. Unit format test passes locally; integration cookbook test passes in CI.
3. Gate green; `docs/README.md` and root `README.md` link the guide.
