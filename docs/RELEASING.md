# Releasing pgschemadiff

## One-time setup

1. On PyPI, add a trusted publisher for project `pgschemadiff` with owner
   `hoand-dev`, repository `pgschemadiff`, workflow `release.yml`, and
   environment `pypi`. Before the first release the project does not exist
   yet, so add it as a *pending* publisher (Account settings → Publishing).
2. On TestPyPI, add the same trusted publisher with environment `testpypi`.
3. In the GitHub repository settings, create `pypi` and `testpypi` environments
   and configure a required reviewer for each environment.

Trusted publishing uses GitHub's OIDC identity. Do not create or store API
tokens for these workflows.

## Release checklist

1. Set the project version in `pyproject.toml` and run `uv lock` so
   `uv.lock` records the same version.
2. Confirm CI is green.
3. Run the `Release` workflow with `workflow_dispatch` to publish a dry run to
   TestPyPI.
4. Create and push tag `vX.Y.Z` matching the project version.
5. Approve the `pypi` environment deployment in GitHub Actions.
6. Verify the published release with `uv tool install pgschemadiff==X.Y.Z`.
