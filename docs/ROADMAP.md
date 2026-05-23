# Roadmap — pgschemadiff

| Phase | Theme | Exit gate | Status |
|---|---|---|---|
| **Phase 0** | Stabilization | M0: CI green on empty project; layered architecture enforced | **In progress** |
| Phase 1 | Domain & Infrastructure (MVP-A) | M1: `pgsd inspect` dumps a JSON snapshot of a real PG18 database for tables/columns/indexes/FKs/constraints/schemas/extensions | _not started_ |
| Phase 2 | Diff engine | M2: `pgsd diff` outputs a typed `DeltaSet` JSON; hypothesis idempotent-diff property passes | _not started_ |
| Phase 3a | Migration generator (MVP-A) | M3: round-trip integration test green for MVP-A scope; `pgsd generate` + `pgsd apply` end-to-end | _not started_ |
| Phase 3b | MVP-B object types | M4: views, matviews, functions, procedures, sequences, enums, triggers, RLS policies, composite/domain types all covered with round-trip tests | _not started_ |
| Phase 4 | TUI | M5: Textual TUI ships with the screens specified in `docs/ui-design.md` | _blocked on user-supplied UI design_ |
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

- [ ] All MVP-A emitters implemented with snapshot tests
- [ ] Risk classifier assigns correct levels for the canonical test corpus
- [ ] Multi-file migration output validates against schema
- [ ] **Core round-trip integration test green**:
      `apply(emit(diff(∅, S)))` → `inspect()` → equal to `S`
- [ ] `pgsd generate` + `pgsd apply` end-to-end on a real PG18 container

### M4 (Phase 3b)

- [ ] Catalog query + domain model + comparator + emitter + round-trip test for:
  views, matviews, functions, procedures, sequences, enums, triggers,
  RLS policies, composite types, domain types
- [ ] Enum ADD VALUE positioning (BEFORE/AFTER) correctly emitted

### M5 (Phase 4)

- [ ] `docs/ui-design.md` imported from user-supplied design
- [ ] All screens implemented as Textual widgets
- [ ] Use cases called only via `application/` ports — no business logic in TUI

### M6 (Phase 5)

- [ ] HTML diff report generator
- [ ] EN + VI message catalog
- [ ] Benchmark suite: 10k-object schema in < 10s end-to-end
- [ ] `uv build` wheel + sdist; published to PyPI
- [ ] Safe-migration cookbook in `docs/`

## Risk register

See the master plan (`/root/.claude/plans/t-i-ang-thi-t-k-groovy-blum.md`) for
the full Technical Debt & Risk table.
