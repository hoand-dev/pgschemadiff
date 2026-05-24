# AI_STATE.md
_Last updated: 2026-05-24_

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI (Textual, Python 3.13)

## Branch
`claude/elegant-albattani-yN6AK` — 1 commit ahead of `main` (the `init` commit added all prototype files)

## CI / PR Status
- **No CI configured** (no `.github/workflows/`)
- **No open pull requests**
- **No open issues**

## Current Project Phase
**Phase 0 — Prototype** (Home screen only)

## Critical Blocker: Package Structure Mismatch

All source files are at **repo root** as flat files, but every import uses the full `src/pgschemadiff/` package path. The app **cannot run** in its current form.

### Files at root that must move into `src/pgschemadiff/` hierarchy:

| Current path | Target path |
|---|---|
| `app.py` | `src/pgschemadiff/presentation/app.py` |
| `home.py` | `src/pgschemadiff/presentation/screens/home.py` |
| `profile.py` | `src/pgschemadiff/domain/models/profile.py` |
| `profile_detail.py` | `src/pgschemadiff/presentation/widgets/profile_detail.py` |
| `profile_item.py` | `src/pgschemadiff/presentation/widgets/profile_item.py` |
| `yaml_loader.py` | `src/pgschemadiff/infrastructure/config/yaml_loader.py` |
| `__main__.py` | `src/pgschemadiff/__main__.py` |
| `profiles.yaml` | `config/profiles.yaml` |
| `styles.tcss` | `src/pgschemadiff/presentation/styles.tcss` |

### Files missing entirely:

- `src/pgschemadiff/__init__.py`
- `src/pgschemadiff/domain/__init__.py`
- `src/pgschemadiff/domain/models/__init__.py` (must re-export `Profile`, `ConnectionInfo`)
- `src/pgschemadiff/infrastructure/__init__.py`
- `src/pgschemadiff/infrastructure/config/__init__.py`
- `src/pgschemadiff/presentation/__init__.py`
- `src/pgschemadiff/presentation/screens/__init__.py`
- `src/pgschemadiff/presentation/widgets/__init__.py`
- `src/pgschemadiff/presentation/widgets/confirm_dialog.py` (imported by `home.py`)

## What Works (Verified in README)
- App boot + load 4 profiles from YAML
- ↑↓ navigation in list, detail pane updates real-time
- `d` opens ConfirmDialog modal, confirming deletes from list
- `esc`/`Cancel` closes modal
- Footer shows key bindings automatically

## Dependency on Textual Workaround
Textual 8.2.7 bug: do **not** extend `Vertical`/`Container` with complex `compose` — inline compose into Screen directly.

## Roadmap (from README)
1. `screens/comparing.py` — async Worker + ProgressBar
2. `screens/diff_explorer.py` — Tree widget, 3-column diff view
3. `screens/sql_preview.py` — RichLog + SQL syntax highlight
4. `infrastructure/postgres/inspector.py` — pg_catalog queries
5. `domain/diff/comparator.py` — diff logic
6. `domain/migration/generator.py` — SQL migration generation
