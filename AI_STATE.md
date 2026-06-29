# AI_STATE.md
_Last updated: 2026-06-29_

RUN_ID: 2026-06-29-1
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/rebase-merge-main-u55dvs` — integration branch. Branched from `origin/main` at `27f63d7` (clean) and **integrates ALL outstanding feature/state branches into a single main-bound branch** (de-fragmentation run). Merged in order: PR #8 (TD-TOPO-01), PR #6 (P2-DOM-01c), then the bookkeeping-only branches `keen-bardeen-37hwd8` (RUN 2026-06-28-1) and `clever-cray-9np03s` (RUN 2026-06-25-2). All merge conflicts resolved; full local gate re-verified green. Ready to merge to `main`.

---

## Current Project Phase
**Phase 2 — Diff Engine — in progress.** Phase 1 ✅ (M1 feature on main).
Delta foundation: P2-DOM-01a+01b MERGED. **P2-DIFF-08 MERGED (PR #7) + refactored under TD-TOPO-01 (PR #8) → done.** **P2-DOM-01c (PR #6) column deltas now INTEGRATED on this branch (conflict resolved) → done.** d/e/f now UNBLOCKED once this branch lands on main.
P1-TEST-02 `needs-human` (PR #3 human-closed; do NOT recreate).

---

## CI / PR Status
- **main**: at `27f63d7` (pre-integration). This branch advances it with PR #6 + PR #8 + reconciled bookkeeping.
- **PR #7** `clever-cray-9np03s` → main — **P2-DIFF-08** (Kahn topo-sort): **MERGED.** → P2-DIFF-08 done.
- **PR #6** `clever-cray-6b2yqf` → main — **P2-DOM-01c** (column deltas): **INTEGRATED on this branch.** The old `dirty`/CONFLICTED state (base `f76cd26` vs advanced main `27f63d7`) was resolved here via a 3-way merge — only the bookkeeping/doc files conflicted; all column-delta code applied cleanly and `topo_sort.py` (from PR #7/#8) was preserved.
- **PR #8** `keen-bardeen-m2qquj` → main — **TD-TOPO-01** (topo_sort O(n+m) + test hardening): **INTEGRATED on this branch** (clean merge).
- **PR #5/#4/#2**: MERGED. **PR #3** (P1-TEST-02): CLOSED-unmerged (human).
- **P4-TUI-02..08**: on main via `e4f0367` (external/human).

### Integration verification (this run, real `uv run` after `uv sync --extra dev`)
`ruff check .` ✅ · `ruff format --check .` ✅ (91 files) · `mypy src/ tests/` ✅ (no issues, 92 files) · `lint-imports` ✅ (4/4 contracts KEPT) · `pytest tests/unit` ✅ (766 passed, 6 snapshots). Integration tests require Docker → not run locally (unchanged from CI).

---

## Execution Queue
1. **(human gate)** Merge this integration branch (`claude/rebase-merge-main-u55dvs`) → `main`. Carries PR #6 + PR #8 + reconciled state. Closes/supersedes PRs #6 and #8.
2. **P2-DOM-01d/e/f** — index / constraint / schema+extension deltas. UNBLOCKED once this lands (shared `domain/delta/__init__.py` no longer contended). Sequential; **01f LAST** (composes global `Delta` union, retypes `DeltaSet.deltas`, closes RF-A TODO).
3. **P2-DIFF-01** — diff engine visitor. `blocked` on all P2-DOM-01b..f.
4. **P0-CI-03** — coverage gate. low, held.  **P1-INFRA-07** — multi-conn snapshot. deferred.

## Next Actions
- Land this integration branch on `main`, then dispatch P2-DOM-01d (rebase onto new main first).
- Concurrent-orchestrator fragmentation is now collapsed onto this single branch — keep one authoritative branch going forward.

## Ready To Merge
- **`claude/rebase-merge-main-u55dvs`** — integration branch (PR #6 + PR #8 + reconciled bookkeeping). Full local gate GREEN. Supersedes the separate PR #6 / PR #8 merges.

## Needs Human
- [ ] integration-merge | Integration branch `claude/rebase-merge-main-u55dvs` (PR #6 + PR #8 + reconciled state) is gate-green and ready to land on `main`. | action: merge to main (then PRs #6/#8 can be closed as superseded). | since: 2026-06-29-1
- [ ] P1-TEST-02 | Inspector integration-tests PR (#3) closed without merge by human. | options: (A) re-approach & retry / (B) defer & proceed Phase 2 / (C) leave M1 exit gate intentionally unmet. **Will NOT recreate without your call.** | since: 2026-06-22-1
- [ ] repo-branch-protection | GitHub branch protection not confirmed: disallow merge commits, require linear history (§7.1, one-time human action). | since: 2026-06-20-1  *(non-blocking)*

## Resolved
- **PR-6-rebase / concurrent-orchestrators** — RESOLVED 2026-06-29: all outstanding branches (PR #6, PR #8, and the `37hwd8`/`9np03s` bookkeeping branches) integrated onto the single branch `claude/rebase-merge-main-u55dvs`; PR #6 conflict resolved via 3-way merge; fragmented state collapsed onto one branch.
- **PR-7-merge** — DONE: human merged PR #7 (rebase) 2026-06-26. P2-DIFF-08 on main → done.
- **PR-5-merge / PR-4-merge** — DONE (human, rebase). P2-DOM-01a/01b on main.
- **phase2-go-ahead** — confirmed.

## Key Architectural Decisions
- **2026-06-27 TD-TOPO-01 (PR pending):** `topo_sort` refactored from `id()`-keyed O(n·m) to direct hashable-node dicts → O(n+m); public signature `topological_sort[T](nodes, dependencies, *, key)` and behavior unchanged (still raises existing `CyclicDependencyError` naming cycle members; `ValueError` on unknown prerequisite). Added Hypothesis DAG property test (max_examples=200). Added narrowly-scoped mypy overrides (`hypothesis.*` ignore_missing_imports; `disallow_any_unimported=false` for the one topo_sort test module) — mirrors existing `testcontainers.*`/`tests.integration.*` patterns. **Pending verify (real `uv run mypy`) + reviewer confirmation that the overrides are necessary, not masking.**
- **2026-06-25 P2-DIFF-08 topo_sort (merged):** generic pure application-layer Kahn sort; NO `domain.delta` coupling; deterministic smallest-by-`key` first; raises existing `CyclicDependencyError`.
- **2026-06-23 Delta-union discriminator convention (RF-B, ALL of P2-DOM-01b..f):** every concrete delta declares a globally-unique `kind`; all discriminated unions (per-category + global `Delta`) discriminate on `kind`, NOT `op` (`op` shared across kinds → TypeError). PR #6 (01c) follows this.
- **2026-06-23 P2-DOM-01a:** `DeltaBase.sort_key` folds parent identity (total order); `DeltaSet.deltas = tuple[DeltaBase,...]`, lossy until P2-DOM-01f retypes to `Delta` union.

## Run-History Note
- 2026-06-27 (RUN 2026-06-27-1): Reconciled stale main-state (27f63d7 / RUN 2026-06-25-1) against live GitHub: **PR #7 merged → P2-DIFF-08 done**; **PR #6 now CONFLICTED** (dirty) → escalated rebase (external branch, NOT force-pushed). Discovered a concurrent orchestrator already ran RUN 2026-06-25-2 (commit `0950695` on clever-cray-9np03s, not on main) — confirms worsening multi-orchestrator fragmentation. Only non-colliding `ready` work was **TD-TOPO-01** (topo_sort O(n+m) refactor + DAG property test) → dispatched maintainer (backend-engineer), committed `2fd9871`, pushed. Dispatched `verify` + `code-reviewer` on it. Caught the maintainer's mypy report running bare `mypy` (not `uv run mypy`) → phantom 555 errors; real CI invocation is `uv run mypy src/ tests/`. Awaiting verify/review verdicts before declaring TD-TOPO-01 review-ready.
