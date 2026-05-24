# AI_STATE.md — pgschemadiff

_Last updated: 2026-05-24_

## Project Summary

**pgschemadiff** is a PostgreSQL schema diff & migration TUI tool built with Python + Textual (Catppuccin Mocha theme). Target: compare two PG databases and generate migration SQL.

## Repository State

| Item | Value |
|---|---|
| Active branch | `claude/elegant-albattani-FL2VU` |
| Commits ahead of main | 12 files (entire project bootstrapped on this branch) |
| Open PRs | 0 |
| Open Issues | 0 |
| CI | Not configured |

## Current Architecture

The prototype lives **flat in the project root**. The `pyproject.toml` declares a `src/pgschemadiff` layout but that directory structure **does not exist yet** — this is the primary blocker.

### Files at root (prototype drafts)

| File | Role | Status |
|---|---|---|
| `__main__.py` | Entry point (`python -m pgschemadiff`) | Draft — imports from non-existent package paths |
| `app.py` | Textual `App` subclass | Draft |
| `home.py` | `HomeScreen` — list + detail pane | Draft — working logic |
| `profile.py` | `Profile`, `ConnectionInfo` Pydantic models | Draft |
| `profile_item.py` | `ProfileListItem` widget | Draft |
| `profile_detail.py` | `ProfileDetail` widget | **Unused** (inlined into HomeScreen) |
| `yaml_loader.py` | `ProfileLoader` — YAML read/write | Draft |
| `styles.tcss` | Catppuccin Mocha theme | Draft |
| `profiles.yaml` | 4 sample profiles | Needs to move to `config/` |
| `pyproject.toml` | uv project, Python 3.13 | Points to non-existent `src/` |
| `README.md` | Docs | Up to date |

### Missing (not yet created)

- `src/pgschemadiff/` full package tree + `__init__.py` files
- `src/pgschemadiff/presentation/widgets/confirm_dialog.py` — **imported but missing**
- `config/profiles.yaml` — profile loader looks for `config/profiles.yaml` but file is at root
- `tests/` — no tests at all (pytest in dev deps but unused)
- `screens/comparing.py` — roadmap item
- `screens/diff_explorer.py` — roadmap item
- `screens/sql_preview.py` — roadmap item
- `infrastructure/postgres/inspector.py` — pg_catalog queries
- `domain/diff/comparator.py` — diff logic
- `domain/migration/generator.py` — SQL generation

## Verified Working (per README)

- App boots, loads 4 profiles from YAML
- Navigate ↑↓ in list, detail panel updates real-time
- `d` key opens `ConfirmDialog` modal, Delete actually removes from list
- `esc`/Cancel closes modal back to home
- Footer auto-renders key bindings from BINDINGS

## Known Technical Notes

- Textual 8.2.7 has a bug extending `Vertical`/`Container` with complex compose — workaround: inline compose into Screen, not a separate widget class
- `psycopg[binary,pool]` declared in deps but not yet used (no DB connection screens yet)
- `profile_detail.py` at root is unused; logic was inlined into `HomeScreen`

## Architecture Decisions

- **src layout** via `hatchling` build backend — target is `src/pgschemadiff/`
- **Domain model**: `Profile` + `ConnectionInfo` as Pydantic frozen models (pure domain, no infra deps)
- **Infrastructure**: `yaml_loader.py` for config, `inspector.py` (future) for pg_catalog
- **Presentation**: Textual screens + widgets, Catppuccin Mocha TCSS theme

## Blocker Summary

1. **Package structure not created** — flat root files use `pgschemadiff.*` import paths that don't resolve without installing the package; the `src/` tree is missing
2. **`confirm_dialog.py` missing** — `HomeScreen` imports it, app won't run without it
3. **`config/profiles.yaml` path mismatch** — `__main__.py` looks for `./config/profiles.yaml` but file is at `./profiles.yaml`
