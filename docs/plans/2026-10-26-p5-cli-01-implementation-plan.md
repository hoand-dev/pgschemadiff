# P5-CLI-01 — Implementation plan

**Spec:** `docs/specs/2026-10-26-p5-cli-01-cli-ux-design.md` (read it first; it wins on any conflict).
**Date:** 2026-10-26

Files you may touch:
- new: `src/pgschemadiff/presentation/cli/output.py`, `src/pgschemadiff/presentation/timeouts.py`
- edit: `presentation/cli/main.py`, `presentation/cli/commands/{diff,generate,apply}.py`,
  `presentation/composition.py`, `presentation/tui/app.py` (imports only),
  `application/migration/{generate,render}.py` (label dedup only), `README.md` (exit codes)
- tests: `tests/unit/presentation/cli/*`, `tests/unit/presentation/test_composition.py`,
  `tests/unit/application/migration/*` (only if the label move requires it), new test files as needed.

Rules: TDD for every step (failing test first). Keep every existing message
string unchanged unless the spec changes it. Run the targeted tests after each
step; run the full gate at the end.

## Step 1 — Helper move (no behaviour change)

1. Create `presentation/timeouts.py::parse_timeout` (copy of `_parse_timeout`,
   same messages, same limits) and `composition.check_connectivity` (copy of
   `_check_connectivity`).
2. Point `cli/commands/apply.py` and `tui/app.py` at the public names; remove
   the private copies. Update tests that monkeypatch
   `apply_command._check_connectivity` to patch the name where it is now
   looked up. Move the `_parse_timeout` tests to target `parse_timeout`.
3. Verify: `grep` shows no `presentation.cli` import in `presentation/tui/`.

## Step 2 — `target_label` dedup

1. One public `target_label(delta)` replacing both private copies (pick a
   module both `generate.py` and `render.py` can import without a cycle).
2. Existing manifest and risk-gate tests/snapshots must pass unchanged.

## Step 3 — Output module

1. Tests first for `output.py`: `error` prints `Error: …` to stderr and
   raises `typer.Exit(code)`; `progress` prints only when stderr is a
   terminal; `risk_text` styles; with `NO_COLOR=1` no ANSI; with a forced
   terminal ANSI present; a markup-like string such as `[red]x[/]\` prints
   literally. Note the CLI test conftest sets `NO_COLOR`/`TERM=dumb`; tests
   that need color override them locally.
2. Implement per spec (consoles created per call, markup off).

## Step 4 — Progress plumbing

1. `composition.compare_conninfo(..., on_phase=None)`: inspector proxy that
   reports `inspect-source`, `inspect-target`, `compare`. Test with fake
   inspectors (order of phases, `None` default unchanged behaviour).
2. `compare_urls` in `cli/commands/diff.py` forwards `on_phase`.

## Step 5 — `pgsd diff`

1. Load `--renames` before connecting; invalid → exit 2 with
   `Error: Invalid renames file: <message>`.
2. `--format json|summary` (default json, unchanged bytes) and
   `--max-risk` (optional) per spec, using `assess_deltas` for IDs/levels and
   `target_label` for labels.
3. Wire progress phases (`[1/3]…[3/3]`).
4. Route existing error messages through `output.error` (same text, same codes).

## Step 6 — `pgsd generate`

1. Pre-connect validation: `--max-risk blocked` and `--out` existence → exit 2.
2. `--renames` as in step 5.
3. Progress `[1/5]…[5/5]`; stderr summary with per-level counts; stdout only
   the bundle path.
4. Existing error messages through `output.error`.

## Step 7 — `apply`, root help, README

1. `apply`: route `_exit` through `output.error` / plain stderr with the same
   text and codes; color the `failed` event line red on a terminal. No
   behaviour change otherwise.
2. Root `--help` epilog: exit-code table (spec). Test that `pgsd --help`
   lists codes 0–3.
3. `README.md`: "Exit codes" section under Quickstart with the same table;
   add `pgsd diff --format summary --max-risk dangerous` to the quickstart.

## Step 8 — Verification and report

Full gate from the common rules; paste tails. Also run
`uv run --no-sync pytest tests/unit/presentation -q -p no:cacheprovider`.
Report: files, the module chosen for `target_label`, any choice the spec did
not fix, anything left open. Integration tests are CI only — say so.
