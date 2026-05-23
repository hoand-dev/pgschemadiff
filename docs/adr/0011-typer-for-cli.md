# ADR-0011 — Use typer for the CLI

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

The project ships a `pgsd` CLI with sub-commands (`inspect`, `diff`,
`generate`, `apply`, …). The CLI must coexist with an async backend, support
rich help output, and play well with `--version`/`--help` automation.

## Decision

We use **typer** (≥0.12) for the CLI. The entry point is
`pgschemadiff.presentation.cli.main:app`. Each sub-command lives in
`presentation/cli/commands/<verb>.py`.

For sub-commands that call async code we wrap the use case with
`asyncio.run(...)` at the boundary — the application layer remains async.

## Consequences

- **Positive:**
  - Type hints become the CLI signature (low boilerplate)
  - Built-in shell completion, rich-formatted help
  - Easy to test via `typer.testing.CliRunner`
- **Negative:**
  - Bringing in `click` (typer's dependency) — already universal in Python
- **Neutral:**
  - Async support is via an explicit wrapper, not a typer extension.

## Alternatives considered

- **click** alone — typer is a thin layer on top; we get the same ecosystem
  with less boilerplate.
- **argparse** — stdlib, but verbose; rich help is harder.

## References

- https://typer.tiangolo.com/
