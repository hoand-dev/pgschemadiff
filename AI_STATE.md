# AI_STATE.md
_Last updated: 2026-06-23_

RUN_ID: 2026-06-23-1
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/clever-cray-0zzng4` — local == `origin/main` at `5b6e9c1` after PR #4 merged (rebase, linear). Continuing Phase 2 here. (Remote `0zzng4` was auto-deleted on merge; will re-push when the next task lands.)

---

## Current Project Phase
**Phase 2 — Diff Engine — in progress.** Phase 1 ✅ (M1 feature on main). **P2-DOM-01a (`domain/delta/` foundation) MERGED to main via PR #4** (2026-06-23, rebase). Now building out the category delta modules + topo-sort.

Phase 0 ✅. Phase 1 domain ✅. Phase 1 infra ✅ MERGED. P1-TEST-02 `needs-human` (PR #3 human-closed; do NOT recreate).

---

## CI / PR Status
- **main**: at `5b6e9c1`, includes merged PR #4 (P2-DOM-01a). Last CI on this head was green 12/12 (incl. Integration PG18).
- **PR #5** `clever-cray-0zzng4` → main — **P2-DOM-01b** (table-level deltas), head `df2b128`. Reviewed → CHANGES-REQUESTED (1 blocker: `op` can't discriminate the global union) → **RF-B landed** (`df2b128`): established the `kind` discriminator convention + validators. Local gate green (675 tests). **CI re-running.** Reviewed-once (§7). Subscribed.
- **PR #4** `clever-cray-0zzng4` → main: **MERGED** 2026-06-23 (rebase). Reviewed (RF-A resolved 2 blockers), reviewed-once §7.
- **PR #2** MERGED (M1). **PR #3** CLOSED-unmerged (P1-TEST-02, human).
- Stale orchestrator branches (192p05/9tgfsf/vqtao5) + old `0zzng4` head: **auto-deleted on PR #4 merge** — housekeeping item resolved.

---

## Execution Queue
1. **(in review — PR #5)** **P2-DOM-01b** — Table-level deltas. CI re-running on RF-B; on green → Ready To Merge (human gate).
1b. **(next dispatch after PR #5 merges)** **P2-DOM-01c** — Column deltas. Must adopt the `kind` discriminator convention (see Key Decisions).
2. **P2-DOM-01c/d/e/f** — column / index / constraint / schema+extension deltas. `ready` on deps, but **each edits the shared `domain/delta/__init__.py`** → run **sequentially** on the single working branch (one-writer-per-file, §6), one PR each, after the prior merges. P2-DOM-01f ALSO retypes `DeltaSet.deltas` to the concrete `Delta` union (closes RF-A's `TODO(P2-DOM-01f)`) — so it lands last (needs b..e subclasses).
3. **P2-DIFF-08** — `topo_sort.py` (Kahn + cycle detection). `ready` (dep only P2-DOM-01a); independent files (does NOT touch `delta/__init__.py`). Can interleave.
4. **P2-DIFF-01** — diff engine visitor. `blocked` on all of P2-DOM-01b..f.
5. **P0-CI-03** — coverage gate. low priority, held (validate headroom first).
6. **P1-INFRA-07** — multi-conn snapshot. deferred.

## Next Actions
- Dispatch `backend-engineer` → **P2-DOM-01b** on the working branch; gate → push → PR → reviewer → (RF if needed) → Ready To Merge (human gate).
- Single-branch sequential development (no new branches without human permission); b..f serialized on the shared `__init__.py`.

## Ready To Merge
- **PR #5** (P2-DOM-01b) — pending CI re-run on `df2b128`. Reviewer's blocker resolved by RF-B (reviewed-once, §7), 0 open review-fix. On CI green → flip to Ready To Merge + non-blocking human-merge note (self check-in armed).

## Needs Human
- [ ] P1-TEST-02 | Inspector integration-tests PR (#3) closed without merge by the human. | root cause: human declined CI-only-validated integration tests (no local Docker to validate pre-merge). | options: (A) re-approach & retry / (B) defer & proceed Phase 2 (in progress) / (C) leave M1 exit gate intentionally unmet. **Will NOT recreate without your call.** | since: 2026-06-22-1
- [ ] repo-branch-protection | GitHub branch protection not confirmed: disallow merge commits, require linear history (§7.1, one-time human action). PRs #2/#4 both landed linear (rebase) — but protection not verified as enforced. | since: 2026-06-20-1  *(non-blocking)*

## Resolved
- **PR-4-merge** — DONE: human merged PR #4 (rebase, linear) 2026-06-23. P2-DOM-01a on main.
- **phase2-go-ahead** — confirmed: human merged the first Phase 2 PR → Phase 2 proceeding (autonomous default-A validated).
- **stale-branches** — DONE: superseded branches auto-deleted on PR #4 merge.

## Key Architectural Decisions
- **2026-06-23 Delta-union discriminator convention (RF-B, applies to ALL of P2-DOM-01b..f):** every concrete delta subclass declares a **globally-unique** `kind: Literal["<verb>_<object>"]` field (e.g. `"create_table"`, `"rename_table"`, and future `"create_index"`, `"create_schema"`, …). **All discriminated unions — per-category aliases (`TableDelta`, …) AND the global `Delta` union (P2-DOM-01f) — discriminate on `kind`, NOT on `op`.** Rationale: `op` (CREATE/DROP/ALTER/RENAME) is shared across object kinds, so an `op`-discriminated global union raises `TypeError` (mapped to multiple choices) — proven by a regression test. `op` stays as the coarse *semantic* operation; `kind` is the *union discriminator*. C/D/E/F MUST follow this.
- 2026-06-23 P2-DOM-01a (`domain/delta/` package): `DeltaOp` StrEnum discriminator = generic op categories (NOT per-object-kind, avoids enum explosion); concrete subclasses (b..f) narrow `op` to `Literal[DeltaOp.X]` + add payload, mirroring `domain/constraint.py`'s discriminated union. `DeltaBase.sort_key` folds parent identity for sub-objects (RF-A) → total, collision-free deterministic ordering for P2-DIFF-08 + stable `pgsd diff` JSON. `DeltaSet.deltas` is `tuple[DeltaBase, ...]`, intentionally lossy on subclass round-trip (tested) until **P2-DOM-01f retypes it to the `Delta` discriminated-union alias**. `DeltaOp` = {CREATE, DROP, ALTER, RENAME, REPLACE} (NO_CHANGE removed in RF-A — no production consumer). No new ADR.
- 2026-06-22 Phase 2 decomposition (planner): delta package split b..f re-exported via `__init__.py`; engine/comparators/topo-sort/loaders in `application/diff/`; `pgsd diff` CLI = M2 gate.
- 2026-06-20 P1-CLI-01 `application/inspect/inspect_schema.py` use case — CLI delegates (ADR-0005). `normalize_type()` inside `_map_column`. ADR-0012: single REPEATABLE READ tx per inspect().

## Run-History Note
- 2026-06-23: Reconciled fragmented orchestrator state (authoritative 2026-06-22-1 run lived only on a side-branch; main/working-branch were stale). Consolidated onto the working branch; landed on main via PR #4. Full cycle this run: dispatch P2-DOM-01a → CI green → review (2 blockers) → RF-A → CI green → human merged. Lesson (recurring): single orchestrator working branch + always reconcile against live PR/CI.
