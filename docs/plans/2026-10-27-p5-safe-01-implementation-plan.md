# P5-SAFE-01 — Implementation plan

**Spec:** `docs/specs/2026-10-27-p5-safe-01-source-fingerprint-guard-design.md` (read it first; it wins on any conflict).
**Date:** 2026-10-27

Files you may touch: `application/diff/fingerprint.py` (new),
`application/migration/{guard.py (new),model.py,generate.py,render.py,bundle.py}`,
`presentation/composition.py`, `presentation/cli/commands/{generate,apply}.py`,
`presentation/cli/main.py`, `presentation/tui/app.py`,
`presentation/tui/views/{apply,migration}.py` (only as needed for messages),
their tests and snapshots, new integration test
`tests/integration/test_source_guard.py`, docs listed in the spec, and add
the P5-SAFE-01 row to `docs/TASKS.md` Phase 5 table as `[ ]`.

TDD each step. Run targeted tests after each step, `lint-imports` after
steps 1–3.

## Step 1 — Fingerprint

Audit the domain snapshot models for volatile fields first; write the list in
the report. Tests, then `schema_fingerprint`.

## Step 2 — Manifest format 2

Tests for `load_bundle` (v1 still valid, v2 valid, v2 missing/invalid
fingerprint or `inspected_schemas` rejected, v3 rejected) and `render_bundle`
(v2 output, README scope line). Update syrupy snapshots deliberately
(`--snapshot-update` only for the render snapshots, then review the diff).
Add `inspected_schemas` to `MigrationPlan` and `generate_migration`.

## Step 3 — Guard use case

Tests with fake inspector and fake history reader for MATCH, mismatch,
SKIPPED_LEGACY, SKIPPED_RESUME. Implement `guard.py`. Check what the history
reader exposes (`list_history`) and reuse it; do not add a new port unless
required — if required, report why.

## Step 4 — Generate wiring

CLI generate and TUI migration pass fingerprints and scope. TUI test must
prove `source_fingerprint` comes from the profile **target** snapshot.

## Step 5 — Apply wiring

`composition.open_inspector` helper; CLI apply guard + `--skip-source-check` +
dry-run reporting + legacy warning + post-apply verification; TUI apply and
dry run guard. Keep all existing messages/exit codes for other paths.

## Step 6 — Integration test

`tests/integration/test_source_guard.py` per spec (mark `integration`).
Locally only `--collect-only`.

## Step 7 — Docs and verification

Docs per spec. Full gate (paste tails) + integration collect-only. Before
running the gate, reinstall nothing: if `mypy` reports missing `py.typed` for
installed packages, stop and report (the shared env is broken), do not try to
repair it. Report: files, volatile-field audit, snapshot changes, anything
left open.
