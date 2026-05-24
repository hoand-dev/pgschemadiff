# TASK_INDEX.md — pgschemadiff

_Last updated: 2026-05-24_

## Execution Queue (priority order)

### P0 — Blockers (app won't run without these)

| ID | Task | Depends on | Status |
|---|---|---|---|
| T-01 | Create `src/pgschemadiff/` package structure with all `__init__.py` files | — | TODO |
| T-02 | Move flat root files into correct `src/` paths | T-01 | TODO |
| T-03 | Implement `confirm_dialog.py` (`ConfirmDialog` modal widget) | T-01 | TODO |
| T-04 | Move `profiles.yaml` → `config/profiles.yaml` (matches `__main__.py` lookup) | — | TODO |
| T-05 | Verify app boots: `uv sync && uv run python -m pgschemadiff` | T-01..T-04 | TODO |

### P1 — Test coverage (no tests exist)

| ID | Task | Depends on | Status |
|---|---|---|---|
| T-06 | Write unit tests for `Profile` / `ConnectionInfo` models | T-01 | TODO |
| T-07 | Write unit tests for `ProfileLoader` (YAML round-trip) | T-01 | TODO |
| T-08 | Write Textual Pilot tests for `HomeScreen` (navigate, delete flow) | T-01, T-03 | TODO |

### P2 — Next screens (roadmap)

| ID | Task | Depends on | Status |
|---|---|---|---|
| T-09 | `screens/comparing.py` — async Worker + ProgressBar loading screen | T-05 | TODO |
| T-10 | `screens/diff_explorer.py` — Tree widget, 3-column diff view | T-09 | TODO |
| T-11 | `screens/sql_preview.py` — RichLog with SQL syntax highlight | T-10 | TODO |

### P3 — Core domain logic

| ID | Task | Depends on | Status |
|---|---|---|---|
| T-12 | `infrastructure/postgres/inspector.py` — real `pg_catalog` queries via psycopg | T-05 | TODO |
| T-13 | `domain/diff/comparator.py` — schema diff logic | T-12 | TODO |
| T-14 | `domain/migration/generator.py` — generate SQL migration from diff | T-13 | TODO |

### P4 — Wiring stubs (currently show notifications)

| ID | Task | Depends on | Status |
|---|---|---|---|
| T-15 | Wire `n` key → New profile dialog/form screen | T-05 | TODO |
| T-16 | Wire `e` key → Edit profile dialog/form screen | T-05 | TODO |
| T-17 | Wire `enter` / Compare button → `ComparingScreen` | T-09 | TODO |
| T-18 | Wire "Test connection" button → async psycopg connect check | T-12 | TODO |

### P5 — Infrastructure & polish

| ID | Task | Depends on | Status |
|---|---|---|---|
| T-19 | Set up CI (GitHub Actions: ruff, mypy, pytest) | T-06..T-08 | TODO |
| T-20 | Profile save-back after delete (persist to `config/profiles.yaml`) | T-04 | TODO |
| T-21 | Remove unused `profile_detail.py` from final package | T-02 | TODO |

## Dependency Graph

```
T-01 (src/ tree)
  └── T-02 (move files)
  └── T-03 (confirm_dialog)
  └── T-06 (model tests)
  └── T-07 (loader tests)
T-04 (config/ dir)
T-01 + T-02 + T-03 + T-04
  └── T-05 (verify boot)
      └── T-08 (pilot tests)
      └── T-09 (comparing screen)
          └── T-10 (diff explorer)
              └── T-11 (sql preview)
      └── T-12 (inspector)
          └── T-13 (comparator)
              └── T-14 (generator)
      └── T-15 (new profile)
      └── T-16 (edit profile)
      └── T-17 (compare wiring) — needs T-09
      └── T-18 (test conn) — needs T-12
T-06 + T-07 + T-08
  └── T-19 (CI)
```

## Next Execution Target

**Start with T-01 → T-02 → T-03 → T-04 → T-05** (unblock the app first, in order).

T-03 (`confirm_dialog.py`) can be done in parallel with T-02 once T-01 is done.  
T-04 is independent and can go anytime.
