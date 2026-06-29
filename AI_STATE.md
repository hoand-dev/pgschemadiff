# AI_STATE.md
_Last updated: 2026-06-29_

RUN_ID: 2026-06-29-2
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`claude/progress-check-kspf8m` — current working branch. All P2-DOM-01a..f are on this branch; P2-DIFF-08 (topo_sort) is on this branch; P2-DIFF-01 (diff engine) is now also on this branch.

---

## Current Project Phase
**Phase 2 — Diff Engine — in progress.**
- Phase 1 ✅ (M1 feature complete).
- Delta foundation P2-DOM-01a..f ✅ ALL DONE on this branch.
- P2-DIFF-08 (topo_sort Kahn O(n+m)) ✅ DONE on this branch.
- P2-DIFF-01 (DiffEngine + Comparator Protocol) ✅ DONE on this branch (this run).
- Next: P2-DIFF-02..05 (concrete comparators for table/column/index/constraint) — all UNBLOCKED.

---

## CI / PR Status
- **main**: previous state; this branch advances main with all Phase 2 diff work.
- P2-DOM-01a..f: DONE on branch.
- P2-DIFF-08 (TD-TOPO-01): DONE on branch.
- P2-DIFF-01: DONE on branch (this session).
- P1-TEST-02: `needs-human` (PR #3 human-closed; do NOT recreate).

### Local gate status (this run, `uv run`)
`ruff check .` ✅ · `ruff format --check .` ✅ (99 files) · `mypy src/ tests/` ✅ (100 files, 0 issues) · `lint-imports` ✅ (4/4 contracts KEPT) · `pytest tests/unit` ✅ (990 passed, 6 snapshots). Integration tests require Docker → not run locally (testcontainers not installed in this environment).

---

## Execution Queue
1. **P2-DIFF-02** — `comparators/table.py` — table-level comparator. Unblocked by P2-DIFF-01.
2. **P2-DIFF-03** — `comparators/column.py` — column-level comparator. Depends on P2-DIFF-02.
3. **P2-DIFF-04** — `comparators/index.py` — index-level comparator. Unblocked by P2-DIFF-01.
4. **P2-DIFF-05** — `comparators/constraint.py` — constraint comparator (incl. FK). Unblocked by P2-DIFF-01.
5. **P2-DIFF-02 and P2-DIFF-04/05** can run in parallel (B3 batch per TASKS.md).
6. **P0-CI-03** — coverage gate. low priority, held.  **P1-INFRA-07** — multi-conn snapshot. deferred.

## Next Actions
- Dispatch P2-DIFF-02 and P2-DIFF-04/P2-DIFF-05 in parallel (they are independent).
- P2-DIFF-03 depends on P2-DIFF-02 (column comparator needs the table context).

## Ready To Merge
- `claude/progress-check-kspf8m` — all gate checks green on this branch (990 unit tests, 4/4 import-linter contracts, mypy strict).

## Needs Human
- [ ] P1-TEST-02 | Inspector integration-tests PR (#3) closed without merge by human. | options: (A) re-approach & retry / (B) defer & proceed Phase 2 / (C) leave M1 exit gate intentionally unmet. **Will NOT recreate without your call.** | since: 2026-06-22-1
- [ ] repo-branch-protection | GitHub branch protection not confirmed: disallow merge commits, require linear history (one-time human action). | since: 2026-06-20-1  *(non-blocking)*

## Resolved
- **P2-DIFF-01** — DONE 2026-06-29 (this run): `Comparator` Protocol + `DiffEngine` dispatcher. 40 new unit tests; 990 total pass. All 4 import-linter contracts KEPT. mypy strict clean.
- **P2-DOM-01d/e/f** — DONE: index/constraint/schema+extension deltas + global `Delta` union + `DeltaSet` retypes. All on this branch.
- **PR-7-merge / P2-DIFF-08** — DONE: merged. P2-DIFF-08 topo_sort on main.
- **PR-6-integration / P2-DOM-01c** — DONE: column deltas on this branch.
- **PR-5-merge / PR-4-merge** — DONE: P2-DOM-01a/01b on main.
- **phase2-go-ahead** — confirmed.
- **orchestrator-fragmentation** — resolved: single authoritative branch `claude/progress-check-kspf8m`.

## Key Architectural Decisions
- **2026-06-29 P2-DIFF-01 (this run):** `Comparator` Protocol is `@runtime_checkable`; `kind: ObjectKind` class attribute + `compare(source, target) -> Iterable[DeltaBase]`. `DiffEngine` constructor indexed by `kind`; duplicate raises `DiffError`. `diff()` enumerates objects via `_fetch_objects_for_kind` (covers SCHEMA/EXTENSION/TABLE/INDEX; unknown kinds return `{}`), pairs by `QualifiedName`, sorts by `(namespace, name)` for determinism, dispatches, aggregates into `DeltaSet`. This is NOT a topo-sort — that is downstream.
- **2026-06-27 TD-TOPO-01:** `topo_sort` refactored from `id()`-keyed O(n·m) to direct hashable-node dicts → O(n+m); public signature unchanged.
- **2026-06-25 P2-DIFF-08 topo_sort:** generic pure application-layer Kahn sort; NO `domain.delta` coupling; deterministic smallest-by-`key` first; raises `CyclicDependencyError`.
- **2026-06-23 Delta-union discriminator convention (ALL P2-DOM-01b..f):** every concrete delta declares a globally-unique `kind`; all discriminated unions discriminate on `kind`, NOT `op`.
- **2026-06-23 P2-DOM-01a:** `DeltaBase.sort_key` folds parent identity (total order); `DeltaSet.deltas = tuple[Delta,...]` since P2-DOM-01f.

## Run-History Note
- 2026-06-29 (RUN 2026-06-29-2): Implemented P2-DIFF-01 (`Comparator` Protocol + `DiffEngine`). Branch `claude/progress-check-kspf8m`. AI_STATE.md reconciled: old stale reference to `claude/rebase-merge-main-u55dvs` removed; P2-DOM-01a..f all confirmed on current branch; P2-DIFF-08/TD-TOPO-01 confirmed done; P2-DIFF-01 now done. 990 unit tests pass.
