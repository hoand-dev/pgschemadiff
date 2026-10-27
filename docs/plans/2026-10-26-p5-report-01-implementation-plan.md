# P5-REPORT-01 — Implementation plan

**Spec:** `docs/specs/2026-10-26-p5-report-01-html-report-design.md` (read it first; it wins on any conflict).
**Date:** 2026-10-26

Files you may touch:
- new: `src/pgschemadiff/presentation/report/{__init__,model,html}.py`,
  `src/pgschemadiff/presentation/cli/commands/report.py`
- edit: `presentation/cli/main.py` (register `report`, add `html` to
  `diff --format`), `presentation/cli/commands/diff.py`,
  `docs/guide/cli.md`, `README.md`
- tests: `tests/unit/presentation/report/` (new, with `__snapshots__`),
  `tests/unit/presentation/cli/test_diff.py`, new
  `tests/unit/presentation/cli/test_report.py`, one integration test
  (`tests/integration/test_report.py` or an extension of
  `tests/integration/test_docs_cookbook.py`).

TDD for every step. Keep existing messages and exit codes. Check
`lint-imports` after step 1 (presentation may import application; it must not
import infrastructure except through existing composition/CLI patterns).

## Step 1 — Model

Tests first: `from_comparison` builds rows identical to the summary's data
(use `assess_deltas` + `target_label`), totals per level, database names;
`from_bundle` maps `ValidatedBundle` assessments, units and statements.
Implement `presentation/report/model.py`.

## Step 2 — Renderer

Tests first: escaping (hostile strings in every field), CSP meta, no `<script`,
determinism, empty-diff text, footer notes; syrupy snapshots for empty diff,
realistic diff and bundle report. Implement `presentation/report/html.py`.
Keep CSS short; badge text always present.

## Step 3 — `pgsd diff --format html`

Tests first in `test_diff.py`: stdout is the rendered HTML for a fake
comparison; `--max-risk` gate still exits 2 after output; sentinel password in
URLs never appears. Wire it: `diff.py` needs the snapshots, so use
`composition.compare_conninfo` result (not only `.deltas`) for this format;
keep the JSON/summary paths unchanged.

## Step 4 — `pgsd report`

Tests first in `test_report.py` (happy path to stdout and to `--out`, invalid
bundle exit 2, existing `--out` exit 2, missing parent exit 2). Implement
`commands/report.py` using `FilesystemBundleReader` + `load_bundle` and
`output.error`. Register in `main.py` with help text.

## Step 5 — Integration

One PG18 test: seed two databases (reuse a cookbook recipe's SQL or a small
inline schema), `generate`, then `report` the bundle; assert every delta ID
from the manifest appears and the HTML has the CSP tag.

## Step 6 — Docs and verification

Update `docs/guide/cli.md` and README. Run the full gate (paste tails) and
`uv run --no-sync pytest tests/integration --collect-only -q -p no:cacheprovider`.
Report files, any spec gap, anything left open.
