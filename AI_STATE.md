# AI_STATE.md
_Last updated: 2026-06-20_

RUN_ID: 2026-06-20-1
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/clever-cray-9tgfsf` — 2 commits ahead of `main`, pushed. PR **#2** open → `main`.
(Prior state files named `claude/brave-gauss-f3he8w`; that branch is gone — its history is now on `main`. Corrected this run.)

---

## Current Project Phase
**Phase 1 — Infrastructure (MVP-A) — Batch C** — **M1 milestone reached this run.**

Phase 0 ✅. Phase 1 domain ✅ (P1-DOM-01..09). Phase 1 infra Batch A+B ✅ (P1-INFRA-01..05, P1-TEST-01).
Batch C: P1-INFRA-06 ✅ + P1-CLI-01 ✅ (in PR #2, awaiting CI + human merge). P1-TEST-02 still `ready`.

---

## CI / PR Status
- **Local**: ruff ✅ ruff format ✅ mypy strict ✅ import-linter 4/0 ✅ 552 unit tests ✅ (2026-06-20)
- **Open PR**: **#2** `claude/clever-cray-9tgfsf` → `main` — CI running (unit/mypy/ruff/arch green on first run; integration in progress).
- **main**: green at `a8b4174` (run 27857290956).

---

## Execution Queue
1. **(this run, awaiting CI)** PR #2 — verify CI green → mark Ready To Merge → escalate human merge (non-blocking).
2. **P1-TEST-02** — Inspector integration tests (`tests/integration/test_inspector.py`). `ready`. NOTE: no local Docker in the orchestrator sandbox → can only be validated by CI's PostgreSQL-18 integration job. Dispatch `qa-engineer`; expect to rely on CI for the gate.
3. **P0-CI-03** — Coverage gate (85%/80%) in CI. `ready`, low priority.
4. Phase 2 (Diff Engine) — blocked until Phase 1 infra fully merged.

## Next Actions
- Re-check PR #2 CI; if green → Ready To Merge + needs-human merge note. If red → dispatch `ci-recovery` (devops-engineer) on this branch.
- After PR #2 merges: dispatch P1-TEST-02.

## Ready To Merge
- _(pending CI green on PR #2)_

## Needs Human
- [ ] PR-2-merge | PR #2 reaches M1 (P1-INFRA-06 + P1-CLI-01) — orchestrator never merges (§7). Merge via squash/rebase once CI green + reviewed. | options: squash (preferred) / rebase | since: 2026-06-20-1  *(non-blocking)*
- [ ] repo-branch-protection | GitHub branch protection not confirmed: disallow merge commits, require linear history (§7.1 one-time human action). | since: 2026-06-20-1  *(non-blocking)*

## Key Architectural Decisions
- 2026-06-20 P1-CLI-01 introduced `application/inspect/inspect_schema.py` use case — CLI (presentation) delegates to it, never reaches into infrastructure logic directly (ADR-0005). CLI command is the composition root wiring Pool + PgCatalogInspector.
- 2026-06-20 `normalize_type()` applied inside `PgCatalogInspector._map_column` so domain `data_type` is always canonical (alias map int4→integer, varchar→character varying, etc.), preserving modifiers and `[]`.
- ADR-0012: single REPEATABLE READ tx per inspect() call.

## Run-History Note
- P1-INFRA-06 had been "DISPATCHED" as a background agent in the 2026-06-19 run but that session ended before the agent committed — the work was lost. Re-dispatched and completed this run. Lesson: do not end a run with an uncommitted background dispatch; block on completion + verify the commit before PERSIST.
