# AI_STATE.md
_Last updated: 2026-06-23_

RUN_ID: 2026-06-23-1
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/clever-cray-0zzng4` — pushed; **PR #4** open → `main` (P2-DOM-01a). Branched from `origin/main` at `f602f60` (clean, linear). This run also **consolidated the fragmented orchestrator state** onto this branch (see Run-History Note) — prior authoritative state lived only on side-branch `claude/clever-cray-192p05`, never merged.

---

## Current Project Phase
**Phase 2 — Diff Engine — STARTED.** Phase 1 core infra MERGED to main (M1 feature reached). Phase 2 entry task **P2-DOM-01a implemented** and in PR #4 (review). Proceeded per the prior run's documented `phase2-go-ahead` default-A pre-authorization.

Phase 0 ✅. Phase 1 domain ✅. Phase 1 infra ✅ MERGED (P1-INFRA-01..06, P1-TEST-01, P1-CLI-01). P1-TEST-02 `needs-human` (PR #3 human-closed; do NOT recreate).

---

## CI / PR Status
- **main**: green at `f602f60` (workflow `success`, 2026-06-22T04:21Z). Includes merged PR #2 (M1).
- **PR #4** `claude/clever-cray-0zzng4` → main — **P2-DOM-01a** (`domain/delta/` foundation), head `eb331e2`. Local gate green (ruff/format/mypy strict/import-linter 4-0/605 unit tests, independently re-run by orchestrator). **CI pending at persist time.** Session subscribed to PR #4 activity.
- **PR #2** `clever-cray-9tgfsf` → main: **MERGED** 2026-06-22 (M1).
- **PR #3** `claude/p1-test-02-integration` → main: **CLOSED, not merged** by human 2026-06-22.
- Stale remote branches (housekeeping, non-blocking): `claude/clever-cray-9tgfsf` (merged PR #2 head), `claude/clever-cray-192p05` + `claude/clever-cray-vqtao5` (prior orchestrator state branches, now superseded by this branch).

---

## Execution Queue
1. **(this run, awaiting CI)** PR #4 — verify CI green → mark Ready To Merge → escalate human merge (non-blocking). If red → `ci-recovery` (devops-engineer) on this branch.
2. **(blocked on P2-DOM-01a merge)** **P2-DOM-01b..f** — category delta modules (table/column/index/constraint/schema+extension). Independent of each other, **distinct file scopes** → parallelizable (worktree per writer, §6). Each ≤3 files + 1 done-condition.
3. **(blocked on P2-DOM-01a merge)** **P2-DIFF-08** — `topo_sort.py` (Kahn + cycle detection). Deps only P2-DOM-01a.
4. **P0-CI-03** — Coverage gate (85%/80%) in CI. `ready`, low priority. ⚠️ risk: a hard gate could turn CI red; validate headroom before enabling. Held.
5. **P1-INFRA-07** — Multi-conn `pg_export_snapshot`. Deferred (do not do yet unless single-conn benchmark fails).

## Next Actions
- Watch PR #4 CI (subscribed). On green → Ready To Merge + non-blocking human-merge note. On red → `ci-recovery`.
- A self check-in is armed (~1h) since webhooks don't deliver CI-success/merge transitions.
- After PR #4 merges: dispatch P2-DOM-01b..f (parallel, isolated worktrees — distinct files) + P2-DIFF-08.

## Ready To Merge
- None yet — **PR #4** CI pending. Becomes ready when CI green (0 open review-fix).

## Needs Human
- [ ] P1-TEST-02 | Inspector integration-tests PR (#3) was closed without merge by the human. | root cause: human declined the CI-only-validated integration tests (no local Docker to validate pre-merge). | options: (A) re-approach P1-TEST-02 differently and retry / (B) defer integration tests, proceed Phase 2 (currently in progress) / (C) leave M1 exit gate intentionally unmet. **Will NOT recreate without your call.** | since: 2026-06-22-1
- [ ] repo-branch-protection | GitHub branch protection not confirmed: disallow merge commits, require linear history (§7.1, one-time human action). | since: 2026-06-20-1  *(non-blocking)*
- [ ] stale-branches | Housekeeping: delete superseded remote branches `claude/clever-cray-9tgfsf`, `claude/clever-cray-192p05`, `claude/clever-cray-vqtao5`. | since: 2026-06-22-1  *(non-blocking)*

## Resolved This Run
- **phase2-go-ahead** (was non-blocking needs-human, default-A): ACTED. Proceeded autonomously with P2-DOM-01a per the prior run's documented default-A pre-authorization (Phase 2 is an approved plan; entry task was `ready`; pure additive domain code behind the human merge gate). Redirect anytime — say the word and I'll hold further Phase 2 dispatch.

## Key Architectural Decisions
- 2026-06-23 P2-DOM-01a (`domain/delta/` package): `DeltaOp` StrEnum discriminator = {CREATE, DROP, ALTER, RENAME, REPLACE, NO_CHANGE} — generic op categories, NOT per-object-kind (avoids enum explosion); concrete subclasses (b..f) narrow `op` to `Literal[DeltaOp.X]` + add payload, mirroring `domain/constraint.py`'s discriminated union. `DeltaBase.sort_key = (namespace, object_name, op.value)` → deterministic ordering for P2-DIFF-08 topo-sort tie-breaking + stable `pgsd diff` JSON output. `DeltaSet.__iter__` overrides Pydantic's field-iteration to yield delta items. No new ADR (no dependency/layer/output/CLI/PG-matrix change).
- 2026-06-22 Phase 2 decomposition (planner): `domain/delta.py` (40+ subclasses) split into `domain/delta/` package (base + per-category b..f) re-exported via `__init__.py`; engine/comparators/topo-sort/loaders in `application/diff/`; `pgsd diff` CLI = M2 gate.
- 2026-06-20 P1-CLI-01 `application/inspect/inspect_schema.py` use case — CLI delegates (ADR-0005); composition root wires Pool + PgCatalogInspector.
- 2026-06-20 `normalize_type()` applied inside `PgCatalogInspector._map_column` so domain `data_type` is always canonical.
- ADR-0012: single REPEATABLE READ tx per inspect() call.

## Run-History Note
- 2026-06-23: Found orchestrator state **fragmented across branches** — the authoritative 2026-06-22-1 run (PR #2 merged, PR #3 human-closed, Phase 2 decomposed) was committed only to `claude/clever-cray-192p05`, while `main` + the assigned working branch carried stale 2026-06-21 state. Reconciled to GitHub ground truth (live PR/CI), adopted the 192p05 state files onto the assigned branch `claude/clever-cray-0zzng4`, and will land it via PR #4 so state finally consolidates on `main`. Lesson (recurring): a single orchestrator working branch + always reconcile against live PR/CI, never just local state files.
- 2026-06-22: a parallel orchestrator session ran on `claude/clever-cray-vqtao5` (opened PR #3). Two concurrent orchestrator branches caused the drift above.
