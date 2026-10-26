# P5-PKG-01 — Build and release workflow design

**Status:** Approved by reviewer; implementation pending. Publishing itself needs explicit human approval.
**Date:** 2026-10-26
**Task:** `docs/TASKS.md` P5-PKG-01 "`uv build` + PyPI publish workflow" ·
roadmap row "Source → wheel/sdist/release workflow; `uv build`, test catalog resources và `pgsd` entry point"
**Plan:** `docs/plans/2026-10-26-p5-pkg-01-implementation-plan.md`

## Current state (2026-10-26)

- Build backend: hatchling; wheel packages `src/pgschemadiff`; sdist includes
  `src/pgschemadiff`, `README.md`, `LICENSE`, `pyproject.toml`.
- Version `0.0.0` in two places: `pyproject.toml` and
  `src/pgschemadiff/__init__.py` (`__version__`). The bundle manifest and TUI
  header read `importlib.metadata.version("pgschemadiff")`.
- Catalog SQL lives in `infrastructure/postgres/catalog/*.sql` and is loaded
  as package resources. `py.typed` exists.
- No release workflow, no tags. The name `pgschemadiff` is free on PyPI and
  TestPyPI (checked 2026-10-26).

## Goals

1. Single version source, set to `0.1.0` (first public pre-release).
2. CI proves every push builds an installable wheel and sdist whose installed
   `pgsd` runs and whose catalog SQL resources are present.
3. A tag-driven release workflow that publishes to PyPI with **trusted
   publishing** (OIDC, no API token in the repo), gated by a GitHub
   environment, plus a manual TestPyPI dry run.
4. Release instructions for the human steps.

## Non-goals

- No actual publish in this task. Creating a tag, configuring PyPI trusted
  publishers, and creating the GitHub `pypi` / `testpypi` environments are
  human actions done only after the user approves.
- No changelog automation, no signing/attestations beyond what the publish
  action does by default, no Homebrew/Docker images.
- No new project dependencies.

## Design

### Version

- `pyproject.toml`: `version = "0.1.0"`; classifier
  `Development Status :: 3 - Alpha`.
- `__init__.py`: `__version__` derived from
  `importlib.metadata.version("pgschemadiff")`, falling back to `"0+unknown"`
  on `PackageNotFoundError` (running from a source tree without install).
- A unit test asserts `pgschemadiff.__version__` equals the installed
  metadata version and `pgsd --version` prints it.

### Package contents

- Wheel must contain: all `pgschemadiff/**/*.py`, every
  `infrastructure/postgres/catalog/*.sql`, `py.typed`, the TUI `.tcss`
  stylesheets if any exist (check `presentation/tui/**`), and entry points
  `pgsd` and `pgschemadiff`.
- Wheel must not contain: `tests/`, `__pycache__`, `.pyc`.
- sdist: as today plus anything hatchling needs to rebuild the wheel from the
  sdist (verify by building a wheel from the sdist).
- Fix the license metadata only if `uv build` warns (prefer the PEP 639 form
  `license = "MIT"` + `license-files = ["LICENSE"]` if hatchling ≥ 1.27 accepts it).

### CI job `package` (in `.github/workflows/ci.yml`)

```
uv build                                   # dist/*.whl and dist/*.tar.gz
uvx twine check --strict dist/*            # metadata/README rendering
python scripts/check_dist.py dist          # content assertions (below)
uv venv /tmp/smoke && uv pip install --python /tmp/smoke dist/*.whl
/tmp/smoke/bin/pgsd --version              # prints 0.1.0
/tmp/smoke/bin/pgsd --help
/tmp/smoke/bin/python -c "<resource check: every catalog .sql readable via importlib.resources>"
```

`scripts/check_dist.py` (stdlib only: `zipfile`, `tarfile`) asserts the
content rules above for the wheel and the sdist and exits non-zero with a
clear list of violations. It also builds nothing and imports nothing from the
package. Upload `dist/` as a workflow artifact (retention 7 days).

### Release workflow `.github/workflows/release.yml` (new)

- Triggers: `push` of tags `v*`, and `workflow_dispatch` (TestPyPI only).
- Job `build`: checkout, `uv build`, `twine check`, `check_dist.py`, verify
  the tag (`GITHUB_REF_NAME` without the leading `v`) equals the project
  version (skipped for `workflow_dispatch`), upload `dist/` artifact.
- Job `publish-pypi` (tags only): `needs: build`, `environment: pypi`,
  `permissions: id-token: write` (and nothing else), download artifact,
  `pypa/gh-action-pypi-publish` pinned to a release tag (not a branch).
- Job `publish-testpypi` (dispatch only): same, `environment: testpypi`,
  `repository-url: https://test.pypi.org/legacy/`.
- Top-level `permissions: contents: read`. No secrets referenced.

### Docs

- `README.md`: Install section — `uv tool install pgschemadiff` and
  `pipx install pgschemadiff`; remove "(Phase 5)" placeholder wording.
- `docs/RELEASING.md` (new): one-time human setup (PyPI and TestPyPI trusted
  publisher: owner `hoand-dev`, repository `pgschemadiff`, workflow
  `release.yml`, environments `pypi` / `testpypi`; GitHub environments with
  required reviewer), then the release checklist: bump version, CI green,
  TestPyPI dry run via dispatch, tag `vX.Y.Z`, approve the `pypi`
  environment, verify `uv tool install pgschemadiff==X.Y.Z`.

## Safety

- Trusted publishing only; no tokens or passwords in the repo or workflow.
- `id-token: write` only on publish jobs; environment approval required.
- Nobody but the user creates tags or approves the `pypi` environment.

## Done when

1. Local: `uv build` succeeds; `python scripts/check_dist.py dist` passes;
   wheel installed into a scratch venv runs `pgsd --version` → `0.1.0`.
2. CI `package` job green on push; `release.yml` passes `actionlint`-level
   review (YAML valid; job conditions correct) — it is not triggered by this
   task.
3. Gate green; README and `docs/RELEASING.md` updated.
