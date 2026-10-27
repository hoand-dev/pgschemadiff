# P5-I18N-01 — Implementation plan

**Spec:** `docs/specs/2026-10-27-p5-i18n-01-message-catalog-design.md` (read it first; it wins on any conflict).
**Date:** 2026-10-27

Files you may touch: new `src/pgschemadiff/presentation/i18n.py` and the
catalog module(s); `presentation/cli/**/*.py`; `tests/unit/presentation/cli/**`,
new `tests/unit/presentation/test_i18n.py`; `docs/guide/cli.md`; `README.md`.
No application/domain/infrastructure changes.

TDD for each step. Never change an English message's text; if two call sites
share a text, they may share a key.

## Step 1 — Inventory

List every human-facing message in `presentation/cli/**` (file, line, text,
in/out of scope per the spec). Keep it in the final report (table). This is
the source for the catalog keys and the AST allow-list.

## Step 2 — i18n core

Tests first (selection precedence, fallback, unknown key, parity helper).
Implement `i18n.py` + empty-ish catalogs. Add `PGSD_LANG=en` to
`tests/unit/presentation/cli/conftest.py`.

## Step 3 — Catalog and call sites

Move messages command by command (`inspect`, `diff`, `generate`, `report`,
`apply`, `output.py`, `main.py` if any). After each command run its tests;
they must pass without edits to expected English strings.

## Step 4 — Vietnamese texts

Write all `VI` entries following the spec's style rules. Re-read each one for
diacritics, natural phrasing and verbatim option names/placeholders.

## Step 5 — Tests

Parity, Vietnamese CLI tests (spec list), byte-identical stdout check, AST
guard with commented allow-list.

## Step 6 — Docs and verification

Docs per spec. Full gate (paste tails). If `mypy` reports missing `py.typed`
for installed packages, the environment is broken: stop and report; do not
repair it. Report: inventory table, catalog module choice, any message you
could not classify.
