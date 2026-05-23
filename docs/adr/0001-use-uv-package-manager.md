# ADR-0001 — Use uv as the package manager

- **Status:** Accepted
- **Date:** 2026-05-23
- **Deciders:** @hoand-dev, AI Engineering Team

## Context

A greenfield Python 3.13 project needs a package manager. The two mainstream
choices in 2026 are **Poetry** and **uv**. Both support PEP 621 (declarative
`pyproject.toml`), lock files, and editable installs. The project will ship
both as a library and as a `uv tool install`-able CLI, and CI will need to
install Python 3.13 itself on runners that may not have it.

## Decision

We will use **uv (≥0.8)** as the sole package manager and Python version
manager for development, CI, and end-user installation.

## Consequences

- **Positive:**
  - PEP 621 native — no separate `poetry.lock` format
  - Resolver ~10-100× faster than Poetry
  - `uv python install 3.13` removes the need for `pyenv` / `actions/setup-python`
  - `uv tool install pgschemadiff` gives end users a `pipx`-style install
  - PEP 735 dependency groups supported natively
- **Negative:**
  - Smaller ecosystem of tooling integrations than Poetry (most editors now
    support uv, but some niche tools still lag)
  - Locking format is uv-specific (mitigated: uv exports `requirements.txt`)
- **Neutral:**
  - Contributors must install uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

## Alternatives considered

- **Poetry** — mature, widely known, but slower resolver and lagged on PEP 735
  at the time of this decision.
- **pip + pip-tools + tox** — flexible but requires gluing together 3+ tools
  to match what uv provides out of the box.
- **Hatch** — strong build backend, but its package-management story is less
  cohesive than uv's; we still use Hatchling as the build backend.

## References

- https://docs.astral.sh/uv/
- PEP 621, PEP 735
