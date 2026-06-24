# AI_STATE.md
_Last updated: 2026-06-24_

RUN_ID: 2026-06-24-2
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/clever-cray-6b2yqf` — branched from `origin/main` at `f76cd26` (clean). **This is the designated working branch for the current session** (the prior session's `clever-cray-0zzng4` is now defunct — its head `f76cd26` was already on main; no unmerged work there). Continuing Phase 2 here.
⚠️ **Branch handoff note:** the 2026-06-24-1 run dispatched P2-DOM-01c on `0zzng4` but that session ended before any code landed (no commit/PR). This run (2026-06-24-2) re-executed P2-DOM-01c on the new designated branch `clever-cray-6b2yqf`. Reconcile against live main/PRs each step (single-writer lesson).

---

## Current Project Phase
**Phase 2 — Diff Engine — in progress.** Phase 1 ✅ (M1 feature on main). Delta foundation landing progressively: **P2-DOM-01a MERGED (PR #4), P2-DOM-01b MERGED (PR #5), P2-DOM-01c (column deltas) reviewed APPROVED + CI green → PR #6 READY TO MERGE (human gate).** Remaining category modules: P2-DOM-01d/e/f; plus P2-DIFF-08 topo-sort (independent).

Phase 0 ✅. Phase 1 domain ✅. Phase 1 infra ✅ MERGED. P1-TEST-02 `needs-human` (PR #3 human-closed; do NOT recreate).

---

## CI / PR Status
- **main**: at `f76cd26`, CI **green** (success). Includes P2-DOM-01a+01b (delta foundation + table deltas) and the externally-landed TUI views (P4-TUI-02..08).
- **Open PRs**: **PR #6** `clever-cray-6b2yqf` → main — **P2-DOM-01c** (column deltas, `035ab72`): CI **green** (run #101 success), reviewer **APPROVED** (0 blockers), `mergeable_state: clean` → **READY TO MERGE (human gate).** Orchestrator subscribed to PR #6 activity.
- **PR #5** (P2-DOM-01b): MERGED. **PR #4** (P2-DOM-01a): MERGED. **PR #2** (M1): MERGED. **PR #3** (P1-TEST-02): CLOSED-unmerged (human).
- **P4-TUI-02..08**: landed on main via `e4f0367` (NOT orchestrator-dispatched — external session/human).

---

## Execution Queue
1. **(review — Ready To Merge, awaiting human)** **P2-DOM-01c** — Column deltas (PR #6). Done from the orchestrator's side: gate green, reviewed APPROVED. Awaiting human squash/rebase merge.
2. **P2-DOM-01d** — Index deltas (`domain/delta/index.py` + test, re-export via `__init__.py`). `ready`. **NEXT to dispatch** once PR #6 merges (it edits the shared `domain/delta/__init__.py` → must not run concurrently with #6's branch). MUST adopt the `kind` convention.
3. **P2-DOM-01e** — Constraint deltas. `ready`. After d.
4. **P2-DOM-01f** — Schema + extension deltas. `ready`. Lands LAST: composes the global `Delta` union (discriminated on `kind`) from all category aliases AND retypes `DeltaSet.deltas` to that union (closes RF-A's `TODO(P2-DOM-01f)`).
5. **P2-DIFF-08** — `topo_sort.py` (Kahn + cycle detection). `ready` (dep only P2-DOM-01a); **independent files (no `__init__.py` touch)** — can be dispatched on its own branch/PR without serializing against d/e/f, but single-designated-branch constraint applies this session (no new branches without human permission).
6. **P2-DIFF-01** — diff engine visitor. `blocked` on all of P2-DOM-01b..f.
7. **P0-CI-03** — coverage gate. low priority, held (validate headroom first).
8. **P1-INFRA-07** — multi-conn snapshot. deferred.

## Next Actions
- **Awaiting human merge of PR #6.** Webhooks don't deliver CI-success/merge transitions → next scheduled orchestrator run re-checks PR #6 state.
- After PR #6 merges → P2-DOM-01c done → dispatch P2-DOM-01d (then e, f). Single-branch sequential development (no new branches without human permission); d/e/f serialized on the shared `__init__.py`.
- Per-task review nits from PR #6 logged as non-blocking tech-debt (see Tech-Debt Backlog) — fold into a future maintainer/P2-DOM-01f pass, not separate PRs.

## Ready To Merge
- **PR #6** `clever-cray-6b2yqf` → main — P2-DOM-01c column deltas. CI green (run #101), reviewer APPROVED, 0 open review-fix, `mergeable_state: clean`. **Merge mode: squash or rebase only (§7.1).**

## Tech-Debt Backlog (non-blocking, from PR #6 review)
- `column.py` SetColumnDefault docstring: add cross-ref to the deliberate divergence from `AlterTableAttrs.new_comment` (None=DROP vs None=unchanged).
- `identity.py`: `ObjectRef` lacks a parent-namespace consistency validator (docstring claims schema mirrors parent); `sort_key` trusts it. Future ObjectRef-hardening task.
- `test_column.py:929-963`: 7 `test_package_exports_*` assert vacuous `issubclass(X, object)`; replace with load-bearing assertion.
- `docs/PROJECT_CONTEXT.md`: stale claim `DeltaOp` has `NO_CHANGE` (removed in RF-A) — fix in doc-sync pass.

## Needs Human
- [ ] PR-6-merge | PR #6 (P2-DOM-01c column deltas) is CI-green + reviewer-APPROVED + 0 open review-fix → ready for human squash/rebase merge. | root cause: §7 merge is a human gate; orchestrator never auto-merges. | options: (A) merge PR #6 (squash/rebase) → unblocks P2-DOM-01d / (B) request changes. | since: 2026-06-24-2  *(non-blocking)*
- [ ] P1-TEST-02 | Inspector integration-tests PR (#3) closed without merge by the human. | root cause: human declined CI-only-validated integration tests (no local Docker to validate pre-merge). | options: (A) re-approach & retry / (B) defer & proceed Phase 2 (in progress) / (C) leave M1 exit gate intentionally unmet. **Will NOT recreate without your call.** | since: 2026-06-22-1
- [ ] repo-branch-protection | GitHub branch protection not confirmed: disallow merge commits, require linear history (§7.1, one-time human action). PRs #2/#4 both landed linear (rebase) — but protection not verified as enforced. | since: 2026-06-20-1  *(non-blocking)*

## Resolved
- **PR-5-merge** — DONE: human merged PR #5 (rebase) 2026-06-24. P2-DOM-01b table deltas on main.
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
