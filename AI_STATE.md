# AI_STATE.md — pgschemadiff

_Last updated: 2026-05-24_

## Project

**pgschemadiff** — PostgreSQL schema diff & migration tool with a Textual TUI.
Language: Python 3.13 · Framework: Textual · Config: YAML · DB: psycopg3

## Branch

| Branch | Local SHA | Remote |
|--------|-----------|--------|
| `claude/elegant-albattani-SuEow` | `9e831f5` | **not pushed** |
| `main` | `251b514` | `origin/main` (GitHub has `9e831f5` = "init") |

> The "init" prototype was pushed directly to GitHub `main` by the user.
> The feature branch `claude/elegant-albattani-SuEow` holds the same commit locally
> but has never been pushed to origin.

## Current Phase

**Phase 1 — Home screen prototype (structurally broken)**

The prototype code exists but cannot be run. Two critical blockers prevent execution:

1. **Missing file**: `confirm_dialog.py` — imported by `home.py` but absent from repo.
2. **Wrong package layout**: source files sit flat at project root; all imports reference
   `pgschemadiff.presentation.screens.home`, `pgschemadiff.domain.models`, etc. — a
   `src/pgschemadiff/` hierarchy that does not exist. `pyproject.toml` declares
   `packages = ["src/pgschemadiff"]` which doesn't exist on disk.

## What Works (Once Structure Is Fixed)

- Home screen UI: profile list + detail pane, Catppuccin Mocha theme
- Profile model (Pydantic frozen, immutable)
- YAML load/save via `ProfileLoader`
- Delete profile with confirm modal (ConfirmDialog — needs to be created)
- Key bindings: ↑↓ navigate, enter compare (stub), n/e/d/q

## What Is Stubbed / Not Wired

| Feature | File | Status |
|---------|------|--------|
| Compare action | `home.py:_start_compare` | Shows notify only |
| New/Edit profile | `home.py:action_new_profile/edit` | notify only |
| Comparing screen | `screens/comparing.py` | **Does not exist** |
| Diff explorer | `screens/diff_explorer.py` | **Does not exist** |
| SQL preview | `screens/sql_preview.py` | **Does not exist** |
| Postgres inspector | `infrastructure/postgres/inspector.py` | **Does not exist** |
| Diff comparator | `domain/diff/comparator.py` | **Does not exist** |
| Migration generator | `domain/migration/generator.py` | **Does not exist** |

## Tests

None. No test directory, no pytest config.

## CI

None configured.

## Open GitHub Activity

- Pull requests: 0 open
- Issues: 0 open
- CI workflows: none

## Blockers

| ID | Blocker | Severity |
|----|---------|----------|
| B-001 | `confirm_dialog.py` missing — app crashes on import | CRITICAL |
| B-002 | Source files at root, not in `src/pgschemadiff/` package hierarchy | CRITICAL |
| B-003 | No tests — no way to verify correctness | HIGH |

## Next Execution Targets

See TASK_INDEX.md — execute T001, T002, T003 in sequence before anything else.
