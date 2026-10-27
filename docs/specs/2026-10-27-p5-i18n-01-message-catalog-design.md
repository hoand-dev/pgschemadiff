# P5-I18N-01 — EN + VI message catalog design

**Status:** Approved by reviewer; implementation complete (CI `98ac93f`).
**Date:** 2026-10-27
**Task:** `docs/TASKS.md` P5-I18N-01 "EN + VI message catalog" ·
roadmap row "Message keys → catalog EN/VI; test fallback và không hard-code message ngoài scope"
**Plan:** `docs/plans/2026-10-27-p5-i18n-01-implementation-plan.md`

## Goal

Human-facing CLI messages come from one catalog with English (default) and
Vietnamese texts, selected from the environment. Machine-readable output stays
English and byte-stable.

## Scope

**Translated** (≈70 call sites in `presentation/cli/**`): error, warning and
confirmation messages; progress lines (`[1/3] Inspecting source`); the
`generate` success summary on stderr; `apply` outcome lines ("Applied
migration: …", "Verified: …"); dry-run notes in prose ("Dry-run does not
prove …"); `report`/`--out` errors.

**Not translated** (stay English, unchanged bytes):
- stdout data: `inspect` JSON, `diff --format json`, `diff --format summary`
  (parsed by the cookbook test and by scripts), `generate`'s bundle path,
  dry-run unit lines (`unit 1/2: transactional; risk=…`).
- `apply` per-statement event lines (`unit 1/3 statement 2/5 started …`):
  log-like key=value records.
- Text produced by the application layer and embedded in a message (risk
  reasons, `RiskGateError` details, `MigrationError` text, rename-loader
  errors): kept as-is inside the translated wrapper.
- Typer `--help` texts, the HTML report, the TUI, bundle files, logs
  (structlog). Each can adopt the catalog later.

## Language selection

`presentation/i18n.py`:

```python
Language = Literal["en", "vi"]
def current_language() -> Language
def t(key: str, /, **params: object) -> str
```

- `PGSD_LANG` (`en` | `vi`, case-insensitive) wins. Any other value → `en`.
- Otherwise the first non-empty of `LC_ALL`, `LC_MESSAGES`, `LANG`; a value
  starting with `vi` (e.g. `vi_VN.UTF-8`) → `vi`; anything else → `en`.
- Resolved per call (cheap; lets tests and `CliRunner` set env freely).
- No CLI flag (env is enough; add `--lang` later if asked).

## Catalog

- `presentation/i18n_catalog.py` (or a package `presentation/i18n/` with
  `en.py`, `vi.py` — implementer's choice, report it): plain dicts
  `EN: dict[str, str]`, `VI: dict[str, str]`. Keys are dotted, stable,
  English-ish (`apply.error.connection_failed`, `diff.progress.inspect_source`).
- Templates use `str.format` named fields only (`{count}`, `{level}`); no
  positional fields, no format specs that differ between languages.
- `t` formats `VI[key]` when the language is `vi` and the key exists, else
  `EN[key]`. A key missing from `EN` raises `KeyError` (programming error).
- English texts are **exactly** today's messages, so every existing test that
  asserts a message keeps passing unchanged.

## Vietnamese texts

- Natural, concise Vietnamese with full diacritics; technical terms that users
  type or see in PostgreSQL stay as-is (`bundle`, `migration`, `--max-risk`,
  `--yes`, `SQLSTATE`, `INVALID index`, risk level names `safe`/`dangerous`…).
- Option names, exit-relevant hints and placeholders must be preserved
  verbatim.
- Example: `Error: Database connection failed.` →
  `Lỗi: Không kết nối được cơ sở dữ liệu.`;
  `Destructive migration requires --yes when stdin is non-interactive.` →
  `Migration có thay đổi phá huỷ cần --yes khi stdin không tương tác.`
- Errors keep a stable prefix per language (`Error:` / `Lỗi:`,
  `Warning:` / `Cảnh báo:`).

## Tests

- Parity: `EN` and `VI` have identical key sets, and each pair has identical
  placeholder sets (parse with `string.Formatter`).
- Fallback: a key present only in `EN` (inject via monkeypatch) renders English
  under `vi`; unknown key raises.
- Selection: `PGSD_LANG` precedence, locale variables, invalid values.
- Integration of CLI: with `PGSD_LANG=vi`, representative commands (connection
  failure in `diff`, risk gate in `generate`, BLOCKED bundle in `apply`,
  `report --out` exists) print the Vietnamese message and keep the same exit
  code; stdout data (summary/JSON) is byte-identical to `en`.
- Guard: an AST test over `presentation/cli/**/*.py` (excluding the catalog)
  fails if a string literal passed to `output.error`, `output.warn`,
  `output.progress`, `_exit`, `typer.confirm`, or `typer.echo(..., err=True)`
  is not produced by `t(...)` — allow-list the out-of-scope English outputs
  explicitly in the test with a comment per entry.
- CLI test conftest sets `PGSD_LANG=en` so a developer's Vietnamese locale
  cannot change test results.

## Docs

`docs/guide/cli.md`: "Language" section (env precedence, what is and is not
translated). README: one line.

## Done when

Gate green, CI green, docs updated, no new dependency.
