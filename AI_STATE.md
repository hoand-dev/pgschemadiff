# AI_STATE.md
_Last updated: 2026-10-24_

RUN_ID: 2026-10-23-1
STATE: ACTIVE
STALL_COUNTER: 0

## Project
**pgschemadiff** — PostgreSQL schema diff & migration TUI + CLI (Textual, Python 3.13).
Goal: inspect two Postgres DBs, show schema diff, generate safe migration SQL.

## Active Branch
`main` — in sync with `origin/main` (pushed 2026-10-24 on user request).

---

## Current Project Phase
**Phase 3a — Migration Generator — in progress.**
- Phase 0 done except open P0-CI-03 coverage gate.
- Phase 1 domain/infrastructure done; `pgsd inspect` shipped. M1 caveat: P1-TEST-02 needs-human; 1000-object benchmark not measured; P1-INFRA-07 deferred.
- Phase 2 complete: `pgsd diff`, comparators, rename/ignore rules, dependencies, topo-sort, and tests done. M2 reached at unit level; Docker integration not run locally.
- P3-RISK-01 and P3-SQL-01 done. Next: P3-SQL-02 table emitter.
- Phase 4 TUI shell and seven views run on mock data; not wired to real use cases.

---

## CI / PR Status
- `main` pushed; CI run on `9527452` green (unit, lint, mypy, import-linter, integration via Testcontainers).
- `5f34d3f` (step 1 CI fix): integration job uses Testcontainers only and fails closed; the ANSI-colored `--help` unit assertion is fixed. The unit job on `origin/main` was red before it; remote CI re-check pending push.
- Local gate: ruff, ruff format, mypy strict, import-linter (4/4 KEPT), and 1,338 unit tests pass. Docker integration not run locally.
- P1-TEST-02 remains `needs-human` (PR #3 human-closed; do NOT recreate).

### Local gate status (this run, `uv run`)
`ruff check .` ✅ · `ruff format --check .` ✅ · `mypy src/ tests/` ✅ · `lint-imports` ✅ (4/4 contracts KEPT) · `pytest tests/unit` ✅ (1,338 passed). Docker integration not run locally.

---

## Execution Queue
1. **P3-OUT-01** — migration plan + multi-file bundle writer; design spec in progress (`docs/specs/2026-10-24-p3-out-01-migration-bundle-design.md`), then implementation slices.
2. **P3-APPLY-01** — PostgreSQL applier (must `SET standard_conforming_strings = on`, lock/statement timeouts, per-unit transactions, CONCURRENTLY units outside transactions).
3. **P3-CLI-01** — `pgsd generate` / `pgsd apply`.
4. **P3-TEST-01** — PG18 round-trip integration (M3 gate); **P3-TEST-02** — extend emitter snapshot corpus.
5. Tech debt: TD-INSPECT-01 (UNLOGGED), TD-INSPECT-02 (virtual generated columns), TD-EMIT-01 (indexes on partitioned tables).

## Next Actions
- Review P3-OUT-01 spec, then dispatch its implementation slices.

## Ready To Merge
- None.

## Needs Human
- [ ] P1-TEST-02 | Inspector integration tests: PR #3 was closed by human; do not recreate without direction. | options: authorize a new attempt / leave M1 caveat open | since: 2026-06-22
- [ ] repo-branch-protection | GitHub branch protection not confirmed (linear history / merge-commit policy). | options: confirm settings / leave unconfirmed | since: 2026-06-20 (non-blocking)
- [ ] repo-file-acl | Tracked files are owned by another SID; the working account has `RX,W` only, so delete/rename fail (`git mv`, `git checkout`, `uv sync` on `.venv`). Blocks archiving `PROGRESS.md`, `REVIEW.md`, `docs/migration.md` into `docs/archive/`. | options: fix ownership/ACL / keep files in place | since: 2026-10-23-1

## Resolved
- Phase 1 complete; `pgsd inspect` shipped. P1-TEST-02 remains needs-human.
- Phase 2 complete; `pgsd diff` shipped and M2 reached at unit level.
- P3-RISK-01 and P3-SQL-01 complete on `main`.

## Key Architectural Decisions
- **2026-10-23 P3-SQL-01:** SQL emission uses exact-type dispatch; `SqlStatement` carries forward SQL, transactional metadata, and originating `Delta`. Emit forward SQL only; do not fabricate rollback SQL. Open contract for P3-OUT-01: `down.sql` needs source state or an explicit irreversible annotation, and `MigrationWriter` must change from its current single-SQL-string port.
- **2026-10-23 P3-RISK-01:** Risk is an assessment separate from `Delta`; unknown exact delta subclasses fail closed as `BLOCKED`.
- **2026-06-29 P2-DIFF-01 (this run):** `Comparator` Protocol is `@runtime_checkable`; `kind: ObjectKind` class attribute + `compare(source, target) -> Iterable[DeltaBase]`. `DiffEngine` constructor indexed by `kind`; duplicate raises `DiffError`. `diff()` enumerates objects via `_fetch_objects_for_kind` (covers SCHEMA/EXTENSION/TABLE/INDEX; unknown kinds return `{}`), pairs by `QualifiedName`, sorts by `(namespace, name)` for determinism, dispatches, aggregates into `DeltaSet`. This is NOT a topo-sort — that is downstream.
- **2026-06-27 TD-TOPO-01:** `topo_sort` refactored from `id()`-keyed O(n·m) to direct hashable-node dicts → O(n+m); public signature unchanged.
- **2026-06-25 P2-DIFF-08 topo_sort:** generic pure application-layer Kahn sort; NO `domain.delta` coupling; deterministic smallest-by-`key` first; raises `CyclicDependencyError`.
- **2026-06-23 Delta-union discriminator convention (ALL P2-DOM-01b..f):** every concrete delta declares a globally-unique `kind`; all discriminated unions discriminate on `kind`, NOT `op`.
- **2026-06-23 P2-DOM-01a:** `DeltaBase.sort_key` folds parent identity (total order); `DeltaSet.deltas = tuple[Delta,...]` since P2-DOM-01f.

## Run-History Note
- 2026-10-23 (RUN 2026-10-23-1): Reconciled project docs and state. CI fixed in `5f34d3f`. Archive and plan rename moves are blocked by Windows ACLs; no push or commit performed by this session. Next: P3-SQL-02.
- 2026-06-29 (RUN 2026-06-29-2): Implemented P2-DIFF-01 (`Comparator` Protocol + `DiffEngine`). Branch `claude/progress-check-kspf8m`. AI_STATE.md reconciled: old stale reference to `claude/rebase-merge-main-u55dvs` removed; P2-DOM-01a..f all confirmed on current branch; P2-DIFF-08/TD-TOPO-01 confirmed done; P2-DIFF-01 now done. 990 unit tests pass.
