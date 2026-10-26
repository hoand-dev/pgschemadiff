# P5-PKG-01 — Implementation plan

**Spec:** `docs/specs/2026-10-26-p5-pkg-01-build-release-design.md` (read it first; it wins on any conflict).
**Date:** 2026-10-26

Files you may touch: `pyproject.toml` (version, classifier, license metadata,
hatch build config only), `src/pgschemadiff/__init__.py`,
`scripts/check_dist.py` (new), `.github/workflows/ci.yml` (new `package` job
only), `.github/workflows/release.yml` (new), `README.md`, `docs/RELEASING.md`
(new), tests under `tests/unit/` (new `test_version.py`, `test_check_dist.py`).

Never: create git tags, push, publish to any index, run `uv sync`, or edit
`uv.lock` beyond what changing the project version requires (if `uv lock`
would be needed, report instead of running it).

## Step 1 — Single version source

1. Test first (`tests/unit/test_version.py`): `__version__` equals
   `importlib.metadata.version("pgschemadiff")`; `pgsd --version` prints
   `pgschemadiff <version>`.
2. Set `version = "0.1.0"` and the Alpha classifier in `pyproject.toml`;
   derive `__version__` from metadata with the `"0+unknown"` fallback.
3. Note: the shared review venv has the package installed as `0.0.0`
   metadata. Do not reinstall it. The version test must compare against
   metadata (not a literal), so it passes in both the old and a rebuilt env.

## Step 2 — Distribution checker

1. Tests first (`tests/unit/test_check_dist.py`): build tiny fake wheel and
   sdist archives in `tmp_path` with `zipfile`/`tarfile`; assert the checker
   passes a good pair and reports each violation (missing catalog `.sql`,
   missing `py.typed`, missing entry points in `entry_points.txt`, `tests/`
   present, `__pycache__`/`.pyc` present).
2. Implement `scripts/check_dist.py` (stdlib only; `main(argv) -> int`;
   derive the expected `.sql` list from `src/pgschemadiff/infrastructure/postgres/catalog/`
   at run time so new catalog files are covered automatically). Make it
   importable by tests (e.g. `importlib.util.spec_from_file_location`).

## Step 3 — Local build check

Run in the scratch area (never in the repo root `dist/` if that would be
committed; `dist/` must be git-ignored — add it to `.gitignore` only if
missing and report):

```
uv build --out-dir <scratch>/dist
python scripts/check_dist.py <scratch>/dist
uv venv <scratch>/smoke && uv pip install --python <scratch>/smoke <scratch>/dist/*.whl
<scratch>/smoke/Scripts/pgsd --version   (Windows path)
```

Also build a wheel from the sdist (`uv build --wheel <sdist>`) and check it.
If `uv build` warns about license metadata, apply the spec's PEP 639 fix.
Paste outputs in the report.

## Step 4 — CI `package` job

Add per spec to `ci.yml` (same setup steps as other jobs; Linux paths). Upload
`dist/` artifact.

## Step 5 — `release.yml`

Write per spec. Pin `pypa/gh-action-pypi-publish` to a release tag. Validate
YAML parses (`python -c "import yaml,sys; yaml.safe_load(open(...))"`) and
double-check the `if:` conditions so tag pushes publish only to PyPI and
dispatch only to TestPyPI.

## Step 6 — Docs

README Install section; new `docs/RELEASING.md` per spec.

## Step 7 — Verification and report

Full gate from the common rules (paste tails) plus step 3 outputs. Report
files, the license-metadata decision, the pinned action version, anything left
open (human steps).
