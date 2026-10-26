# Roadmap — pgschemadiff

| Phase | Theme | Exit gate | Status |
|---|---|---|---|
| **Phase 0** | Stabilization | M0: CI green on empty project; layered architecture enforced | Done except open P0-CI-03 coverage gate |
| Phase 1 | Domain & Infrastructure (MVP-A) | M1: `pgsd inspect` dumps a JSON snapshot of a real PG18 database for tables/columns/indexes/FKs/constraints/schemas/extensions | Feature shipped; M1 caveat: P1-TEST-02 needs-human and 1000-object benchmark unmeasured |
| Phase 2 | Diff engine | M2: `pgsd diff` outputs a typed `DeltaSet` JSON; hypothesis idempotent-diff property passes | Done; M2 reached at unit level; Docker integration not run locally |
| Phase 3a | Migration generator (MVP-A) | M3: round-trip integration test green for MVP-A scope; `pgsd generate` + `pgsd apply` end-to-end | ✅ M3 reached 2026-10-26: PG18 round-trip corpus 48 passed, 0 xfail (CI `0c9536b`) |
| Phase 3b | MVP-B object types | M4: views, matviews, functions, procedures, sequences, enums, triggers, RLS policies, composite/domain types all covered with round-trip tests | ✅ M4 reached 2026-10-26: all ten object types round-trip on PG18 (CI `c8bb1c9`: 136 integration passed) |
| Phase 4 | TUI | M5: Textual TUI ships with the screens specified in `docs/ui-design.md` | ✅ M5 reached 2026-10-26 (CI `52b6eb9`): all seven views wired to real use cases; panels without a data source hidden (see `docs/ui-design.md` §10) |
| Phase 5 | Production readiness | M6: HTML report, i18n, benchmark suite (10k objects < 10s), PyPI release, safe-migration cookbook | _not started_ |

## Milestone exit criteria — details

### M0 (Phase 0)

- [ ] `uv sync --extra dev` resolves on clean checkout
- [ ] `uv run ruff check .` exits 0
- [ ] `uv run ruff format --check .` exits 0
- [ ] `uv run mypy src/ tests/` exits 0
- [ ] `uv run lint-imports` exits 0, all contracts KEPT
- [ ] `uv run pytest` passes (smoke suite only)
- [ ] GitHub Actions CI is green on the branch

### M1 (Phase 1)

- [ ] All MVP-A domain models exist and have ≥95% test coverage
- [ ] `pgsd inspect <conn-url>` produces valid JSON for a non-trivial schema
- [ ] Integration test suite green against postgres:18 container
- [ ] Benchmark: snapshot of 1000-object schema completes in < 2s on CI runner

### M2 (Phase 2)

- [ ] All MVP-A comparators implemented
- [ ] Round-trip property test green (`hypothesis max_examples=500`)
- [ ] `pgsd diff <src> <tgt>` emits ordered DeltaSet JSON
- [ ] Topological sort + cycle detection unit-tested with hand-crafted cycles

### M3 (Phase 3a) — go/no-go gate

- [x] All MVP-A emitters implemented with snapshot tests
- [x] Risk classifier assigns correct levels for the canonical test corpus
- [x] Multi-file migration output validates against schema
- [x] **Core round-trip integration test green** (37-scenario PG18 corpus; known gaps tracked as TD items):
      `apply(emit(diff(∅, S)))` → `inspect()` → equal to `S`
- [x] `pgsd generate` + `pgsd apply` end-to-end on a real PG18 container

### M4 (Phase 3b)

- [x] Catalog query + domain model + comparator + emitter + round-trip test for:
  views, matviews, functions, procedures, sequences, enums, triggers,
  RLS policies, composite types, domain types
- [x] Enum ADD VALUE positioning (BEFORE/AFTER) correctly emitted

### M5 (Phase 4)

- [x] `docs/ui-design.md` imported from user-supplied design
- [x] All screens implemented as Textual widgets
- [x] Use cases called only via `application/` ports — no business logic in TUI

### M6 (Phase 5)

- [ ] HTML diff report generator
- [ ] EN + VI message catalog
- [ ] Benchmark suite: 10k-object schema in < 10s end-to-end
- [ ] `uv build` wheel + sdist; published to PyPI
- [ ] Safe-migration cookbook in `docs/`

## Risk register

See the master plan (`/root/.claude/plans/t-i-ang-thi-t-k-groovy-blum.md`) for
the full Technical Debt & Risk table.
