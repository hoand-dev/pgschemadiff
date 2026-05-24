# AI_STATE.md — pgschemadiff project state

_Last updated: 2026-05-24_

## Project overview

PostgreSQL schema diff & migration TUI built with Textual (Python 3.13). End goal: compare two Postgres databases, explore schema diffs, preview generated migration SQL — all in a terminal UI.

---

## Current project state: BROKEN / PROTOTYPE

### Branch
- Development branch: `claude/elegant-albattani-IOtyF`
- Base: `main` (1 commit ahead — "init" added all prototype files)

### What exists
| File | Status |
|---|---|
| `__main__.py` | Done — CLI entry with argparse, config path auto-detect |
| `app.py` | Done — Textual App shell, pushes HomeScreen |
| `home.py` | Done — HomeScreen: list/detail/delete with ConfirmDialog |
| `profile.py` | Done — Pydantic domain models (Profile, ConnectionInfo) |
| `profile_item.py` | Done — ListView item widget |
| `profile_detail.py` | Unused — ProfileDetail container inlined into HomeScreen |
| `yaml_loader.py` | Done — load/save profiles.yaml |
| `styles.tcss` | Done — Catppuccin Mocha theme |
| `profiles.yaml` | Done — 4 sample profiles for demo |

### Critical blockers

#### BLOCKER-1: Package structure is broken — app cannot run
All files sit at project root. Every file imports from `pgschemadiff.*` subpackage paths
(`pgschemadiff.domain.models`, `pgschemadiff.presentation.screens.home`, etc.) that don't
exist. `pyproject.toml` points `packages = ["src/pgschemadiff"]` but no `src/` directory
exists. Running the app currently fails with `ModuleNotFoundError`.

#### BLOCKER-2: `confirm_dialog.py` is missing
`home.py` imports `from pgschemadiff.presentation.widgets.confirm_dialog import ConfirmDialog`
but this file was never created (referenced in README but absent from repo).

### No CI / no tests / no open issues / no open PRs

---

## Roadmap (from README)

Feature screens and backend not yet started:
1. `screens/comparing.py` — loading screen, async Worker, ProgressBar
2. `screens/diff_explorer.py` — Tree widget, 3-column diff view
3. `screens/sql_preview.py` — RichLog with SQL syntax highlight
4. `infrastructure/postgres/inspector.py` — query pg_catalog
5. `domain/diff/comparator.py` — diff logic
6. `domain/migration/generator.py` — generate migration SQL

---

## Known technical constraints

- Textual 8.x has a bug when extending `Vertical`/`Container` with complex `compose()` — must inline compose into Screen, not create widget subclasses. Confirmed workaround already applied to HomeScreen.
- `psycopg[binary,pool]` listed in deps but unused until `comparing.py` connects to DB.
- Target Python: 3.13.
