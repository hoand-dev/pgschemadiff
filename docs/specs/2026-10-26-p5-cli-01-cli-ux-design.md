# P5-CLI-01 — Full CLI UX design

**Status:** Approved by reviewer; implementation pending.
**Date:** 2026-10-26
**Task:** `docs/TASKS.md` P5-CLI-01 "Full CLI UX (progress, color, `--max-risk`)" ·
roadmap row "Risk/progress/options → UX hoàn chỉnh; test `--max-risk`, output ổn định, lỗi hữu ích"
**Plan:** `docs/plans/2026-10-26-p5-cli-01-implementation-plan.md`

## Current state (2026-10-26, `b02aaec`)

- `pgsd inspect | diff | generate | apply | tui` exist. Errors are fixed,
  redacted strings via `typer.echo(..., err=True)`; no color, no progress.
- `diff` prints only `DeltaSet` JSON. `generate` has `--max-risk`
  (default `dangerous`) and accepts `blocked`. `apply` prints per-statement
  event lines to stderr and has `--dry-run`, `--yes`, timeouts.
- `--renames` errors are swallowed into "Schema comparison failed." and a
  missing `--out` directory surfaces only after both databases were inspected
  as "Migration bundle writing failed."
- The TUI imports private CLI helpers `_check_connectivity` and
  `_parse_timeout` from `presentation/cli/commands/apply.py`.

## Goals

1. **Progress** on stderr for long phases, only when stderr is a terminal.
2. **Color** on stderr (errors, risk levels), only when stderr is a terminal
   and `NO_COLOR` is unset. Stdout stays plain and byte-stable.
3. **`--max-risk`** as a consistent risk gate: `generate` rejects `blocked`;
   `diff` gains an optional gate for CI use.
4. **Human summary** for `diff` (`--format summary`), using the same delta IDs
   and risk levels as `generate` and the TUI (`assess_deltas`).
5. **Useful errors** for user-input mistakes, raised before any database work.
6. **Stable, documented exit codes.**
7. Move the two helpers the TUI borrows out of the CLI module.

## Non-goals

- No change to JSON shapes (`inspect`, `diff --format json`, manifest).
- No `--quiet`, `--color`, or spinner/animated progress (non-TTY is already
  quiet; `NO_COLOR` covers color opt-out). Add later if asked.
- No i18n (P5-I18N-01), no HTML report (P5-REPORT-01).
- Presentation only, except one application-layer dedup: the public
  `target_label` helper described under `pgsd diff`. No domain change.

## Design

### Output module — `presentation/cli/output.py` (new)

```python
def stderr_console() -> Console   # Console(stderr=True, markup=False, highlight=False, emoji=False, soft_wrap=True)
def error(message: str, code: int) -> NoReturn   # prints "Error: …" (red on TTY) and raises typer.Exit(code)
def warn(message: str) -> None                   # yellow on TTY
def progress(step: int, total: int, label: str) -> None  # "[step/total] label" dim, only if console.is_terminal
def risk_text(level: RiskLevel | None) -> Text   # styled level name; None -> "none"
```

- Consoles are created per call so Typer's `CliRunner` stream swap and
  `NO_COLOR`/`FORCE_COLOR` are honoured (Rich resolves `sys.stderr` lazily).
- **Markup is off.** Untrusted text (object names, reasons, paths, rename
  file errors) is only ever passed as plain strings or `Text(...)` with a
  `style=` argument — never interpolated into a markup string.
- Risk styles: `safe` green, `warning` yellow, `dangerous` magenta,
  `destructive` red, `blocked` bold red.
- Message wording stays exactly as today wherever a message already exists;
  only styling is added. Existing tests asserting messages keep passing.

### Progress

`composition.compare_conninfo(..., on_phase: Callable[[str], None] | None = None)`
wraps both inspectors in a small presentation-side proxy that calls
`on_phase("inspect-source")` / `on_phase("inspect-target")` before each
`inspect()` and `on_phase("compare")` after the target snapshot returns.
No application-layer change. CLI maps phases to:

- `diff`: `[1/3] Inspecting source`, `[2/3] Inspecting target`, `[3/3] Comparing`
- `generate`: the same three plus `[4/5] Generating migration`, `[5/5] Writing bundle`

Printed via `output.progress` (TTY only). `apply` keeps its event lines.

### `pgsd diff`

New options:

- `--format [json|summary]`, default `json` (unchanged output).
- `--max-risk LEVEL`, default unset (no gate).

`summary` writes to stdout, one line per delta in generator order, then a
totals line:

```
d0001  destructive  drop_table      public.legacy   Drops table data.
…
5 changes: safe=2 warning=0 dangerous=1 destructive=2 blocked=0
```

Columns: delta ID, level, kind, target label, reason. Plain text on stdout
(colored level only when stdout is a terminal). Empty diff prints
`No schema changes.` and the totals line is omitted.

With `--max-risk`, after printing the chosen format, if any assessment exceeds
the level: stderr `Risk gate failed: <n> change(s) exceed max-risk=<level>.`
and exit **2**. `--max-risk blocked` is allowed on `diff` (it is a check, not
a generator) and therefore never fails.

Target labels must match the manifest. Today the same private helper exists
twice (`application/migration/generate.py::_target_label` and
`render.py::_target_label`, identical behaviour). Replace both with one public
`target_label(delta) -> str` in a module both can import without a cycle
(report which), and use it from the CLI. Behaviour unchanged; manifest
snapshots must not change.

### `pgsd generate`

- `--max-risk blocked` → exit 2 before connecting:
  `Error: --max-risk blocked is not allowed; BLOCKED changes are never generated.`
- `--out` must be an existing directory, checked before connecting:
  `Error: --out must be an existing directory.` exit 2.
- On success, stderr summary adds per-level counts:
  `Generated migration: deltas=N max-risk=<level> units=M (safe=… warning=… dangerous=… destructive=…)`.
  Stdout still prints only the bundle path (scripts depend on it).
- Risk gate failure (exit 2) keeps today's detailed message.

### `--renames` (diff and generate)

Loaded before connecting. `DiffError` from `load_renames` →
`Error: Invalid renames file: <message>` exit 2. The loader's message names
the user's own file and the parse error; it never contains connection data.

### Exit codes (all commands)

| Code | Meaning |
|---|---|
| 0 | Success (including `diff` with changes and no gate) |
| 1 | Runtime failure: connection, inspection, comparison, writing |
| 2 | Usage or policy: bad option/file, risk gate exceeded, invalid bundle, destructive not approved, BLOCKED bundle |
| 3 | Apply failed or was cancelled after it started |

Typer usage errors already exit 2. Document the table in the root `--help`
epilog and in `README.md` (new "Exit codes" section under Quickstart).

### Helper move (debt)

- `_parse_timeout` → `presentation/timeouts.py::parse_timeout(value, option) -> int`
  (same behaviour and messages).
- `_check_connectivity` → `presentation/composition.py::check_connectivity(conninfo)`.
- `cli/commands/apply.py` and `tui/app.py` import the public names. Existing
  tests that monkeypatch `apply_command._check_connectivity` are updated to
  patch the name where it is looked up.

## Safety

- No connection URL, DSN, user, host or driver message in any new output.
- Untrusted text never goes through Rich markup (test with a target name
  like `[red]x[/]\` and assert it is printed literally).
- Stdout content for `inspect`, `diff --format json`, and `generate` is
  unchanged byte for byte when stdout is not a terminal.

## Tests (unit, `tests/unit/presentation/cli/`)

- Progress: shown when stderr is a TTY (force via Rich `force_terminal`
  or monkeypatched `is_terminal`), absent otherwise.
- Color: ANSI present with forced terminal, absent with `NO_COLOR=1`.
- `diff --format summary`: ordering and IDs match `assess_deltas`, totals,
  empty diff, markup-like names literal.
- `diff --max-risk`: pass (exit 0), fail (exit 2, message), `blocked` never fails,
  gate applies to both formats.
- `generate --max-risk blocked` exit 2 without connecting; missing/non-dir
  `--out` exit 2 without connecting; summary counts on stderr; stdout is only
  the path.
- `--renames` invalid → exit 2 with the loader message, without connecting.
- Exit-code table: one test per code path not already covered.
- Helper move: `parse_timeout` and `check_connectivity` tests moved/adjusted;
  TUI still works (existing TUI tests pass).

## Done when

Gate green (ruff, format, mypy src+tests, lint-imports, unit tests), CI green
(integration unchanged), README exit-code section present, no private CLI
import left in `tui/app.py`.
