# AI_STATE.md
_Last updated: 2026-06-25_

RUN_ID: 2026-06-25-1
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/clever-cray-9np03s` — branched from `origin/main` at `f76cd26` (clean). This run's working branch (replaces the now-defunct `clever-cray-0zzng4` reference from the prior run). HEAD `f410486`.
⚠️ **Concurrent actor confirmed:** PR #6 (P2-DOM-01c) was built, reviewed, and approved entirely by a SEPARATE orchestrator/session (branch `claude/clever-cray-6b2yqf`, session `017jMeWPQi...`). The prior run's state said "P2-DOM-01c dispatched / in-progress" on THIS lineage, but no `column.py` ever landed here — the external session did it. **Lesson reinforced:** reconcile against live PRs/CI every run; never trust the prior run's "dispatched" claim without verifying a commit exists. Two orchestrators are operating on this repo concurrently.

---

## Current Project Phase
**Phase 2 — Diff Engine — in progress.** Phase 1 ✅ (M1 feature on main). Delta foundation: P2-DOM-01a+01b MERGED to main (PR #4, #5). **P2-DOM-01c in review (PR #6, ready to merge)**, **P2-DIFF-08 in review (PR #7, ready to merge)** — both green + reviewed this run.

Phase 0 ✅. Phase 1 domain ✅. Phase 1 infra ✅ MERGED. P1-TEST-02 `needs-human` (PR #3 human-closed; do NOT recreate).

---

## CI / PR Status
- **main**: at `f76cd26`, CI green. (No new merges to main this run — both open PRs are at the human merge gate.)
- **PR #7** `clever-cray-9np03s` → main — **P2-DIFF-08** (Kahn topo-sort + cycle detection). **CI GREEN 12/12** on `f410486`. Reviewed by `code-reviewer` (opus): one blocker **B1** (mypy-strict on test empty-input call) → fixed by `ci-recovery` (`f410486`, commit 1/3 of cap); no open review-fix. → **READY TO MERGE** (human gate). Commits: `9d1079f` (feat) + `f410486` (ci-recovery mypy fix).
- **PR #6** `clever-cray-6b2yqf` → main — **P2-DOM-01c** (column deltas). Built + reviewed + **APPROVED by the external session** (CI green 12/12, `mergeable_state: clean`, base = current main tip). → **READY TO MERGE** (human gate). NOT built by this lineage.
- **PR #5** (P2-DOM-01b): MERGED. **PR #4** (P2-DOM-01a): MERGED. **PR #2** (M1): MERGED. **PR #3** (P1-TEST-02): CLOSED-unmerged (human).
- **P4-TUI-02..08**: on main via `e4f0367` (external session/human).

---

## Execution Queue
1. **(human gate)** Merge **PR #6** (P2-DOM-01c) and **PR #7** (P2-DIFF-08) — both green + reviewed. Orchestrator does not auto-merge (§7). Merging PR #6 unblocks the d/e/f chain below.
2. **P2-DOM-01d/e/f** — index / constraint / schema+extension deltas. `blocked-on-merge`: each edits the shared `domain/delta/__init__.py`, which **PR #6 also edits** → cannot start a non-colliding branch until PR #6 merges (one-writer-per-file, §6). Run **sequentially** after PR #6 lands, one PR each. **P2-DOM-01f** lands LAST: composes the global `Delta` union (discriminated on `kind`) + retypes `DeltaSet.deltas` (closes RF-A `TODO(P2-DOM-01f)`).
3. **P2-DIFF-01** — diff engine visitor. `blocked` on all of P2-DOM-01b..f.
4. **TD-TOPO-01** (NEW, low priority, non-blocking) — refactor `topo_sort.py` from `id()`-keyed lookups (O(n·m)) to plain hashable-node dict (O(n+m)) per reviewer N1, before it sits on a hot path; plus test-hardening N2–N5 (assert non-cycle node excluded from cycle msg; add Hypothesis DAG property test; doc fix re `DeltaOp.NO_CHANGE`). Logged as tech-debt; pick up via `maintainer` or fold into P2-DIFF-01 work.
5. **P0-CI-03** — coverage gate. low priority, held.
6. **P1-INFRA-07** — multi-conn snapshot. deferred.

## Next Actions
- **No further developer dispatch this run** — the only non-colliding ready work (P2-DIFF-08) is done; d/e/f are gated on PR #6's merge. Loop pauses at the human merge gate.
- On next run: if PR #6 merged → dispatch developer on P2-DOM-01d (rebase onto new main first, §7.1). If PR #7 merged → P2-DIFF-08 done.
- PR #7 subscription active: self check-in scheduled ~1h to re-verify CI/merge state (webhooks don't deliver CI-success/merge).

## Ready To Merge
- **PR #7** `clever-cray-9np03s` — P2-DIFF-08. CI green 12/12 (`f410486`), reviewed (B1 resolved), 0 open review-fix.
- **PR #6** `clever-cray-6b2yqf` — P2-DOM-01c. CI green 12/12, reviewed + APPROVED, `mergeable_state: clean`.

## Needs Human
- [ ] PR-7-merge | P2-DIFF-08 ready to merge (CI green + reviewed, 0 open review-fix). | action: squash/rebase merge only (linear history §7.1); orchestrator does not auto-merge. | since: 2026-06-25-1  *(non-blocking)*
- [ ] PR-6-merge | P2-DOM-01c ready to merge (external-built, CI green + approved, mergeable clean). Merging this UNBLOCKS P2-DOM-01d/e/f. | action: squash/rebase merge only. | since: 2026-06-25-1  *(non-blocking)*
- [ ] concurrent-orchestrators | A second orchestrator session is operating on this repo (built PR #6 on `clever-cray-6b2yqf`). Risk of duplicate dispatch / fragmented state. | options: (A) designate ONE orchestrator session as authoritative / (B) accept and rely on per-run live-PR reconciliation. | since: 2026-06-25-1  *(non-blocking, but recommend resolving)*
- [ ] P1-TEST-02 | Inspector integration-tests PR (#3) closed without merge by the human. | root cause: human declined CI-only-validated integration tests (no local Docker). | options: (A) re-approach & retry / (B) defer & proceed Phase 2 / (C) leave M1 exit gate intentionally unmet. **Will NOT recreate without your call.** | since: 2026-06-22-1
- [ ] repo-branch-protection | GitHub branch protection not confirmed: disallow merge commits, require linear history (§7.1, one-time human action). | since: 2026-06-20-1  *(non-blocking)*

## Resolved
- **PR-5-merge** — DONE: human merged PR #5 (rebase) 2026-06-24. P2-DOM-01b on main.
- **PR-4-merge** — DONE: human merged PR #4 (rebase) 2026-06-23. P2-DOM-01a on main.
- **phase2-go-ahead** — confirmed: Phase 2 proceeding.

## Key Architectural Decisions
- **2026-06-25 P2-DIFF-08 topo_sort (PR #7):** generic, pure application-layer Kahn topological sort — `topological_sort[T](nodes, dependencies, *, key)`. NO `domain.delta` coupling (decoupled graph utility; import-linter 4/4 kept). Deterministic: ready nodes emitted smallest-by-`key` first (downstream passes `DeltaBase.sort_key`). Raises the EXISTING `shared.errors.CyclicDependencyError` (not a new class) on cycles, message names cycle members; `ValueError` on unknown prerequisite. **Known tech-debt (reviewer N1, non-blocking):** current `id()`-keyed implementation is O(n·m); refactor to hashable-node dict (TD-TOPO-01) before hot-path use.
- **2026-06-23 Delta-union discriminator convention (RF-B, ALL of P2-DOM-01b..f):** every concrete delta subclass declares a globally-unique `kind: Literal["<verb>_<object>"]`. **All discriminated unions — per-category aliases AND the global `Delta` union (P2-DOM-01f) — discriminate on `kind`, NOT `op`.** Rationale: `op` is shared across object kinds → `op`-discriminated global union raises TypeError (proven by regression test). `op` = coarse semantic op; `kind` = union discriminator. PR #6 (01c) follows this (6 column kinds, no collision with table kinds).
- 2026-06-23 P2-DOM-01a: `DeltaOp` StrEnum = generic op categories; subclasses narrow `op` to `Literal` + payload. `DeltaBase.sort_key` folds parent identity (RF-A) → total, collision-free ordering for topo-sort tie-break + stable JSON. `DeltaSet.deltas` = `tuple[DeltaBase, ...]`, lossy on subclass round-trip until **P2-DOM-01f retypes to the `Delta` union alias**.
- 2026-06-22 Phase 2 decomposition: delta package split b..f re-exported via `__init__.py`; engine/comparators/topo-sort/loaders in `application/diff/`; `pgsd diff` CLI = M2 gate.

## Run-History Note
- 2026-06-25 (RUN 2026-06-25-1): Full loop on isolated work. Dispatched developer→P2-DIFF-08 (PR #7, `9d1079f`) → reviewer (opus, CHANGES-REQUESTED: B1 mypy-strict-on-tests) → ci-recovery (devops, `f410486`, fixed B1) → CI green 12/12 → ready-to-merge. Root cause of B1/CI-red: developer ran `mypy src` but CI runs `mypy src/ tests/` — empty-literal call gave PEP 695 `T` no inference. Reconciled stale prior state: P2-DOM-01c was NOT this lineage's "in-progress" work — the external session built PR #6 (now also ready-to-merge). No new main merges (both PRs at human gate). d/e/f gated on PR #6 merge (shared `__init__.py`).
