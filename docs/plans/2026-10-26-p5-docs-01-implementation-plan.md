# P5-DOCS-01 — Implementation plan

**Spec:** `docs/specs/2026-10-26-p5-docs-01-user-guide-design.md` (read it first; it wins on any conflict).
**Date:** 2026-10-26

Files you may create/edit: everything under `docs/guide/`, `docs/README.md`,
root `README.md` (link only), `tests/docs_cookbook.py` (recipe parser),
`tests/unit/docs/__init__.py`, `tests/unit/docs/test_cookbook_format.py`,
`tests/integration/test_docs_cookbook.py`. No production code.

## Step 1 — Gather facts (no writing yet)

1. Capture real `--help` output for `pgsd` and every sub-command
   (`NO_COLOR=1 COLUMNS=100 uv run --no-sync pgsd <cmd> --help`).
2. Read: `presentation/cli/**`, `presentation/composition.py`,
   `presentation/tui/app.py` (palette), `presentation/tui/screens/help.py`,
   `presentation/tui/screens/confirm_apply.py`,
   `application/sql_emit/risk.py`, `application/sql_emit/transaction.py`,
   `application/migration/{generate,render,bundle,apply}.py`,
   `infrastructure/postgres/applier.py` (history schema, resume),
   `infrastructure/config/rename_loader.py`, `domain/models/profile.py`,
   `config/profiles.yaml`, `docs/ui-design.md` §10, and the known-limits
   lines in `DAILY_LOG.md`.
3. Keep a private fact list (not committed) mapping each guide claim to its
   source file/test. Use it in the final report's "claims checked" section.

## Step 2 — Recipe parser and format test (TDD)

1. `tests/unit/docs/test_cookbook_format.py` first: parser returns blocks by
   info string; a recipe missing `sql current` fails; links in
   `docs/guide/**.md` resolve (relative paths only; ignore `http(s)://`).
2. Implement `tests/docs_cookbook.py` (stdlib only).

## Step 3 — Cookbook recipes

1. Write each recipe's `current` / `desired` SQL first.
2. Produce the `text summary` block by running the real pipeline in memory:
   write a throwaway script (scratch area, not committed) that builds the
   expected output the same way the CLI does, OR leave the summary block for
   CI to confirm — but never invent it. Preferred: derive levels, kinds and
   reasons by reading `risk.py`/comparators and the existing unit tests for
   the same delta kinds; mark in the report which summaries could not be
   machine-verified locally (Docker is unavailable).
3. `sql up` excerpts: take statements from emitter unit tests/snapshots for
   the same delta kinds.
4. If a recipe's scenario turns out unsupported or unsafe, rewrite it as a
   documented limitation and report it.

## Step 4 — Integration test

`tests/integration/test_docs_cookbook.py` per spec, reusing
`pg_test_dsn` / `pg_test_dsn2` fixtures. Locally only `--collect-only`.

## Step 5 — Guide pages

Write `README.md`, `getting-started.md`, `cli.md`, `tui.md`, `bundles.md`,
`risk-and-safety.md`, `limitations.md`, `cookbook/README.md` per spec.
Link everything; update `docs/README.md` and root `README.md`.

## Step 6 — Verification and report

Full gate from the common rules (paste tails), plus
`uv run --no-sync pytest tests/unit/docs -q -p no:cacheprovider` and
`uv run --no-sync pytest tests/integration/test_docs_cookbook.py --collect-only -q -p no:cacheprovider`.
Report: files, "claims checked" list (claim → source), summaries not verified
locally, any behaviour that looked like a bug (with evidence), anything left open.
