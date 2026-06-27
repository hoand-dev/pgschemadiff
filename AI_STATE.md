# AI_STATE.md
_Last updated: 2026-06-27_

RUN_ID: 2026-06-27-1
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/keen-bardeen-m2qquj` — this run's designated working branch. Branched from `origin/main` at `27f63d7` (= current main tip, clean). HEAD `2fd9871` (TD-TOPO-01, pushed to origin).
⚠️ **Concurrent actors confirmed (worsening).** State is now fragmented across ≥3 orchestrator branches:
- `clever-cray-9np03s` — prior lineage that built PR #7. After PR #7 merged it ran a **RUN 2026-06-25-2** (state commit `0950695`, pushed only to that branch, NOT main) reaching the same conclusions this run did (PR #7 done; PR #6 conflicted → escalate rebase).
- `clever-cray-6b2yqf` — external session that built PR #6 (P2-DOM-01c).
- `keen-bardeen-m2qquj` — THIS session.
**Lesson reinforced:** reconcile against live PRs/CI every run; never trust prior "dispatched" claims. The authoritative state on `main` (27f63d7) is what this file is rebuilt from each run.

---

## Current Project Phase
**Phase 2 — Diff Engine — in progress.** Phase 1 ✅ (M1 feature on main).
Delta foundation: P2-DOM-01a+01b MERGED. **P2-DIFF-08 MERGED (PR #7, human, 2026-06-26) → done.** **P2-DOM-01c (PR #6) now CONFLICTED** (was ready-to-merge; main moved past its base). d/e/f remain blocked on PR #6.
P1-TEST-02 `needs-human` (PR #3 human-closed; do NOT recreate).

---

## CI / PR Status
- **main**: at `27f63d7`, **CI green** (verified via Actions API this run).
- **PR #7** `clever-cray-9np03s` → main — **P2-DIFF-08** (Kahn topo-sort): **MERGED (rebase, human, 2026-06-26).** → P2-DIFF-08 done.
- **PR #6** `clever-cray-6b2yqf` → main — **P2-DOM-01c** (column deltas, external-built). **`mergeable_state: dirty` (CONFLICTED)** — base is old main tip `f76cd26`; after PR #7 merged main → `27f63d7`, and PR #6's doc edits (`docs/TASKS.md`/`docs/PROJECT_CONTEXT.md`) now collide. **Needs REBASE onto main.** Branch is externally owned → this session does NOT force-push it (§5/§7.1). Escalated. **Still blocks P2-DOM-01d/e/f.**
- **PR #8** `keen-bardeen-m2qquj` → main — **TD-TOPO-01** (topo_sort O(n+m) + test hardening). HEAD `08879cb` (2 commits: `2fd9871` refactor + `08879cb` nitpick-fix). **verify + code-reviewer(opus) BOTH GREEN/APPROVED** (real `uv run mypy` clean 90 files, import-linter 4/4, pytest 720 passed, cov 87.2%; 0 merge-blockers; nitpicks RF-N1/N2 applied). **CI on PR #8 pending** → becomes ready-to-merge once CI green. Subscribed to PR #8 activity.
- **PR #5/#4/#2**: MERGED. **PR #3** (P1-TEST-02): CLOSED-unmerged (human).
- **P4-TUI-02..08**: on main via `e4f0367` (external/human).

---

## Execution Queue
1. **(human gate, this run)** **PR #8 (TD-TOPO-01)** — verify+review GREEN/APPROVED, nitpicks applied. Await PR #8 CI green → then ready-to-merge (human squash/rebase; orchestrator does not auto-merge §7). Subscribed for CI/review events.
2. **(human gate)** **PR #6 (P2-DOM-01c) REBASE** — conflicted; needs `git rebase origin/main` + conflict resolve on the **external** branch `clever-cray-6b2yqf`, OR human/external-session action. Merging PR #6 unblocks d/e/f. Orchestrator will NOT force-push an external branch (§5).
3. **P2-DOM-01d/e/f** — index / constraint / schema+extension deltas. `blocked` on PR #6 merge (shared `domain/delta/__init__.py`, §6). Sequential after PR #6 lands; **01f LAST** (composes global `Delta` union, retypes `DeltaSet.deltas`, closes RF-A TODO).
4. **P2-DIFF-01** — diff engine visitor. `blocked` on all P2-DOM-01b..f.
5. **P0-CI-03** — coverage gate. low, held.  **P1-INFRA-07** — multi-conn snapshot. deferred.

## Next Actions
- On verify+review return: finalize TD-TOPO-01 (open PR → review → ready-to-merge, OR dispatch fix).
- **No developer dispatch on d/e/f possible** until PR #6 merges (shared `__init__.py`). The loop is otherwise at the PR #6 human/rebase gate.
- Resolve the concurrent-orchestrator coordination (see Needs Human) — it is causing duplicate runs + fragmented state.

## Ready To Merge
- **PR #8** `keen-bardeen-m2qquj` — TD-TOPO-01. Reviewed APPROVED (opus) + local gate GREEN (both verify & reviewer), 0 open review-fix. **Pending PR-CI green** (squash/rebase only, §7.1); orchestrator does not auto-merge. *(non-blocking)*
- PR #6 is NOT here — it is `dirty`/conflicted (see Needs Human: PR-6-rebase).

## Needs Human
- [ ] PR-6-rebase | **P2-DOM-01c (PR #6) is CONFLICTED** (`mergeable_state: dirty`) after main advanced; it was ready-to-merge last run. Blocks all of P2-DOM-01d/e/f. | root cause: main moved `f76cd26`→`27f63d7` (PR #7 merge); PR #6's doc edits collide; base never rebased. | options: (A) human merges after rebasing, (B) external session (`clever-cray-6b2yqf`) rebases + force-pushes-with-lease, (C) authorize THIS session to rebase that external branch (needs explicit OK — §5 force-push-shared-branch). | since: 2026-06-27-1
- [ ] concurrent-orchestrators | ≥3 orchestrator branches now active on this repo (clever-cray-9np03s, clever-cray-6b2yqf, keen-bardeen-m2qquj); duplicate runs + fragmented state observed (RUN 2026-06-25-2 on clever-cray-9np03s duplicated this run's assessment). | options: (A) designate ONE authoritative orchestrator session/branch and stop the others / (B) accept and rely on per-run live reconciliation (current behavior). **Recommend (A).** | since: 2026-06-25-1
- [ ] P1-TEST-02 | Inspector integration-tests PR (#3) closed without merge by human. | options: (A) re-approach & retry / (B) defer & proceed Phase 2 / (C) leave M1 exit gate intentionally unmet. **Will NOT recreate without your call.** | since: 2026-06-22-1
- [ ] repo-branch-protection | GitHub branch protection not confirmed: disallow merge commits, require linear history (§7.1, one-time human action). | since: 2026-06-20-1  *(non-blocking)*

## Resolved
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
