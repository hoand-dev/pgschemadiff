# pgschemadiff — Sub-agent Roster

Project-scoped Claude Code sub-agents that automate the routine work of the
master plan. Invoke via the `Agent` tool with `subagent_type=<name>`.

| Agent | When to use | Tools | Model |
|---|---|---|---|
| `backend-engineer` | Implement domain / application / infrastructure code (models, comparators, emitters, inspector). Runs the full verification pipeline before reporting done. | Read, Write, Edit, Bash, Glob, Grep | sonnet |
| `qa-engineer` | Write unit / snapshot / property / integration tests. Owns fixtures and coverage. | Read, Write, Edit, Bash, Glob, Grep | sonnet |
| `code-reviewer` | Strict pre-merge review against Clean Architecture + ADRs + SOLID. Never writes code. | Read, Bash, Glob, Grep | opus |
| `devops-engineer` | `pyproject.toml`, `uv.lock`, GitHub Actions, pre-commit, packaging, benchmarks. Doesn't touch business logic. | Read, Write, Edit, Bash, Glob, Grep | sonnet |
| `architect` | ADRs, domain ports, layer contracts, technology decisions. Writes specs; delegates implementation. | Read, Write, Edit, Bash, Glob, Grep | opus |
| `verify` | Runs the full local verification pipeline (`ruff` + `mypy` + `lint-imports` + `pytest`). Reports only — no edits. | Read, Bash, Glob, Grep | haiku |
| `tui-engineer` | Textual TUI screens. **Currently BLOCKED** until `docs/ui-design.md` exists (task `P4-UX-01`). | Read, Write, Edit, Bash, Glob, Grep | sonnet |

## Recommended task routing

| Task family | Primary agent | Reviewer |
|---|---|---|
| Pydantic domain models (`P1-DOM-*`, `P2-DOM-*`) | `backend-engineer` | `code-reviewer` |
| Catalog SQL queries (`P1-INFRA-02..04`) | `backend-engineer` | `architect` then `code-reviewer` |
| Inspector (`P1-INFRA-05`) | `backend-engineer` | `code-reviewer` |
| Diff comparators (`P2-DIFF-02..05`) | `backend-engineer` | `code-reviewer` |
| SQL emitters (`P3-SQL-02..05`) | `backend-engineer` (+ snapshots by `qa-engineer`) | `code-reviewer` |
| Risk classifier (`P3-RISK-01`) | `backend-engineer` (or `architect` if classification rules need ADR) | `code-reviewer` |
| Integration / round-trip tests (`P1-TEST-*`, `P2-TEST-*`, `P3-TEST-*`) | `qa-engineer` | `code-reviewer` |
| CI workflow tweaks (`P0-CI-*`, `P5-PKG-*`) | `devops-engineer` | `code-reviewer` |
| New ADR | `architect` | the user |

## Routine: completing a task end-to-end

1. **Plan:** consult `docs/TASKS.md`. Pick a `[ ]` task whose dependencies are all `[x]`.
2. **Implement:** dispatch to the primary agent for that task family.
3. **Verify:** dispatch to `verify`. All gates green is the bar.
4. **Review:** dispatch to `code-reviewer` for any non-trivial change (skip for ADR-only or docs-only).
5. **Update state:** ensure the primary agent flipped `docs/TASKS.md` and `docs/PROJECT_CONTEXT.md`.
6. **Commit:** the user (or the parent agent) creates the commit and pushes.

## Routine: parallel batch dispatch

When multiple tasks have no dependency on each other (see `docs/TASKS.md`
"Parallel batches"), dispatch one `backend-engineer` call per task in a
single message — the agents run concurrently.

Example: after `P1-DOM-01` lands, fan out `P1-DOM-02`, `P1-DOM-03`,
`P1-DOM-05`, `P1-DOM-06` in parallel.

## Routine: handling a CI failure

1. Dispatch `verify` first to reproduce locally.
2. If reproduced, dispatch the appropriate engineer (matching the failure):
   - lint / format → `devops-engineer` *or* `backend-engineer` if the
     fix is in source
   - type errors → `backend-engineer`
   - test failure → `backend-engineer` (production code) *or*
     `qa-engineer` (test code)
   - architecture violation → `architect` first, then `backend-engineer`
3. Re-`verify`, then `code-reviewer`, then commit.

## Do-not-do list (for every agent)

- ❌ Commit or push without explicit human approval
- ❌ Skip the verification pipeline
- ❌ Edit files outside the agent's declared scope
- ❌ Add `# type: ignore` to silence mypy — fix the root cause
- ❌ Add `# noqa` to silence ruff — fix the root cause
- ❌ Bypass `import-linter` — escalate to `architect` instead
