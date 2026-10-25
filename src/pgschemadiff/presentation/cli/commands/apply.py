"""``pgsd apply`` command implementation."""

from __future__ import annotations

import asyncio
import re
import sys
from typing import TYPE_CHECKING, NoReturn

import psycopg
import psycopg_pool
import typer

from pgschemadiff.application.migration.apply import (
    ApplyEvent,
    ApplyResult,
    StatementFinished,
    StatementStarted,
    UnitFailed,
    UnitFinished,
    UnitStarted,
    apply_migration,
)
from pgschemadiff.application.migration.bundle import ValidatedBundle, load_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.infrastructure.postgres.applier import open_executor
from pgschemadiff.shared.errors import ApplyMigrationError, MigrationError, RiskGateError

if TYPE_CHECKING:
    from pathlib import Path

_TIMEOUT_PATTERN = re.compile(r"(?:0|[0-9]+(?:ms|s|min))\Z")
_MAX_TIMEOUT_MS = 86_400_000  # Matches the executor's accepted range.


def _parse_timeout(value: str, option: str) -> int:
    """Convert a non-negative CLI timeout to milliseconds."""
    if _TIMEOUT_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Error: Invalid value for {option}.")
    if value == "0":
        return 0

    for suffix, multiplier in (("min", 60_000), ("ms", 1), ("s", 1_000)):
        if value.endswith(suffix):
            milliseconds = int(value[: -len(suffix)]) * multiplier
            if milliseconds > _MAX_TIMEOUT_MS:
                raise ValueError(f"Error: {option} must not exceed 24 hours.")
            return milliseconds
    raise ValueError(f"Error: Invalid value for {option}.")


def _exit(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _requires_destructive_approval(bundle: ValidatedBundle) -> bool:
    return any(unit.max_risk in {RiskLevel.DESTRUCTIVE, RiskLevel.BLOCKED} for unit in bundle.units)


async def _check_connectivity(db_url: str) -> None:
    """Check target connectivity without acquiring a migration lock."""
    connection = await psycopg.AsyncConnection.connect(db_url)
    try:
        await connection.execute("SELECT 1")
    finally:
        await connection.close()


async def _apply(
    bundle: ValidatedBundle,
    db_url: str,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
    approve_destructive: bool,
) -> ApplyResult:
    async with open_executor(
        db_url,
        lock_timeout_ms=lock_timeout_ms,
        statement_timeout_ms=statement_timeout_ms,
    ) as executor:
        return await apply_migration(
            bundle,
            executor,
            approve_destructive=approve_destructive,
            on_event=_print_event,
        )


def _read_bundle(bundle_dir: Path) -> ValidatedBundle:
    try:
        manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    except OSError:
        _exit("Error: Could not read migration bundle.", 1)

    try:
        return load_bundle(manifest_bytes, up_sql_bytes)
    except MigrationError as error:
        _exit(f"Error: Invalid migration bundle: {error}", 2)


def _confirm_risk(bundle: ValidatedBundle, *, dry_run: bool, yes: bool) -> tuple[bool, bool]:
    if any(unit.max_risk is RiskLevel.BLOCKED for unit in bundle.units):
        _exit("Migration bundle contains a BLOCKED unit and cannot be applied.", 2)

    destructive = _requires_destructive_approval(bundle)
    approved = yes
    if destructive and not dry_run and not yes:
        if not sys.stdin.isatty():
            _exit("Destructive migration requires --yes when stdin is non-interactive.", 2)
        try:
            approved = typer.confirm("This migration contains destructive changes. Continue?")
        except (KeyboardInterrupt, asyncio.CancelledError):
            _exit("Apply cancelled; earlier units remain applied.", 3)
        if not approved:
            _exit("Destructive migration was not approved.", 2)
    return destructive, approved


def _print_event(event: ApplyEvent) -> None:
    if isinstance(event, UnitStarted):
        line = f"unit {event.unit_index + 1}/{event.unit_count} started"
    elif isinstance(event, UnitFinished):
        line = f"unit {event.unit_index + 1}/{event.unit_count} finished"
    elif isinstance(event, StatementStarted):
        line = (
            f"unit {event.unit_index + 1}/{event.unit_count} "
            f"statement {event.statement_index + 1}/{event.statement_count} started "
            f"delta={event.delta_id} lines {event.line_range[0]}-{event.line_range[1]}"
        )
    elif isinstance(event, StatementFinished):
        line = (
            f"unit {event.unit_index + 1}/{event.unit_count} "
            f"statement {event.statement_index + 1}/{event.statement_count} finished "
            f"delta={event.delta_id} lines {event.line_range[0]}-{event.line_range[1]}"
        )
    elif isinstance(event, UnitFailed):
        sqlstate = event.sqlstate or "unknown"
        line = (
            f"unit {event.unit_index + 1}/{event.unit_count} "
            f"statement {event.statement_index + 1}/{event.statement_count} failed "
            f"delta={event.delta_id} lines {event.line_range[0]}-{event.line_range[1]} "
            f"error={event.error_class} SQLSTATE={sqlstate}"
        )
    else:
        return
    typer.echo(line, err=True)


def _print_apply_failure(error: ApplyMigrationError, bundle: ValidatedBundle) -> None:
    message = str(error)
    result = error.result
    if isinstance(result, ApplyResult) and result.failed_unit_index is not None:
        unit_index = result.failed_unit_index
        unit = bundle.units[unit_index] if 0 <= unit_index < len(bundle.units) else None
        statement_count = len(unit.statements) if unit is not None else "?"
        statement_index = result.failed_statement_index
        statement_position = statement_index + 1 if statement_index is not None else "?"
        line_range = result.line_range
        lines = f"{line_range[0]}-{line_range[1]}" if line_range is not None else "unknown"
        message += (
            f" Unit {unit_index + 1}/{result.unit_count} (index {unit_index}), "
            f"statement {statement_position}/{statement_count} (index {statement_index}), "
            f"delta={result.delta_id}, "
            f"lines {lines}, error={result.error_class}, "
            f"SQLSTATE={result.sqlstate or 'unknown'}."
        )
        if result.manual_inspection_required:
            message += (
                " PostgreSQL may have left an INVALID index; manually inspect and clean it up "
                "before retry."
            )
    _exit(message, 3)


def _print_dry_run(bundle: ValidatedBundle) -> None:
    for unit in bundle.units:
        mode = "transactional" if unit.transactional else "non-transactional"
        delta_ids = ",".join(unit.delta_ids) or "none"
        typer.echo(
            f"unit {unit.index + 1}/{len(bundle.units)}: {mode}; "
            f"risk={unit.max_risk.value}; statements={len(unit.statements)}; "
            f"deltas={delta_ids}; lines={unit.start_line}-{unit.end_line}"
        )
    typer.echo("Dry-run does not prove permissions or future execution success.")


def _dry_run(bundle: ValidatedBundle, db_url: str, *, destructive: bool) -> None:
    if destructive:
        typer.echo(
            "Warning: bundle contains destructive-risk units; dry-run executes no migration SQL.",
            err=True,
        )
    try:
        asyncio.run(_check_connectivity(db_url))
    except (psycopg.Error, psycopg_pool.PoolTimeout):
        _exit("Error: Database connection failed.", 1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _exit("Apply cancelled; earlier units remain applied.", 3)
    except Exception:
        _exit("Error: Migration apply failed.", 3)
    _print_dry_run(bundle)


def _real_apply(
    bundle: ValidatedBundle,
    db_url: str,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
    approve_destructive: bool,
) -> None:
    try:
        result = asyncio.run(
            _apply(
                bundle,
                db_url,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                approve_destructive=approve_destructive,
            )
        )
    except (psycopg.Error, psycopg_pool.PoolTimeout):
        _exit("Error: Database connection failed.", 1)
    except RiskGateError as error:
        _exit(str(error), 2)
    except ApplyMigrationError as error:
        _print_apply_failure(error, bundle)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _exit("Apply cancelled; earlier units remain applied.", 3)
    except Exception:
        _exit("Error: Migration apply failed.", 3)

    outcome = "Resumed" if result.resumed else "Applied"
    typer.echo(
        f"{outcome} migration: units-applied={result.applied_unit_count}/"
        f"{result.unit_count} bundle={result.bundle_id}"
    )


def _apply_cmd(
    bundle_dir: Path,
    db_url: str,
    *,
    lock_timeout: str = "5s",
    statement_timeout: str = "0",
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    """Apply a validated migration bundle to PostgreSQL with risk confirmation."""
    try:
        lock_timeout_ms = _parse_timeout(lock_timeout, "--lock-timeout")
        statement_timeout_ms = _parse_timeout(statement_timeout, "--statement-timeout")
    except ValueError as error:
        _exit(str(error), 2)

    bundle = _read_bundle(bundle_dir)
    destructive, approve_destructive = _confirm_risk(bundle, dry_run=dry_run, yes=yes)
    if dry_run:
        _dry_run(bundle, db_url, destructive=destructive)
        return
    _real_apply(
        bundle,
        db_url,
        lock_timeout_ms=lock_timeout_ms,
        statement_timeout_ms=statement_timeout_ms,
        approve_destructive=approve_destructive,
    )


def apply_cmd(
    bundle_dir: Path,
    db_url: str,
    *,
    lock_timeout: str = "5s",
    statement_timeout: str = "0",
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    """Run ``pgsd apply`` with a redacted fallback for unexpected failures."""
    try:
        _apply_cmd(
            bundle_dir,
            db_url,
            lock_timeout=lock_timeout,
            statement_timeout=statement_timeout,
            dry_run=dry_run,
            yes=yes,
        )
    except typer.Exit:
        raise
    except (KeyboardInterrupt, asyncio.CancelledError):
        _exit("Apply cancelled; earlier units remain applied.", 3)
    except Exception:
        _exit("Error: Migration apply failed.", 3)
