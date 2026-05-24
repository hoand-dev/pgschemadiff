# AI_STATE.md
_Last updated: 2026-05-24_

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI (Textual, Python 3.13)
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/elegant-albattani-0MjWg` — 1 commit ahead of `main` (same content as main; no unique work yet).

---

## Current Project Phase
**Phase 0 — Prototype** (Home screen only, flat-file layout, cannot run)

---

## CI / PR Status
- **CI**: configured on `determined-goodall-KGag4` branch only — NOT on `main`
- **Open PRs**: 0
- **Open Issues**: 0

---

## Critical Blocker: Package Structure Mismatch

All source files live at **repo root** as flat files, but every import uses the full
`src/pgschemadiff/` package path. The app **cannot run** in its current form.

### Files at root → must move to `src/pgschemadiff/` hierarchy

| Root file | Target path |
|---|---|
| `__main__.py` | `src/pgschemadiff/__main__.py` |
| `app.py` | `src/pgschemadiff/presentation/app.py` |
| `home.py` | `src/pgschemadiff/presentation/screens/home.py` |
| `profile.py` | `src/pgschemadiff/domain/models/profile.py` |
| `profile_detail.py` | `src/pgschemadiff/presentation/widgets/profile_detail.py` |
| `profile_item.py` | `src/pgschemadiff/presentation/widgets/profile_item.py` |
| `yaml_loader.py` | `src/pgschemadiff/infrastructure/config/yaml_loader.py` |
| `profiles.yaml` | `config/profiles.yaml` |
| `styles.tcss` | `src/pgschemadiff/presentation/styles.tcss` |

### Files missing entirely
- All `__init__.py` files for each package directory
- `src/pgschemadiff/presentation/widgets/confirm_dialog.py` (imported by `home.py`, not in repo)
- `.gitignore`
- `.github/workflows/ci.yml`

---

## Work Done on Other Branches (not yet merged to main)

| Branch | What it contains | Mergeable? |
|---|---|---|
| `claude/determined-goodall-KGag4` | **Full src layout fix + confirm_dialog + .gitignore + CI + tests + uv.lock** | ✅ Best candidate to merge |
| `claude/stoic-pascal-LOygS` | Complete Clean Architecture re-design (12 ADRs, domain/application layers, CLI-first) | Divergent — different scope |
| `claude/elegant-albattani-yN6AK` | AI_STATE.md + TASK_INDEX.md only | Reference only |
| `claude/nice-brahmagupta-nkwW5` | TASK_INDEX.md (12 tasks) | Reference only |
| `claude/compassionate-hamilton-*` | Various partial src layout restructures | Superseded by KGag4 |
| `claude/determined-goodall-4R9qN` | .gitignore only | Superseded by KGag4 |
| `claude/fervent-thompson-dyTEq` | Code review notes | Reference only |

---

## What Works (verified in README, not runnable due to layout bug)
- App boot + load 4 profiles from YAML
- ↑↓ navigation, detail pane updates real-time
- `d` opens ConfirmDialog, confirming deletes profile from list
- `esc`/`Cancel` closes modal
- Footer shows key bindings from `BINDINGS`

## Technical Note
Textual 8.2.7 bug: do **not** extend `Vertical`/`Container` with complex `compose` —
inline compose into `Screen` directly. Already worked around in `home.py`.

---

## Roadmap (from README + prior planning)

| Phase | Item | Status |
|---|---|---|
| P0 | Home screen (list + detail + delete modal) | ✅ Done (but not runnable — layout bug) |
| P0 | Src layout restructure | ❌ BLOCKER |
| P0 | CI / lint / tests | ❌ Not on main |
| P1 | `screens/comparing.py` — async Worker + ProgressBar | ❌ |
| P2 | `screens/diff_explorer.py` — Tree widget, 3-column diff | ❌ |
| P3 | `screens/sql_preview.py` — RichLog + SQL highlight | ❌ |
| P4 | `infrastructure/postgres/inspector.py` — pg_catalog queries | ❌ |
| P5 | `domain/diff/comparator.py` — diff logic | ❌ |
| P6 | `domain/migration/generator.py` — SQL migration generation | ❌ |

---

## Next Execution Target
**T-01** — Implement src layout restructure (or cherry-pick `determined-goodall-KGag4`).
This is the gating blocker for all subsequent work.
