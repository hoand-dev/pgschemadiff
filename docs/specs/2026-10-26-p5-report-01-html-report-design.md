# P5-REPORT-01 — HTML report design

**Status:** Approved by reviewer; implementation complete (CI `2003b75`).
**Date:** 2026-10-26
**Task:** `docs/TASKS.md` P5-REPORT-01 "HTML diff report" ·
roadmap row "DeltaSet/manifest → report; escape output, offline render, nội dung khớp CLI"
**Plan:** `docs/plans/2026-10-26-p5-report-01-implementation-plan.md`

## Goal

A single self-contained HTML file a reviewer can open offline (or attach to a
pull request / change ticket) that shows exactly what the CLI shows: the same
delta IDs, risk levels, kinds, target labels and reasons — plus, for a saved
bundle, the execution units and SQL.

## Entry points

1. `pgsd diff <current> <desired> --format html` — report of a live
   comparison, written to stdout (redirect to a file). Rows come from
   `assess_deltas` and `target_label`, exactly like `--format summary`.
   `--max-risk` keeps working after the report is printed (exit 2 on
   failure), as for the other formats.
2. `pgsd report BUNDLE_DIR [--out FILE]` — report of a saved bundle, read with
   `FilesystemBundleReader` + `load_bundle` (so checksums are verified; an
   invalid bundle exits 2 with the existing "Invalid migration bundle"
   message). No database access. Writes to `--out` (must not already exist;
   parent must exist; exit 2 otherwise) or stdout when omitted.

## Report content

Common header:
- Title "pgschemadiff report", tool version, generation time (UTC, ISO 8601).
- For `diff`: the two database **names** from the snapshots
  (`SchemaComparisonResult.source.name` / `.target.name`), labelled
  "current" and "desired". Never URLs, hosts, users or DSNs.
- For `report`: bundle id, slug, created_at, delta count, overall max risk,
  `up.sql` SHA-256.

Body:
- Risk totals: one count per level (safe, warning, dangerous, destructive,
  blocked) — same numbers as the summary totals line.
- Changes table in generator order: ID, level (coloured badge + text, never
  colour alone), kind, target, reason. Bundle report adds "reversible" and the
  reversibility reason from the manifest.
- Bundle report only: execution units table (index+1, transactional or not,
  max risk, delta IDs, `up.sql` line range) and, per unit, its statements in a
  `<pre>` block with line numbers.
- Footer: "Risk levels are static classifications, not runtime estimates" and,
  for bundles, "`down.sql` is notes only; no automatic rollback".
- Empty diff: header plus "No schema changes."

## Rendering rules

- Module: `presentation/report/html.py` (presentation layer; pure function
  `render_report(model) -> str`), model types in `presentation/report/model.py`
  (frozen dataclasses: `ReportRow`, `ReportUnit`, `ReportModel`) with two
  builders: `from_comparison(result, assessments, *, generated_at)` and
  `from_bundle(bundle, *, generated_at)`.
- Stdlib only (`html.escape(..., quote=True)` on **every** interpolated value,
  including attributes). No Jinja, no new dependencies.
- Self-contained and offline: inline `<style>`, no scripts, no external
  fonts/images/links. `<meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src 'unsafe-inline'">`.
- Light and dark via `prefers-color-scheme`; readable when printed.
- Deterministic: same input and `generated_at` → byte-identical output
  (snapshot-tested). The CLI passes the current UTC time; tests inject it.
- UTF-8, `<!doctype html>`, `lang="en"`.

## Non-goals

- No JavaScript filtering/sorting, no charts, no PDF.
- No report written into the bundle directory (bundle format and checksums
  stay unchanged).
- No TUI integration.
- No i18n (P5-I18N-01 may translate later).

## Safety

- Escaping test with names/reasons/SQL containing `<script>`, `"`, `'`, `&`,
  `</pre>`: output contains only escaped forms; the CSP meta tag is present;
  no `<script` substring anywhere.
- Credential test: report from a comparison whose snapshot names are benign
  while the CLI URLs contain a sentinel password — sentinel never appears.
- `--out` refuses to overwrite.

## Tests

- Unit (model + render): snapshot tests for empty diff, realistic diff,
  bundle report; escaping; determinism; CSP; totals match summary totals for
  the same assessments; rows identical (ID, level, kind, target, reason) to
  `diff --format summary` for the same fake comparison.
- CLI: `diff --format html` (stdout HTML; `--max-risk` still gates);
  `report` happy path, invalid bundle (exit 2), `--out` exists (exit 2),
  missing parent (exit 2), stdout mode.
- Integration (CI): extend the cookbook test or add one test that generates a
  bundle on PG18 and renders `pgsd report` for it, asserting each delta ID
  appears.

## Docs

`docs/guide/cli.md` gains `--format html` and `pgsd report`; README quickstart
gets one `pgsd report` line.

## Done when

Gate green, CI green, docs updated, no new dependency.
